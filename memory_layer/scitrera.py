"""Persistent cognitive memory through the Scitrera MemoryLayer 0.2 REST API.

Working memory uses durable native memory rows, rather than expiring session KV
entries. Each app/user/type/session partition is a separate workspace. This is
data partitioning; the application must authenticate its user before calling us.
"""
import hashlib
import json
import threading
import uuid

import httpx

ALIASES = {'short_term': 'working', 'long_term': 'semantic'}
KINDS = {'working', 'semantic', 'episodic', 'procedural'}


class MemoryLayerRepository:
    def __init__(self, base_url='http://127.0.0.1:61001', *, api_key='', client=None):
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
        self.client = client or httpx.Client(base_url=base_url.rstrip('/'), headers=headers, timeout=30)
        self._lock = threading.RLock()
        self._workspaces = set()

    @staticmethod
    def cognitive_kind(kind):
        native = ALIASES.get(kind, kind)
        if native not in KINDS:
            raise ValueError('Unknown memory kind')
        return native

    @classmethod
    def workspace(cls, app, user, kind, session_id=''):
        native = cls.cognitive_kind(kind)
        if (native == 'working') != bool(session_id):
            raise ValueError('Working memory requires a session; durable memory must be user scoped')
        identity = json.dumps([app, user, native, session_id], ensure_ascii=False, separators=(',', ':'))
        return 'workshop_' + hashlib.sha256(identity.encode()).hexdigest()

    def _request(self, method, path, workspace, **kwargs):
        headers = {'X-Workspace-ID': workspace, **kwargs.pop('headers', {})}
        result = self.client.request(method, path, headers=headers, **kwargs)
        result.raise_for_status()
        return result

    @staticmethod
    def _tag(key):
        return 'workshop_key_' + hashlib.sha256(key.encode()).hexdigest()

    def _find(self, workspace, key, native):
        rows = self._request('GET', '/v1/memories', workspace,
                             params={'tag': self._tag(key), 'type': native, 'limit': 2}).json()['memories']
        matches = [row for row in rows if row.get('metadata', {}).get('_workshop', {}).get('key') == key]
        if len(matches) > 1:
            raise RuntimeError('Duplicate memory keys in MemoryLayer')
        return matches[0] if matches else None

    def _ensure_workspace(self, workspace):
        if workspace in self._workspaces:
            return
        try:
            self._request('GET', f'/v1/workspaces/{workspace}', workspace)
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
            try:
                # A scoped POST header makes server authentication auto-create
                # the target before the create handler, causing a duplicate.
                self._request('POST', '/v1/workspaces', '_default',
                              json={'id': workspace, 'name': workspace})
            except httpx.HTTPStatusError as race:
                if race.response.status_code != 409:
                    raise
        self._workspaces.add(workspace)

    @staticmethod
    def _record(row, kind, session_id):
        envelope = row.get('metadata', {}).get('_workshop', {})
        if not envelope.get('key'):
            raise RuntimeError('MemoryLayer returned an unmanaged memory row')
        return {'key': envelope['key'], 'text': row['content'],
                'metadata': envelope.get('metadata', {}), 'kind': kind,
                'cognitive_type': row['type'], 'session_id': session_id,
                'updated_at': row.get('updated_at') or row.get('created_at'),
                'memory_id': row['id'], 'backend': 'memorylayer'}

    def put(self, app, user, memory):
        native = self.cognitive_kind(memory.kind)
        workspace = self.workspace(app, user, memory.kind, memory.session_id)
        serialized = json.dumps(memory.metadata, allow_nan=False)
        if len(serialized.encode()) > 20000:
            raise ValueError('Metadata exceeds 20 KB')
        payload = {'content': memory.text, 'type': native, 'pinned': True,
                   'tags': [self._tag(memory.key)],
                   'metadata': {'_workshop': {'key': memory.key, 'metadata': memory.metadata}}}
        with self._lock:
            self._ensure_workspace(workspace)
            existing = self._find(workspace, memory.key, native)
            if existing:
                result = self._request('PUT', f"/v1/memories/{existing['id']}", workspace, json=payload)
            else:
                # Conditional keyed creation bypasses similarity deduplication;
                # identical content under different keys must remain distinct.
                create = {**payload, 'workspace_id': workspace, 'logical_key': memory.key,
                          'scope': 'workspace', 'user_id': user}
                try:
                    result = self._request('POST', '/v1/memories', workspace, json=create,
                                           headers={'Idempotency-Key': uuid.uuid4().hex, 'If-None-Match': '*'})
                except httpx.HTTPStatusError as error:
                    if error.response.status_code not in {409, 412}:
                        raise
                    existing = self._find(workspace, memory.key, native)
                    if not existing:
                        raise
                    result = self._request('PUT', f"/v1/memories/{existing['id']}", workspace, json=payload)
        return self._record(result.json()['memory'], memory.kind, memory.session_id)

    def search(self, app, user, query, limit, kind='long_term', session_id=''):
        native = self.cognitive_kind(kind)
        workspace = self.workspace(app, user, kind, session_id)
        if query.strip():
            response = self._request('POST', '/v1/memories/recall', workspace,
                                     json={'query': query, 'types': [native], 'limit': limit,
                                           'mode': 'rag', 'include_global': False,
                                           'include_global_user': False, 'include_associations': False,
                                           'min_relevance': 0.01, 'detail_level': 'full'})
        else:
            response = self._request('GET', '/v1/memories', workspace,
                                     params={'type': native, 'limit': limit})
        return [self._record(row, kind, session_id) for row in response.json()['memories']]

    def delete(self, app, user, key, kind='long_term', session_id=''):
        native = self.cognitive_kind(kind)
        workspace = self.workspace(app, user, kind, session_id)
        with self._lock:
            existing = self._find(workspace, key, native)
            if not existing:
                return False
            self._request('DELETE', f"/v1/memories/{existing['id']}", workspace, params={'hard': 'true'})
            return True

    def close(self):
        self.client.close()
