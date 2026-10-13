"""Synchronous repository adapter for the letslego/memlayer SDK bridge.

The bridge owns persistence using native SDK layers. This adapter neither
substitutes another backend nor stores a second copy. Caller identity must be
authenticated by the application before invoking the repository.
"""
import json

import httpx

NATIVE_LAYERS = frozenset({'working', 'profile', 'knowledge', 'episodic', 'operational'})
LAYER_ALIASES = {'short_term': 'working', 'long_term': 'profile',
                 'semantic': 'profile', 'procedural': 'knowledge'}


class MemLayerRepository:
    def __init__(self, base_url='http://127.0.0.1:61002', *, api_key='', client=None):
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
        self.client = client or httpx.Client(base_url=base_url.rstrip('/'), headers=headers, timeout=30)

    @staticmethod
    def native_layer(kind):
        layer = LAYER_ALIASES.get(kind, kind)
        if layer not in NATIVE_LAYERS:
            raise ValueError('Unknown MemLayer memory kind')
        return layer

    @classmethod
    def _scope(cls, app, user, kind, session_id):
        if not isinstance(app, str) or not isinstance(user, str) or not app or not user or max(len(app), len(user)) > 200:
            raise ValueError('Nonempty application and user IDs up to 200 characters required')
        layer = cls.native_layer(kind)
        if (layer == 'working') != bool(session_id):
            raise ValueError('Working memory requires a session; other layers are user scoped')
        return {'app': app, 'user': user, 'kind': layer, 'session_id': session_id}

    def _request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    @classmethod
    def _record(cls, record, kind, session_id):
        expected = cls.native_layer(kind)
        if record.get('kind') != expected or record.get('session_id', '') != session_id:
            raise RuntimeError('MemLayer bridge returned a memory outside the requested partition')
        for field in ('key', 'text', 'metadata', 'updated_at'):
            if field not in record:
                raise RuntimeError(f'MemLayer bridge memory is missing {field}')
        return {**record, 'kind': kind, 'memory_layer': expected, 'backend': 'letslego/memlayer'}

    def put(self, app, user, memory):
        scope = self._scope(app, user, memory.kind, memory.session_id)
        serialized = json.dumps(memory.metadata, allow_nan=False)
        if len(serialized.encode()) > 20000:
            raise ValueError('Metadata exceeds 20 KB')
        payload = {'app': app, 'user': user,
                   'memory': {**memory.model_dump(), 'kind': scope['kind']}}
        result = self._request('POST', '/memory/store', json=payload)
        record = self._record(result['memory'], memory.kind, memory.session_id)
        if record['key'] != memory.key:
            raise RuntimeError('MemLayer bridge returned a different memory key')
        return record

    def search(self, app, user, query, limit, kind='long_term', session_id=''):
        scope = self._scope(app, user, kind, session_id)
        if len(query) > 2000 or not 1 <= limit <= 50:
            raise ValueError('Query max 2000 characters; limit 1-50')
        result = self._request('GET', '/memory/search', params={**scope, 'query': query, 'limit': limit})
        return [self._record(record, kind, session_id) for record in result['memories']][:limit]

    def delete(self, app, user, key, kind='long_term', session_id=''):
        scope = self._scope(app, user, kind, session_id)
        result = self._request('DELETE', '/memory', json={**scope, 'key': key})
        if not isinstance(result.get('deleted'), bool):
            raise RuntimeError('MemLayer bridge returned an invalid delete result')
        return result['deleted']

    def close(self):
        self.client.close()
