"""Registry-first routing with bounded Plan/ReAct fallback and isolated parallel stages."""
import asyncio
import copy
import json
import re
import uuid
from pydantic import BaseModel, ConfigDict, Field
from google.adk.agents import LlmAgent
from google.adk.planners import PlanReActPlanner
from google.adk.tools import ToolContext
from google.adk.tools.agent_tool import AgentTool
from dynamic_router.agent import build_model, MODEL_NAME
from finance_common.runtime import capability_registry, registry_scope, delegate_finance, create_goal_agent, search_registered_skills
from finance_common.policies import compose_policy, PROFILES, policy_guard
from finance_common import skills
from finance_common.calculations import get_finance_case, analyze_finance_case
from finance_common.runtime import load_finance_skill
from memory_layer.tools import MEMORY_TOOLS

class GoalStage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    goal: str = Field(min_length=10, max_length=9000)
    skill_ids: list[str] = Field(default_factory=list, max_length=5)
    depends_on: list[str] = Field(default_factory=list)

class GoalPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stages: list[GoalStage] = Field(min_length=1, max_length=8)


def lookup_capabilities(query: str, tool_context: ToolContext) -> dict:
    """Look up existing agents, skills and tools before choosing reuse or bounded creation."""
    registry = capability_registry()
    scope = registry_scope(tool_context)
    return {'agents': registry.search('agent',query,scope,limit=8) if scope else [],
            'skills': registry.search('skill',query,limit=15),
            'tools': registry.search('tool',query,limit=10),
            'policy_profile': tool_context.state.get('finance_policy_profile','synthetic_analysis'),
            'selection': 'Reuse only roles with verified skill coverage. Missing tools are gaps, never invented capabilities.'}


def isolated_context(tool_context):
    invocation = tool_context.get_invocation_context()
    session = invocation.session.model_copy(deep=True)
    isolated = invocation.model_copy(update={'session': session, 'branch': uuid.uuid4().hex,
        'canonical_tools_cache': copy.copy(invocation.canonical_tools_cache)})
    return ToolContext(isolated)


async def execute_goal_plan(plan_json: str, tool_context: ToolContext) -> dict:
    """Execute a dependency DAG, running up to three ready stages concurrently in isolated state.

    Only independent stages share a batch. Dependent stages receive prior observed outputs.
    No model-created tools or Python execution are allowed.
    """
    try:
        plan = GoalPlan.model_validate_json(plan_json)
        ids = [s.id for s in plan.stages]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate stage IDs')
        for stage in plan.stages:
            if stage.id in stage.depends_on or not set(stage.depends_on) <= set(ids):
                raise ValueError('Invalid stage dependency')
        seen = set()
        while len(seen) < len(ids):
            ready = {s.id for s in plan.stages if set(s.depends_on) <= seen} - seen
            if not ready:
                raise ValueError('Dependency cycle')
            seen |= ready
        existing = set(tool_context.state.get('finance_agents',{}))
        if len(existing | set(ids)) > 8:
            raise ValueError('Plan exceeds eight specialist roles per session')
        if tool_context.state.get('temp:finance_calls',0) + len(ids) > 12:
            raise ValueError('Delegation budget insufficient for plan')
    except ValueError as exc:
        return {'error':str(exc)}
    completed = {}
    batches = []
    async def run(stage, context):
        goal = stage.goal
        if stage.depends_on:
            goal += '\nPRIOR OBSERVED OUTPUTS:\n' + json.dumps({key:completed[key] for key in stage.depends_on})[:20000]
        if stage.skill_ids:
            return await delegate_finance(stage.id,goal,stage.skill_ids,context)
        return await create_goal_agent(stage.id,goal,context)
    while len(completed) < len(plan.stages):
        ready = [s for s in plan.stages if s.id not in completed and set(s.depends_on) <= completed.keys()][:3]
        baseline = copy.deepcopy(tool_context.state.get('finance_agents',{}))
        contexts = [isolated_context(tool_context) for _ in ready]
        results = await asyncio.gather(*(run(stage,ctx) for stage,ctx in zip(ready,contexts)), return_exceptions=True)
        for stage,ctx,result in zip(ready,contexts,results):
            if isinstance(result,Exception):
                result = {'error':str(result),'stage':stage.id}
            completed[stage.id] = result
            # Merge only known output collections, in plan order, after the batch joins.
            agents = dict(tool_context.state.get('finance_agents',{}))
            agents.update({name: spec for name, spec in ctx.state.get('finance_agents',{}).items()
                           if spec != baseline.get(name)})
            tool_context.state['finance_agents'] = agents
            loaded = set(tool_context.state.get('finance_loaded_skills',[])) | set(ctx.state.get('finance_loaded_skills',[]))
            tool_context.state['finance_loaded_skills'] = sorted(loaded)
            observations = list(tool_context.state.get('finance_observations',[]))
            if 'error' not in result:
                observations.append(result)
            tool_context.state['finance_observations'] = observations[-12:]
        tool_context.state['temp:finance_calls'] = tool_context.state.get('temp:finance_calls',0) + len(ready)
        batches.append([s.id for s in ready])
        if any('error' in completed[s.id] for s in ready):
            return {'status':'partial','batches':batches,'outputs':completed,'error':'A stage failed; dependent stages were not executed'}
    tool_context.state['registry_plan'] = {'status':'complete','batches':batches,'outputs':completed}
    return tool_context.state['registry_plan']


