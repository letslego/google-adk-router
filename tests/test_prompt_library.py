import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from google.genai import types
import asyncio
from memory_layer.plugin import PersistentMemoryPlugin
from memory_layer.service import MemoryService,MemoryWrite,SQLiteMemoryRepository

ROOT=Path(__file__).resolve().parents[1]

def test_prompt_library_scenarios_have_runnable_checks():
    library=json.loads((ROOT/'examples/prompts/library.json').read_text())
    ids=[s['id'] for s in library['scenarios']]
    assert len(set(ids))==len(ids)==8
    kinds=set()
    for scenario in library['scenarios']:
        assert scenario['app']=='finance_registry' and scenario['steps']
        for step in scenario['steps']:
            assert len(step['prompt'])>30 and step['checks']
            kinds|={c['kind'] for c in step['checks'] if c.get('kind')}
    assert {'working','profile','knowledge','episodic'} <= kinds
    assert any(c['type']=='operational_audit' for s in library['scenarios'] for step in s['steps'] for c in step['checks'])


def test_operational_records_are_not_injected_into_model(tmp_path):
    service=MemoryService(SQLiteMemoryRepository(tmp_path/'db'))
    service.store('app','alice',MemoryWrite(key='ops',text='OPERATIONS_ONLY_SENTINEL',kind='operational'))
    service.store('app','alice',MemoryWrite(key='pref',text='USER_PROFILE_SENTINEL'))
    ctx=SimpleNamespace(session=SimpleNamespace(app_name='app',id='one'),user_id='alice')
    instructions=[]
    request=SimpleNamespace(append_instructions=lambda x:instructions.extend(x))
    with patch('memory_layer.plugin.get_memory_service',return_value=service):
        asyncio.run(PersistentMemoryPlugin(name='test').before_model_callback(callback_context=ctx,llm_request=request))
    assert 'USER_PROFILE_SENTINEL' in '\n'.join(instructions)
    assert 'OPERATIONS_ONLY_SENTINEL' not in '\n'.join(instructions)


def test_operational_hook_records_tool_without_arguments(tmp_path):
    service=MemoryService(SQLiteMemoryRepository(tmp_path/'db'))
    ctx=SimpleNamespace(invocation_id='one',function_call_id='call',session=SimpleNamespace(app_name='app'),user_id='alice')
    with patch('memory_layer.plugin.get_memory_service',return_value=service):
        asyncio.run(PersistentMemoryPlugin(name='test').after_tool_callback(tool=SimpleNamespace(name='retrieve_custom_memory'),tool_args={'secret':'NEVER_COPY_THIS'},tool_context=ctx,result={'memories':[]}))
    records=service.retrieve('app','alice',kind='operational')
    assert records[0]['metadata']['tool']=='retrieve_custom_memory'
    assert 'NEVER_COPY_THIS' not in json.dumps(records)
