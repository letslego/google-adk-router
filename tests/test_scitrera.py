"""Contract tests for native cognitive memory and persona/session partitioning."""
import json

import httpx
import pytest

from memory_layer.scitrera import MemoryLayerRepository
from memory_layer.service import MemoryWrite


class MemoryAPI:
    def __init__(self):
        self.workspaces = set()
        self.rows = {}
        self.calls = []

    def __call__(self, request):
        workspace = request.headers['X-Workspace-ID']
        data = json.loads(request.content) if request.content else {}
        self.calls.append((request, data))
        path = request.url.path
        if path.startswith('/v1/workspaces/'):
            return httpx.Response(200 if workspace in self.workspaces else 404, json={})
        if path == '/v1/workspaces':
            # Authentication auto-creates scoped header workspaces before the
            # route handler. Creation must run under the default workspace.
            assert workspace == '_default'
            self.workspaces.add(data['id'])
            return httpx.Response(201, json={})
        if path == '/v1/memories' and request.method == 'POST':
            assert request.headers['If-None-Match'] == '*'
            assert request.headers['Idempotency-Key']
            row = {**data, 'id': f'mem_{len(self.rows)}', 'created_at': '2026-10-13T00:00:00Z'}
            self.rows[row['id']] = row
            return httpx.Response(201, json={'memory': row})
        if path.startswith('/v1/memories/') and path != '/v1/memories/recall':
            mid = path.rsplit('/', 1)[-1]
            assert self.rows[mid]['workspace_id'] == workspace
            if request.method == 'PUT':
                self.rows[mid].update(data)
                return httpx.Response(200, json={'memory': self.rows[mid]})
            assert request.url.params['hard'] == 'true'
            del self.rows[mid]
            return httpx.Response(204)
        rows = [row for row in self.rows.values() if row['workspace_id'] == workspace]
        if request.url.params.get('tag'):
            rows = [row for row in rows if request.url.params['tag'] in row['tags']]
        return httpx.Response(200, json={'memories': rows})


@pytest.fixture
def backend():
    api = MemoryAPI()
    client = httpx.Client(base_url='http://memory.test', transport=httpx.MockTransport(api))
    return MemoryLayerRepository(client=client), api


@pytest.mark.parametrize('kind', ['working', 'semantic', 'episodic', 'procedural', 'short_term', 'long_term'])
def test_native_types_and_durable_writes(backend, kind):
    repository, api = backend
    session = 'session_a' if kind in {'working', 'short_term'} else ''
    memory = MemoryWrite(key='answer_style', text='Concise USD answers', kind=kind,
                         session_id=session, metadata={'source': 'explicit_user'})
    result = repository.put('workshop', 'cfo', memory)
    assert result['cognitive_type'] == repository.cognitive_kind(kind)
    assert result['metadata'] == memory.metadata
    row = next(iter(api.rows.values()))
    assert row['pinned'] is True
    assert row['scope'] == 'workspace'
    assert repository.search('workshop', 'cfo', '', 10, kind, session)[0]['key'] == memory.key


def test_same_keys_upsert_and_identical_content_distinct_keys(backend):
    repository, api = backend
    repository.put('app', 'cfo', MemoryWrite(key='a', text='same'))
    repository.put('app', 'cfo', MemoryWrite(key='b', text='same'))
    repository.put('app', 'cfo', MemoryWrite(key='a', text='changed'))
    assert len(api.rows) == 2
    assert sorted(row['content'] for row in api.rows.values()) == ['changed', 'same']
    assert repository.delete('app', 'cfo', 'a')
    assert not repository.delete('app', 'cfo', 'a')
    assert len(api.rows) == 1


def test_persona_application_session_isolation_and_no_global_recall(backend):
    repository, api = backend
    repository.put('app', 'cfo', MemoryWrite(key='profile', text='CFO preference'))
    repository.put('app', 'analyst', MemoryWrite(key='profile', text='Analyst preference'))
    assert repository.search('app', 'auditor', '', 10) == []
    assert repository.search('other_app', 'cfo', '', 10) == []
    assert repository.search('app', 'cfo', 'preference', 10)[0]['text'] == 'CFO preference'
    request, body = api.calls[-1]
    assert body['include_global'] is False and body['include_global_user'] is False
    assert body['include_associations'] is False
    repository.put('app', 'cfo', MemoryWrite(key='turn', text='Private turn', kind='working', session_id='a'))
    assert repository.search('app', 'cfo', '', 10, 'working', 'b') == []
    assert not repository.delete('app', 'analyst', 'turn', 'working', 'a')


def test_aliases_share_partitions_and_failures_do_not_fallback(backend):
    repository, _ = backend
    assert repository.workspace('app', 'u', 'long_term') == repository.workspace('app', 'u', 'semantic')
    assert repository.workspace('app', 'u', 'short_term', 's') == repository.workspace('app', 'u', 'working', 's')
    for kind, session in [('working', ''), ('semantic', 's'), ('bogus', '')]:
        with pytest.raises(ValueError):
            repository.workspace('app', 'u', kind, session)
    unavailable = MemoryLayerRepository(client=httpx.Client(base_url='http://memory.test',
        transport=httpx.MockTransport(lambda request: httpx.Response(503))))
    with pytest.raises(httpx.HTTPStatusError):
        unavailable.search('app', 'u', '', 10)
