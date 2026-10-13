import sqlite3
import pytest
from capability_registry import RegistryService, Scope


def tool():
    """Approved calculator."""
    return 42


def registry(tmp_path):
    return RegistryService(tmp_path / 'registry.db', {'calculate': tool})


def test_persistent_and_cross_instance_invalidation(tmp_path):
    a = registry(tmp_path)
    b = registry(tmp_path)
    a.register('tool', 'calculate', {'description': 'Original calculator'})
    assert b.get('tool', 'calculate')['description'] == 'Original calculator'
    a.register('tool', 'calculate', {'description': 'Updated calculator'})
    assert b.get('tool', 'calculate')['description'] == 'Updated calculator'
    assert RegistryService(a.path, {'calculate': tool}).get('tool', 'calculate')['description'] == 'Updated calculator'
    a.delete('tool', 'calculate')
    assert b.get('tool', 'calculate') is None


def test_scopes_and_detached_cache_values(tmp_path):
    service = registry(tmp_path)
    alice, bob = Scope('app', 'alice', 'session'), Scope('app', 'bob', 'session')
    service.register('agent', 'analyst', {'goal': 'Review credit', 'tool_names': ['calculate']}, alice)
    assert service.get('agent', 'analyst', bob) is None
    assert service.get('agent', 'analyst', Scope('app', 'alice', 'another')) is None
    value = service.get('agent', 'analyst', alice)
    value['goal'] = 'mutated'
    assert service.search('agent', 'credit', alice)[0]['goal'] == 'Review credit'
    assert service.list('agent', bob) == []
    with pytest.raises(ValueError):
        service.get('agent', 'analyst')


def test_database_failure_does_not_publish_cache(tmp_path):
    service = registry(tmp_path)
    service.register('tool', 'calculate', {'description': 'old'})
    with sqlite3.connect(service.path) as conn:
        conn.execute("CREATE TRIGGER fail_update BEFORE UPDATE ON capability_entries BEGIN SELECT RAISE(ABORT, 'failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        service.register('tool', 'calculate', {'description': 'new'})
    assert service.get('tool', 'calculate')['description'] == 'old'
    assert registry(tmp_path).get('tool', 'calculate')['description'] == 'old'


def test_code_is_not_a_registry_capability(tmp_path):
    service = registry(tmp_path)
    with pytest.raises(ValueError):
        service.register('tool', 'shell', {'description': 'Execute commands'})
    with pytest.raises(ValueError):
        service.register('tool', 'calculate', {'nested': {'code': 'print(1)'}})
    with pytest.raises(ValueError):
        service.register('agent', 'evil', {'tool_names': ['shell']}, Scope('app', 'user', 's'))
    service.register('tool', 'calculate', {'description': 'Allowed'})
    assert service.bind_tools(['calculate'], {'calculate'}) == [tool]
    with pytest.raises(ValueError):
        service.bind_tools(['calculate'], set())


def test_bootstrap_source_qualified_skills(tmp_path):
    service = registry(tmp_path)
    counts = service.bootstrap()
    assert counts['skill'] == 199
    assert service.search('skill', 'dcf valuation')
    skill = service.get('skill', 'anthropics--dcf-model')
    assert skill['sha256'] and skill['license'] and skill['url']
    assert 'body' not in skill
    with sqlite3.connect(service.path) as conn:
        before = conn.execute('SELECT version FROM capability_version').fetchone()[0]
    service.bootstrap()
    with sqlite3.connect(service.path) as conn:
        assert conn.execute('SELECT version FROM capability_version').fetchone()[0] == before
