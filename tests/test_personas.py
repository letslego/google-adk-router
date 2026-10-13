"""Persistence and isolation of demo personas; this does not test authentication."""
import itertools
import pytest
from memory_layer.service import MemoryService, MemoryWrite, SQLiteMemoryRepository

PERSONAS = ('analyst', 'risk_reviewer', 'relationship_manager', 'auditor')

@pytest.fixture
def persona_database(tmp_path):
    path = tmp_path / 'personas.sqlite3'
    service = MemoryService(SQLiteMemoryRepository(path))
    for persona in PERSONAS:
        user = 'workshop_' + persona
        service.store('finance_dynamic', user, MemoryWrite(
            key='preference', text=f'{persona} reporting preference', metadata={'persona': persona}))
        for session in ('first', 'second'):
            service.store('finance_dynamic', user, MemoryWrite(
                key='turn', text=f'{persona} {session} confidential task',
                kind='short_term', session_id=session))
    return path

@pytest.mark.parametrize('persona', PERSONAS)
def test_persona_memory_survives_restart_and_keeps_session_scope(persona_database, persona):
    reopened = MemoryService(SQLiteMemoryRepository(persona_database))
    user = 'workshop_' + persona
    long = reopened.retrieve('finance_dynamic', user)
    assert [item['text'] for item in long] == [f'{persona} reporting preference']
    for session in ('first', 'second'):
        short = reopened.retrieve('finance_dynamic', user, kind='short_term', session_id=session)
        assert [item['text'] for item in short] == [f'{persona} {session} confidential task']
    assert reopened.retrieve('finance_dynamic', user, kind='short_term', session_id='new') == []
    assert reopened.retrieve('finance_react', user) == []

@pytest.mark.parametrize('owner,reader', list(itertools.permutations(PERSONAS, 2)))
def test_no_cross_persona_retrieval_or_deletion(persona_database, owner, reader):
    service = MemoryService(SQLiteMemoryRepository(persona_database))
    owner_user, reader_user = 'workshop_' + owner, 'workshop_' + reader
    assert service.retrieve('finance_dynamic', reader_user, query=owner) == []
    assert service.retrieve('finance_dynamic', reader_user, query=owner,
                            kind='short_term', session_id='first') == []
    service.forget('finance_dynamic', reader_user, 'preference')
    assert service.retrieve('finance_dynamic', owner_user)[0]['metadata']['persona'] == owner


def test_chat_has_explicit_persona_partition_and_demo_disclosure():
    from pathlib import Path
    page = (Path(__file__).resolve().parents[1] / 'web/chat.html').read_text()
    for persona in PERSONAS:
        assert f'value="{persona}"' in page
    assert 'workshop:${app}:${persona}' in page
    assert "user='workshop_'+persona" in page
    assert "$('persona').disabled=true" in page
    assert 'version!==viewVersion' in page
    assert 'not enterprise authentication' in page
    assert 'execution logs, not model knowledge' in page
    assert 'id="prompt-library"' in page
    assert 'value="finance_registry"' in page
    for kind in ('working', 'profile', 'knowledge', 'episodic', 'operational'):
        assert f'value="{kind}"' in page
    assert "['short_term','working'].includes(kind)" in page

@pytest.mark.parametrize('persona', PERSONAS)
@pytest.mark.parametrize('kind', ('working', 'profile', 'knowledge', 'episodic', 'operational'))
def test_every_native_memory_type_persists_and_isolates_personas(tmp_path, persona, kind):
    path = tmp_path / 'native-memory.sqlite3'
    service = MemoryService(SQLiteMemoryRepository(path))
    scoped = kind == 'working'
    for other in PERSONAS:
        service.store('finance_registry', 'workshop_' + other, MemoryWrite(
            key='same_key', text=f'{other} {kind} memory', kind=kind,
            session_id='task-one' if scoped else ''))
    service = MemoryService(SQLiteMemoryRepository(path))
    items = service.retrieve('finance_registry', 'workshop_' + persona, kind=kind,
                             session_id='task-one' if scoped else '')
    assert [item['text'] for item in items] == [f'{persona} {kind} memory']
    if scoped:
        assert service.retrieve('finance_registry', 'workshop_' + persona,
                                kind=kind, session_id='task-two') == []
    else:
        assert items[0]['session_id'] == ''
    assert service.retrieve('different_app', 'workshop_' + persona, kind=kind,
                            session_id='task-one' if scoped else '') == []
