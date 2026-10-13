"""Contract checks for the actual letslego/memlayer bridge adapter."""
import json
from types import SimpleNamespace

import httpx
import pytest

from memory_layer.memlayer import LAYER_ALIASES, NATIVE_LAYERS, MemLayerRepository


def write(kind='profile', key='preference', text='Concise USD answers', session_id='', metadata=None):
    payload = {'kind': kind, 'key': key, 'text': text, 'session_id': session_id, 'metadata': metadata or {}}
    return SimpleNamespace(**payload, model_dump=lambda: payload.copy())


class Bridge:
    def __init__(self):
        self.rows = {}
        self.calls = []

    def __call__(self, request):
        payload = json.loads(request.content) if request.content else dict(request.url.params)
        self.calls.append((request.method, request.url.path, payload))
        if request.url.path == '/memory/store':
            memory = payload['memory']
            key = (payload['app'], payload['user'], memory['kind'], memory['session_id'], memory['key'])
            row = {**memory, 'updated_at': '2026-10-13T00:00:00Z'}
            self.rows[key] = row
            return httpx.Response(200, json={'memory': row})
        scope = (payload['app'], payload['user'], payload['kind'], payload['session_id'])
        if request.method == 'DELETE':
            deleted = self.rows.pop((*scope, payload['key']), None) is not None
            return httpx.Response(200, json={'deleted': deleted})
        rows = [row for key, row in self.rows.items() if key[:4] == scope]
        if payload['query']:
            rows = [row for row in rows if payload['query'].lower() in row['text'].lower()]
        return httpx.Response(200, json={'memories': rows[:int(payload['limit'])]})


@pytest.fixture
def backend():
    bridge = Bridge()
    repository = MemLayerRepository(client=httpx.Client(base_url='http://bridge.test',
        transport=httpx.MockTransport(bridge)))
    return repository, bridge


@pytest.mark.parametrize('kind', sorted(NATIVE_LAYERS | LAYER_ALIASES.keys()))
def test_every_native_layer_and_alias(backend, kind):
    repository, bridge = backend
    layer = repository.native_layer(kind)
    session = 'session_a' if layer == 'working' else ''
    result = repository.put('app', 'cfo', write(kind, session_id=session, metadata={'source': 'user'}))
    assert result['kind'] == kind and result['memory_layer'] == layer
    assert result['backend'] == 'letslego/memlayer'
    assert bridge.calls[-1][2]['memory']['kind'] == layer
    assert repository.search('app', 'cfo', 'USD', 10, kind, session)[0]['metadata'] == {'source': 'user'}
    assert repository.delete('app', 'cfo', 'preference', kind, session)
    assert not repository.delete('app', 'cfo', 'preference', kind, session)


def test_personas_sessions_applications_and_alias_upsert(backend):
    repository, bridge = backend
    repository.put('app', 'cfo', write('semantic'))
    repository.put('app', 'analyst', write('profile', text='Detailed EUR answers'))
    repository.put('app', 'cfo', write('long_term', text='Concise GBP answers'))
    assert len(bridge.rows) == 2
    assert repository.search('app', 'cfo', '', 10, 'profile')[0]['text'] == 'Concise GBP answers'
    assert repository.search('app', 'auditor', '', 10, 'profile') == []
    assert repository.search('other', 'cfo', '', 10, 'profile') == []
    repository.put('app', 'cfo', write('working', session_id='a'))
    assert repository.search('app', 'cfo', '', 10, 'working', 'b') == []
    assert not repository.delete('app', 'analyst', 'preference', 'working', 'a')


def test_invalid_scope_bounds_metadata_and_failure_no_fallback(backend):
    repository, _ = backend
    for kind, session in [('working', ''), ('profile', 'a'), ('shell', '')]:
        with pytest.raises(ValueError):
            repository.search('app', 'u', '', 10, kind, session)
    with pytest.raises(ValueError):
        repository.search('app', '', '', 10)
    with pytest.raises(ValueError):
        repository.search('app', 'u', '', 51)
    with pytest.raises(ValueError):
        repository.put('app', 'u', write(metadata={'oversized': 'x' * 20001}))
    down = MemLayerRepository(client=httpx.Client(base_url='http://bridge.test',
        transport=httpx.MockTransport(lambda request: httpx.Response(503))))
    with pytest.raises(httpx.HTTPStatusError):
        down.search('app', 'u', '', 10)


def test_rejects_unexpected_layer_and_session_from_bridge():
    row = {'key': 'a', 'text': 'secret', 'metadata': {}, 'updated_at': 'today',
           'kind': 'working', 'session_id': 'another'}
    with pytest.raises(RuntimeError):
        MemLayerRepository._record(row, 'working', 'mine')
    with pytest.raises(RuntimeError):
        MemLayerRepository._record(row, 'profile', '')
