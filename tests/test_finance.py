import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from finance_common import skills
from finance_common.calculations import get_finance_case, analyze_finance_case
from finance_common.runtime import FinanceTask, validate_task, delegate_finance, load_finance_skill, start_finance_goal, finalize_finance_task
from finance_react.agent import Decision, execute_decision


def context():
    return SimpleNamespace(state={})


def task_payload():
    ids = ['anthropics--dcf-model', 'rkalathy--credit-analysis', 'anthropics--dd-checklist', 'anthropics--ic-memo']
    return {'title': 'Synthetic acquisition underwriting', 'goal': get_finance_case()['goal'],
            'case_id': 'synthetic_northstar_acquisition', 'synthetic': True,
            'stages': [{'id': f'stage_{i}', 'objective': 'Analyze the synthetic acquisition case',
                        'agent_name': f'analyst_{i}', 'skill_ids': [sid], 'depends_on': [f'stage_{i-1}'] if i else [],
                        'deliverable': 'Evidence and analytical findings', 'acceptance_checks': ['Source-backed evidence required']}
                       for i, sid in enumerate(ids)],
            'completion_gates': ['source provenance', 'numeric reconciliation', 'risk evidence', 'limitations'],
            'missing_evidence': ['verified statements'], 'runtime_limitations': ['No live data']}


def test_financial_catalog_has_199_provenanced_skills():
    assert len(skills.inventory()) == 199
    assert all(s['license'] in {'MIT', 'Apache-2.0'} and len(s['commit']) == 40 for s in skills.inventory().values())
    assert 'anthropics--dcf-model' in [s['id'] for s in skills.search_finance_skills('DCF model valuation')['results']]


def test_unknown_skill_and_resource_traversal():
    assert 'error' in skills.load_finance_skill('nonexistent')
    assert 'error' in skills.read_finance_resource('anthropics--dcf-model', '../../../../.env')
    assert 'instructions' in skills.load_finance_skill('anthropics--dcf-model')


def test_finance_model_reconciles_cash_and_gates():
    case = get_finance_case()
    assert case['synthetic'] is True
    for scenario in ['base', 'downside']:
        result = analyze_finance_case(scenario)
        prior_debt = case['transaction']['new_debt']
        for row in result['schedule']:
            assert row['ending_debt'] == pytest.approx(prior_debt - row['debt_repayment'])
            assert row['ending_debt'] >= 0
            prior_debt = row['ending_debt']
        assert result['entry_debt_to_ebitda'] == pytest.approx(145 / 24)
        assert result['gates']['leverage_pass'] is False
    assert analyze_finance_case('downside')['dcf_enterprise_value'] < analyze_finance_case('base')['dcf_enterprise_value']
    assert 'error' in analyze_finance_case('unknown')


def test_task_must_load_four_skills_and_avoid_cycles():
    data = task_payload()
    task = FinanceTask.model_validate(data)
    loaded = [s['skill_ids'][0] for s in data['stages']]
    validate_task(task, loaded)
    with pytest.raises(ValueError): validate_task(task, [])
    data['stages'][0]['depends_on'] = ['stage_3']
    with pytest.raises(ValueError): validate_task(FinanceTask.model_validate(data), loaded)


def test_goal_finalize_writes_only_after_validation(tmp_path):
    ctx = context()
    payload = task_payload()
    start_finance_goal(payload['goal'], ctx)
    assert 'error' in finalize_finance_task(json.dumps(payload), ctx)
    assert ctx.state['finance_goal']['status'] == 'active'
    for stage in payload['stages']: load_finance_skill(stage['skill_ids'][0], ctx)
    with patch('finance_common.runtime.ROOT', tmp_path):
        result = finalize_finance_task(json.dumps(payload), ctx)
    assert result['status'] == 'complete'
    assert ctx.state['finance_goal']['status'] == 'complete'
    assert len(list(tmp_path.rglob('*.json'))) == 1


def test_finance_dynamic_creation_reuse_and_equipment():
    ctx = context()
    ids = ['rkalathy--credit-analysis']
    with patch('finance_common.runtime.AgentTool.run_async', new_callable=AsyncMock, return_value='Evidence') as run:
        one = asyncio.run(delegate_finance('credit_analyst', 'Analyze debt capacity', ids, ctx))
        two = asyncio.run(delegate_finance('credit_analyst', 'Analyze downside', ids, ctx))
        assert one['created'] is True and two['created'] is False
        assert run.await_count == 2
        assert 'error' in asyncio.run(delegate_finance('credit_analyst', 'Change role', ['anthropics--dcf-model'], ctx))
        assert 'error' in asyncio.run(delegate_finance('../bad', 'Bad name', ids, ctx))
        ctx.state['temp:finance_calls'] = 12
        assert 'error' in asyncio.run(delegate_finance('new_credit', 'Analyze credit', ids, ctx))
        assert 'new_credit' not in ctx.state['finance_agents']


def test_react_action_dispatch_is_allowlisted():
    with pytest.raises(ValueError): Decision(action='shell', decision_summary='Run shell')
    decision = Decision(action='calculate', scenario='downside', decision_summary='Observe stress metrics')
    result = asyncio.run(execute_decision(decision, context()))
    assert result['scenario'] == 'downside'


def test_react_rejects_early_finish_and_obeys_step_limit():
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    from finance_react.agent import FinanceReActAgent
    from google.adk.agents import LlmAgent

    async def scenario():
        sessions = InMemorySessionService()
        await sessions.create_session(app_name='react_test', user_id='test', session_id='one')
        planner = LlmAgent(name='fake_planner')
        root = FinanceReActAgent(name='test_react', sub_agents=[planner], max_steps=2)
        runner = Runner(app_name='react_test', agent=root, session_service=sessions)
        async def fake_plan(self, ctx):
            ctx.session.state['react_decision'] = Decision(action='finish', decision_summary='Premature completion', answer='Done').model_dump_json()
            if False:
                yield None
        with patch.object(LlmAgent, 'run_async', fake_plan):
            events = [e async for e in runner.run_async(user_id='test', session_id='one', new_message=types.Content(role='user',parts=[types.Part(text='Assess acquisition')]))]
        session = await sessions.get_session(app_name='react_test', user_id='test', session_id='one')
        assert session.state['react_status'] == 'step_limit'
        assert len(session.state['react_observations']) == 2
        assert all('error' in r['observation'] for r in session.state['react_observations'])
        assert events[-1].content.parts[0].text.endswith('the goal is not complete.')
        await runner.close()
    asyncio.run(scenario())


def test_downloaded_skill_placeholders_are_not_session_variables():
    ctx = context()
    with patch('finance_common.runtime.AgentTool') as wrapper:
        wrapper.return_value.run_async = AsyncMock(return_value='Valuation evidence')
        asyncio.run(delegate_finance('valuation', 'Value the synthetic company', ['anthropics--dcf-model'], ctx))
        child = wrapper.call_args.kwargs['agent']
        instruction, bypass = asyncio.run(child.canonical_instruction(None))
        assert bypass is True
        assert '{wacc_value}' in instruction
        assert 'REFERENCE SKILL anthropics--dcf-model' in instruction
