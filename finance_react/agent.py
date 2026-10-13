"""Explicit bounded ReAct loop: decision -> allowlisted action -> observation."""
import json
from typing import Literal
from pydantic import BaseModel, Field
from google.adk.agents import BaseAgent, LlmAgent
from google.adk.events import Event, EventActions
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from dynamic_router.agent import build_model, MODEL_NAME
from finance_common.runtime import load_finance_skill, delegate_finance, create_goal_agent
from finance_common.policies import compose_policy, classify_intent, PROFILES
from memory_layer.tools import store_custom_memory, retrieve_custom_memory, delete_custom_memory
from finance_common.skills import search_finance_skills
from finance_common.calculations import get_finance_case, analyze_finance_case


class Decision(BaseModel):
    action: Literal['search', 'load', 'case', 'calculate', 'route', 'finish', 'memory_store', 'memory_search', 'memory_delete']
    decision_summary: str = Field(max_length=500)
    query: str = ''
    skill_id: str = ''
    scenario: Literal['base', 'downside'] = 'base'
    agent_name: str = ''
    objective: str = ''
    skill_ids: list[str] = []
    answer: str = ''
    memory_key: str = ''
    memory_text: str = ''
    memory_kind: Literal['short_term','long_term','episodic','semantic','procedural','working','profile','knowledge','operational'] = 'long_term'


def planner_instruction(context):
    return compose_policy(context.state.get('finance_policy_profile', 'synthetic_analysis')) + '''\nYou are the decision node in an explicit ReAct financial routing loop.
Return ONE JSON Decision, never an unbounded plan or private chain of thought.
The approved profile takes precedence over the synthetic example sequence below. For task_design,
produce workflows without calculating. For real_world_review, use only references and report evidence
gaps; do not fetch the fictional case or calculate. Route with an empty skill_ids list to discover
skills automatically from the specialist objective.
Memory actions: memory_search(query, memory_kind), memory_store(memory_key, memory_text, memory_kind),
memory_delete(memory_key, memory_kind). Save/delete only on explicit user request.
Allowed actions: case (get inputs), search (query skill descriptions), load (skill_id), calculate
(base/downside), route (agent_name, objective, skill_ids), finish (answer).
Observe results before choosing the next action. Discover skills before routing. Route to at least
two specialists with complementary skills and use at least one numerical tool result before finish.
For underwriting, calculate both scenarios. On failure revise the next action; do not fabricate success.
You have 12 action steps. Prefer case, search with several finance concepts, base calculate,
downside calculate, route valuation specialist, route risk/memo specialist, finish. Specialist routing
loads its selected skills automatically. At finish, summarize evidence, breached gates, gaps, and
limitations. decision_summary is a short explanation of the action, not hidden reasoning.
''' + '\nCURRENT GOAL:\n' + context.state.get('react_goal', '') + '\nOBSERVATIONS:\n' + json.dumps(context.state.get('react_observations', []), ensure_ascii=False)


class FinanceReActAgent(BaseAgent):
    max_steps: int = 12

    async def _run_async_impl(self, ctx):
        goal = '\n'.join(p.text for p in (ctx.user_content.parts or []) if p.text) if ctx.user_content else ''
        tool_context = ToolContext(ctx)
        tool_context.state['finance_policy_profile'] = classify_intent(goal)
        tool_context.state['react_goal'] = goal
        tool_context.state['react_observations'] = []
        tool_context.state['react_status'] = 'active'
        yield Event(author=self.name, actions=tool_context.actions)
        for step in range(1, self.max_steps + 1):
            # Clear previous decision so a failed model step cannot reuse stale state.
            ctx.session.state.pop('react_decision', None)
            async for event in self.sub_agents[0].run_async(ctx):
                yield event
            raw = ctx.session.state.get('react_decision')
            if not raw:
                yield Event(author=self.name, content=types.Content(role='model', parts=[types.Part(text='Planner did not return a decision; execution stopped.')]))
                return
            try:
                decision = Decision.model_validate_json(raw) if isinstance(raw, str) else Decision.model_validate(raw)
            except ValueError:
                yield Event(author=self.name, content=types.Content(role='model', parts=[types.Part(text='Invalid planner decision; execution stopped.')]))
                return
            tool_context = ToolContext(ctx)
            if decision.action == 'finish':
                observed = ctx.session.state.get('react_observations', [])
                routes = [o for o in observed if o['action'] == 'route' and 'error' not in o['observation']]
                calculations = [o for o in observed if o['action'] == 'calculate' and 'error' not in o['observation']]
                if len({o['observation']['agent'] for o in routes}) >= 2 and (calculations or tool_context.state.get('finance_policy_profile') != 'synthetic_analysis') and decision.answer.strip():
                    tool_context.state['react_status'] = 'complete'
                    yield Event(author=self.name, actions=tool_context.actions,
                                content=types.Content(role='model', parts=[types.Part(text=decision.answer)]))
                    return
                observation = {'error': 'Finish needs two distinct successful specialist routes, a numerical observation, and a nonempty answer.'}
            else:
                observation = await execute_decision(decision, tool_context)
            trace = list(ctx.session.state.get('react_observations', []))
            trace.append({'step': step, 'action': decision.action, 'decision_summary': decision.decision_summary, 'observation': observation})
            tool_context.state['react_observations'] = trace
            yield Event(author=self.name, actions=tool_context.actions,
                        content=types.Content(role='model', parts=[types.Part(text=f'Step {step}: {decision.action} — {decision.decision_summary}\nObservation: ' + json.dumps(observation, ensure_ascii=False))]))
        tool_context = ToolContext(ctx)
        tool_context.state['react_status'] = 'step_limit'
        yield Event(author=self.name, actions=tool_context.actions,
                    content=types.Content(role='model', parts=[types.Part(text='ReAct reached its 12-step limit. Partial observations are saved; the goal is not complete.')]))


async def execute_decision(decision: Decision, tool_context) -> dict:
    if decision.action == 'memory_search':
        return await retrieve_custom_memory(decision.query, tool_context, decision.memory_kind)
    if decision.action == 'memory_store':
        return await store_custom_memory(decision.memory_key, decision.memory_text, tool_context, decision.memory_kind)
    if decision.action == 'memory_delete':
        return await delete_custom_memory(decision.memory_key, tool_context, decision.memory_kind)
    profile = tool_context.state.get('finance_policy_profile', 'synthetic_analysis')
    required = {'case': 'get_finance_case', 'calculate': 'analyze_finance_case'}
    if decision.action in required and required[decision.action] not in PROFILES[profile][0]:
        return {'error': f'Action {decision.action} is unavailable under {profile}'}
    if decision.action == 'case':
        return get_finance_case()
    if decision.action == 'search':
        return search_finance_skills(decision.query, 20)
    if decision.action == 'load':
        return load_finance_skill(decision.skill_id, tool_context)
    if decision.action == 'calculate':
        return analyze_finance_case(decision.scenario)
    if decision.action == 'route':
        if not decision.skill_ids:
            return await create_goal_agent(decision.agent_name, decision.objective, tool_context)
        return await delegate_finance(decision.agent_name, decision.objective, decision.skill_ids, tool_context)
    return {'error': 'Unsupported action'}


planner = LlmAgent(name='finance_react_planner', model=build_model(MODEL_NAME),
                   instruction=planner_instruction, include_contents='none',
                   output_schema=Decision, output_key='react_decision')
root_agent = FinanceReActAgent(name='finance_react', description='Bounded explicit ReAct routing with observed tool results.', sub_agents=[planner])
