import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from finance_registry.routing import execute_goal_plan, route_registered_goal
from finance_common.runtime import capability_registry
from capability_registry import Scope


def ctx():
    return SimpleNamespace(state={'finance_policy_profile':'synthetic_analysis'},
        session=SimpleNamespace(app_name='finance_registry',id='session'),user_id='persona')


def test_plan_parallelism_and_dependency_join():
    context=ctx();active=0;peak=0
    def isolate(parent):
        return SimpleNamespace(state=copy.deepcopy(parent.state))
    async def fake_delegate(name,goal,ids,local):
        nonlocal active,peak
        if name=='memo':
            assert 'PRIOR OBSERVED OUTPUTS' in goal and 'valuation' in goal and 'risk' in goal
        active+=1;peak=max(peak,active)
        await asyncio.sleep(.01)
        local.state['finance_agents']={**local.state.get('finance_agents',{}),name:{'name':name}}
        active-=1
        return {'agent':name,'output':goal}
    plan={'stages':[{'id':'valuation','goal':'Analyze valuation independently','skill_ids':['anthropics--dcf-model']},
        {'id':'risk','goal':'Analyze credit risk independently','skill_ids':['rkalathy--credit-analysis']},
        {'id':'memo','goal':'Synthesize prior observed evidence','skill_ids':['anthropics--ic-memo'],'depends_on':['valuation','risk']}]}
    with patch('finance_registry.routing.isolated_context',isolate),patch('finance_registry.routing.delegate_finance',fake_delegate):
        result=asyncio.run(execute_goal_plan(json.dumps(plan),context))
    assert result['status']=='complete' and result['batches']==[['valuation','risk'],['memo']]
    assert peak==2 and set(context.state['finance_agents'])=={'valuation','risk','memo'}
    assert context.state['temp:finance_calls']==3


def test_invalid_plan_and_failures_do_not_run_dependents():
    context=ctx()
    with patch('finance_registry.routing.delegate_finance',new_callable=AsyncMock) as run:
        result=asyncio.run(execute_goal_plan(json.dumps({'stages':[{'id':'a','goal':'Cycle stage aaa','depends_on':['b']},{'id':'b','goal':'Cycle stage bbb','depends_on':['a']}]}),context))
        assert 'error' in result;run.assert_not_called()
    def isolate(parent):return SimpleNamespace(state=copy.deepcopy(parent.state))
    with patch('finance_registry.routing.isolated_context',isolate),patch('finance_registry.routing.create_goal_agent',new_callable=AsyncMock,return_value={'error':'Unavailable'}) as run:
        result=asyncio.run(execute_goal_plan(json.dumps({'stages':[{'id':'a','goal':'Analyze valuation'},{'id':'b','goal':'Synthesize findings','depends_on':['a']}]}),context))
        assert result['status']=='partial' and run.await_count==1


def test_registry_reuses_full_coverage_agent_and_creates_fallback(tmp_path,monkeypatch):
    monkeypatch.setenv('CAPABILITY_REGISTRY_DB',str(tmp_path/'registry.db'))
    capability_registry.cache_clear()
    registry=capability_registry();context=ctx()
    registry.register('agent','valuation',{'name':'valuation','goal':'DCF valuation','skill_ids':['anthropics--dcf-model'],'tool_names':['analyze_finance_case']},Scope('finance_registry','persona','session'))
    with patch('finance_registry.routing.delegate_finance',new_callable=AsyncMock,return_value={'agent':'valuation','created':False}) as run:
        result=asyncio.run(route_registered_goal('DCF valuation',['anthropics--dcf-model'],context))
        assert result['route']=='existing_agent';run.assert_awaited_once()
    with patch('finance_registry.routing.AgentTool') as tool:
        tool.return_value.run_async=AsyncMock(return_value='Plan executed')
        result=asyncio.run(route_registered_goal('Assess credit risk',['rkalathy--credit-analysis'],context))
        assert result['route']=='created_plan_react'
        from google.adk.planners import PlanReActPlanner
        assert isinstance(tool.call_args.kwargs['agent'].planner,PlanReActPlanner)
        assert registry.get('agent',result['agent'],Scope('finance_registry','persona','session'))
    capability_registry.cache_clear()


def test_plan_react_agent_is_reused_with_current_policy(tmp_path,monkeypatch):
    monkeypatch.setenv('CAPABILITY_REGISTRY_DB',str(tmp_path/'registry.db'))
    capability_registry.cache_clear()
    context=ctx()
    with patch('finance_registry.routing.AgentTool') as wrapper:
        wrapper.return_value.run_async=AsyncMock(return_value='Evidence')
        first=asyncio.run(route_registered_goal('DCF valuation',['anthropics--dcf-model'],context))
        context.state['finance_policy_profile']='real_world_review'
        second=asyncio.run(route_registered_goal('DCF valuation review workflow',['anthropics--dcf-model'],context))
        assert second['agent']==first['agent'] and second['created'] is False
        assert second['route']=='existing_agent'
        assert 'analyze_finance_case' not in second['spec']['tool_names']
    capability_registry.cache_clear()


def test_isolated_context_preserves_real_adk_cache_shape():
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.agents import LlmAgent
    from google.adk.sessions import Session
    from google.adk.tools import ToolContext
    from finance_registry.routing import isolated_context
    from google.adk.agents.run_config import RunConfig
    session=Session(id='one',app_name='test',user_id='alice',state={'value':['original']})
    from google.adk.sessions import InMemorySessionService
    invocation=InvocationContext(session_service=InMemorySessionService(),invocation_id='run',agent=LlmAgent(name='root'),session=session,run_config=RunConfig())
    invocation.canonical_tools_cache=['a']
    child=isolated_context(ToolContext(invocation))
    child.get_invocation_context().session.state['value'].append('child')
    assert invocation.session.state['value']==['original']
    assert child.get_invocation_context().canonical_tools_cache==['a']
    assert child.get_invocation_context().canonical_tools_cache is not invocation.canonical_tools_cache