async def route_registered_goal(goal: str, skill_ids: list[str], tool_context: ToolContext) -> dict:
    """Reuse a registry specialist with full requested skill coverage, else create a Plan/ReAct loop agent."""
    if not goal.strip() or len(goal)>10000:
        return {'error':'Goal must be 1-10000 characters'}
    registry=capability_registry();scope=registry_scope(tool_context)
    if any(registry.get('skill',sid) is None for sid in skill_ids):
        return {'error':'Unknown registered skill'}
    matches=registry.search('agent',goal,scope,limit=30) if scope else []
    reusable_plan = None
    for candidate in matches:
        if skill_ids and set(skill_ids) <= set(candidate.get('skill_ids',[])):
            if candidate.get('planner') == 'ADK PlanReActPlanner':
                reusable_plan = candidate
                break
            result=await delegate_finance(candidate['id'],goal,candidate['skill_ids'],tool_context)
            tool_context.state['registry_route']={'route':'existing_agent','agent':candidate['id']}
            return {'route':'existing_agent',**result}
    profile=tool_context.state.get('finance_policy_profile','synthetic_analysis')
    if not reusable_plan and len(tool_context.state.get('finance_agents',{})) >= 8:
        return {'error':'Maximum eight registered session agents'}
    name=reusable_plan['id'] if reusable_plan else 'plan_react_'+uuid.uuid4().hex[:10]
    functions=[search_registered_skills,load_finance_skill,skills.read_finance_resource,
               create_goal_agent,delegate_finance,execute_goal_plan,*MEMORY_TOOLS]
    functions += [fn for fn in (get_finance_case,analyze_finance_case) if fn.__name__ in PROFILES[profile][0]]
    # Registry only stores metadata; these bindings are supplied by trusted code.
    for fn in functions:
        registry.approved_tools[fn.__name__]=fn
        registry.register('tool',fn.__name__,{'name':fn.__name__,'description':fn.__doc__ or ''})
    spec={'name':name,'goal':goal,'skill_ids':skill_ids,'tool_names':[fn.__name__ for fn in functions],
          'policy_profile':profile,'planner':'ADK PlanReActPlanner','max_delegations':12}
    if scope:
        registry.register('agent',name,spec,scope)
    child=LlmAgent(name=name,model=build_model(MODEL_NAME),planner=PlanReActPlanner(),
        instruction=lambda ctx: compose_policy(profile)+'\nPlan from registry capabilities. Use execute_goal_plan for independent work in parallel and dependencies for synthesis. Use only observed outputs. Stay within 12 delegated stages. Missing executable tools are evidence gaps.\nGoal: '+goal,
        before_tool_callback=policy_guard,tools=functions)
    output=await AgentTool(agent=child,include_plugins=True).run_async(args={'request':goal},tool_context=tool_context)
    spec_result={'agent':name,'created':reusable_plan is None,'spec':spec,'skills':skill_ids,'output':output}
    agents=dict(tool_context.state.get('finance_agents',{}));agents[name]=spec
    if scope:
        for entry_name, record in agents.items():
            registry.register('agent', entry_name, record.get('spec',record), scope)
    tool_context.state['finance_agents']=agents
    route='existing_agent' if reusable_plan else 'created_plan_react'
    tool_context.state['registry_route']={'route':route,'agent':name}
    return {'route':route,**spec_result}
