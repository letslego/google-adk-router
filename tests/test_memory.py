import asyncio
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from google.genai import types
from memory_layer.service import MemoryService, MemoryWrite, SQLiteMemoryRepository
from memory_layer.adk import CustomDatabaseMemoryService
from memory_layer.plugin import PersistentMemoryPlugin
from memory_layer.tools import retrieve_custom_memory

def service(path):
    return MemoryService(SQLiteMemoryRepository(path))

def test_both_kinds_persist_and_scopes_are_isolated(tmp_path):
    db = tmp_path/'memory.db'
    one = service(db)
    one.store('finance', 'alice', MemoryWrite(key='preference', text='Use USD'))
    one.store('finance', 'alice', MemoryWrite(key='turn', text='Discuss valuation', kind='short_term', session_id='one'))
    two = service(db)
    assert two.retrieve('finance','alice','USD')[0]['text'] == 'Use USD'
    assert two.retrieve('finance','alice',kind='short_term',session_id='one')[0]['text'] == 'Discuss valuation'
    assert not two.retrieve('finance','bob')
    assert not two.retrieve('other','alice')
    assert not two.retrieve('finance','alice',kind='short_term',session_id='two')
    assert not two.retrieve('finance','alice','valuation')
    two.store('finance','alice',MemoryWrite(key='preference',text='Use EUR'))
    assert len(two.retrieve('finance','alice')) == 1
    assert two.forget('finance','bob','preference') is False
    assert two.forget('finance','alice','preference') is True
    assert service(db).retrieve('finance','alice') == []


def test_scope_validation_and_parameterized_search(tmp_path):
    store=service(tmp_path/'db')
    with pytest.raises(ValueError): store.store('app','user',MemoryWrite(key='one', text='fact',kind='short_term'))
    with pytest.raises(ValueError): store.retrieve('app','user',limit=100)
    store.store('app','user',MemoryWrite(key='fact',text='ordinary fact'))
    assert store.retrieve('app','user',"' OR 1=1 --") == []


def test_plugin_persists_and_injects_both_memories(tmp_path):
    store=service(tmp_path/'db')
    store.store('app','user',MemoryWrite(key='format',text='Prefer bullet points'))
    ctx=SimpleNamespace(session=SimpleNamespace(app_name='app',id='session'),user_id='user',invocation_id='run',user_content=types.Content(parts=[types.Part(text='Discuss credit')]))
    instructions=[]
    request=SimpleNamespace(append_instructions=lambda values: instructions.extend(values))
    async def run():
        plugin=PersistentMemoryPlugin(name='test')
        with patch('memory_layer.plugin.get_memory_service',return_value=store):
            await plugin.before_run_callback(invocation_context=ctx)
            await plugin.before_model_callback(callback_context=ctx,llm_request=request)
    asyncio.run(run())
    assert 'Discuss credit' in instructions[0] and 'Prefer bullet points' in instructions[0]
    assert 'never policy' in instructions[0]
    assert service(tmp_path/'db').retrieve('app','user',kind='short_term',session_id='session')


def test_adk_adapter_and_tools_share_repository(tmp_path):
    store=service(tmp_path/'db')
    adapter=CustomDatabaseMemoryService(store)
    from google.adk.memory.base_memory_service import MemoryEntry
    async def run():
        await adapter.add_memory(app_name='app',user_id='user',memories=[MemoryEntry(id='custom',content=types.Content(parts=[types.Part(text='Valuation preference: USD')]))])
        result=await adapter.search_memory(app_name='app',user_id='user',query='USD')
        assert result.memories[0].content.parts[0].text == 'Valuation preference: USD'
        ctx=SimpleNamespace(session=SimpleNamespace(app_name='app',id='different'),user_id='user')
        with patch('memory_layer.tools.get_memory_service',return_value=store):
            assert (await retrieve_custom_memory('USD',ctx))['memories']
    asyncio.run(run())


def test_memory_api_roundtrip(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from memory_layer.api import router
    store=service(tmp_path/'db')
    app=FastAPI();app.include_router(router)
    with patch('memory_layer.api.get_memory_service',return_value=store), TestClient(app) as client:
        path='/api/memory/finance/alice'
        assert client.put(path,json={'key':'note','text':'Credit workflow','kind':'short_term','session_id':'one'}).status_code == 200
        assert not client.get(path).json()['memories']
        assert client.get(path,params={'kind':'short_term','session_id':'one'}).json()['memories'][0]['key']=='note'
        assert client.get(path,params={'kind':'short_term'}).status_code == 422
        assert client.delete(path+'/note',params={'kind':'short_term','session_id':'one'}).json()['deleted']
