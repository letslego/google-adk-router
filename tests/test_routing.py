import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from dynamic_router import catalog
from dynamic_router.agent import create_specialist, delegate, discover_capabilities, run_graph


def ctx():
    return SimpleNamespace(state={})


def test_catalog_and_skills():
    found = discover_capabilities('Improve this article')
    assert {a['name'] for a in found['agents']} == {'writer', 'reviewer', 'analyst'}
    assert catalog.skills()['clear-writing']['body']


def test_hot_discovery(tmp_path, monkeypatch):
    (tmp_path / 'catalog').mkdir()
    (tmp_path / 'skills').mkdir()
    monkeypatch.setattr(catalog, 'BASE', tmp_path)
    assert catalog.agents() == {}
    spec = dict(name='new_agent', description='New role', instruction='Help', tools=[], skills=[])
    (tmp_path / 'catalog' / 'new.json').write_text(json.dumps(spec))
    assert 'new_agent' in catalog.agents()


@pytest.mark.parametrize('path', [[], ['reviewer'], ['writer', 'writer', 'reviewer'], ['writer', 'missing', 'reviewer'], ['writer', 'analyst']])
def test_invalid_graph_paths(path):
    with pytest.raises(ValueError):
        catalog.validate_path(catalog.graphs()['write_review'], path, catalog.agents())


def test_valid_graph_branch():
    catalog.validate_path(catalog.graphs()['write_review'], ['writer', 'analyst', 'reviewer'], catalog.agents())


def test_dynamic_agent_and_isolation():
    first, second = ctx(), ctx()
    assert create_specialist('email_writer', 'writer', 'Write concise emails', first)['name'] == 'email_writer'
    assert 'email_writer' in {a['name'] for a in discover_capabilities('email', first)['agents']}
    assert not second.state
    assert 'error' in create_specialist('email_writer', 'writer', 'x', first)
    assert 'error' in create_specialist('../bad', 'writer', 'x', first)
    assert 'error' in create_specialist('unknown', 'missing', 'x', first)


def test_delegation_and_budget():
    context = ctx()
    with patch('dynamic_router.agent.AgentTool.run_async', new_callable=AsyncMock, return_value='Draft') as call:
        result = asyncio.run(delegate('writer', 'Write an email', context))
        assert result['output'] == 'Draft'
        assert call.call_args.kwargs['args'] == {'request': 'Write an email'}
        context.state['temp:delegations'] = 12
        assert 'error' in asyncio.run(delegate('writer', 'x', context))
        assert call.await_count == 1


def test_graph_output_chaining():
    context = ctx()
    with patch('dynamic_router.agent.AgentTool.run_async', new_callable=AsyncMock, side_effect=['Draft', 'Final']) as call:
        result = asyncio.run(run_graph('write_review', ['writer', 'reviewer'], 'Write email', context))
        assert [r['output'] for r in result['outputs']] == ['Draft', 'Final']
        second = json.loads(call.call_args.kwargs['args']['request'])
        assert second['previous_outputs'][0]['output'] == 'Draft'


def test_graph_rejects_before_execution():
    with patch('dynamic_router.agent.AgentTool.run_async', new_callable=AsyncMock) as call:
        assert 'error' in asyncio.run(run_graph('write_review', ['reviewer'], 'x', ctx()))
        call.assert_not_called()


def test_missing_agent_is_created_and_reused():
    context = ctx()
    with patch('dynamic_router.agent.AgentTool.run_async', new_callable=AsyncMock, return_value='Email'):
        first = asyncio.run(delegate('apology_writer', 'Write an apology', context, 'writer'))
        assert first['created'] is True
        assert context.state['dynamic_agents']['apology_writer']['tools'] == []
        second = asyncio.run(delegate('apology_writer', 'Revise it', context))
        assert second['created'] is False


def test_missing_agent_rejects_unknown_template():
    context = ctx()
    with patch('dynamic_router.agent.AgentTool.run_async', new_callable=AsyncMock) as call:
        assert 'error' in asyncio.run(delegate('new_role', 'x', context, 'unknown'))
        call.assert_not_called()
        assert not context.state


def test_missing_agent_budget_does_not_create():
    context = ctx()
    context.state['temp:delegations'] = 12
    assert 'error' in asyncio.run(delegate('new_role', 'x', context))
    assert 'dynamic_agents' not in context.state


def test_graph_recreates_removed_prebuilt_agent():
    context = ctx()
    remaining = {k: v for k, v in catalog.agents().items() if k != 'reviewer'}
    with patch('dynamic_router.agent.catalog.agents', return_value=remaining), patch('dynamic_router.agent.AgentTool.run_async', new_callable=AsyncMock, side_effect=['Draft', 'Reviewed']):
        result = asyncio.run(run_graph('write_review', ['writer', 'reviewer'], 'Draft email', context))
        assert result['outputs'][1]['created'] is True
        assert context.state['dynamic_agents']['reviewer']['skills'] == ['quality-review']


def test_provider_failure_does_not_create_replacement():
    context = ctx()
    with patch('dynamic_router.agent.AgentTool.run_async', new_callable=AsyncMock, side_effect=RuntimeError('provider unavailable')):
        with pytest.raises(RuntimeError):
            asyncio.run(delegate('writer', 'Draft', context))
        assert 'dynamic_agents' not in context.state
