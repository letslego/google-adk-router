"""Goal tracking and bounded dynamic routing over downloaded finance skills."""
import json
from functools import lru_cache
import re
import uuid
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, ValidationError
from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.tool_context import ToolContext
from dynamic_router.agent import build_model, MODEL_NAME
from . import skills
from memory_layer.tools import MEMORY_TOOLS
from .calculations import get_finance_case, analyze_finance_case

ROOT = Path(__file__).resolve().parents[1]
from .policies import AgentSpec, PROFILES, compose_policy, classify_intent
POLICY = compose_policy('synthetic_analysis')


@lru_cache(maxsize=1)
def capability_registry():
    from capability_registry import get_registry
    from dynamic_router.tools import TOOLS
    bindings = {**TOOLS, **{fn.__name__: fn for fn in [get_finance_case, analyze_finance_case,
        skills.search_finance_skills, load_finance_skill, skills.read_finance_resource, *MEMORY_TOOLS]}}
    registry = get_registry(approved_tools=bindings)
    registry.bootstrap()
    return registry


def registry_scope(tool_context):
    from capability_registry import Scope
    session = getattr(tool_context, 'session', None)
    if session is None:
        return None  # Unit-test contexts have no durable identity.
    return Scope(session.app_name, tool_context.user_id, session.id)


def search_registered_skills(query: str, limit: int = 12) -> dict:
    """Discover verified skills from the durable write-through registry."""
    records = capability_registry().search('skill', query, limit=limit)
    return {'results': [{'id': row['id'], 'description': row['description'],
                        'source': row['url'], 'license': row['license']} for row in records]}


class TaskStage(BaseModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    objective: str = Field(min_length=10, max_length=3000)
    agent_name: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    skill_ids: list[str] = Field(min_length=1, max_length=5)
    depends_on: list[str]
    deliverable: str = Field(min_length=10)
    acceptance_checks: list[str] = Field(min_length=1)


class FinanceTask(BaseModel):
    title: str
    goal: str = Field(min_length=30)
    case_id: Literal['synthetic_northstar_acquisition']
    synthetic: Literal[True]
    stages: list[TaskStage] = Field(min_length=4, max_length=8)
    completion_gates: list[str] = Field(min_length=4)
    missing_evidence: list[str] = Field(min_length=1)
    runtime_limitations: list[str] = Field(min_length=1)


def start_finance_goal(goal: str, tool_context: ToolContext) -> dict:
    """Set a session goal to design a complex multi-skill task for the synthetic case."""
    if len(goal.strip()) < 30 or len(goal) > 5000:
        return {'error': 'Goal must be 30-5000 characters'}
    current = tool_context.state.get('finance_goal', {})
    if current.get('status') == 'active':
        return {'error': 'A goal is already active; finish it first', 'goal': current}
    record = {'id': uuid.uuid4().hex, 'objective': goal, 'status': 'active',
              'completion': 'A validated task with >=4 downloaded skills, >=4 stages, dependencies, acceptance checks, gaps, and completion gates.'}
    tool_context.state['finance_goal'] = record
    tool_context.state['finance_loaded_skills'] = []
    return record


def load_finance_skill(skill_id: str, tool_context: ToolContext) -> dict:
    """Load selected skill instructions and record the observed skill in session state."""
    result = skills.load_finance_skill(skill_id)
    if 'error' not in result:
        loaded = list(tool_context.state.get('finance_loaded_skills', []))
        if skill_id not in loaded:
            loaded.append(skill_id)
        tool_context.state['finance_loaded_skills'] = loaded
    return result


def validate_task(task: FinanceTask, loaded: list[str]) -> None:
    ids = [s.id for s in task.stages]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate task stage IDs')
    seen, selected = set(), set()
    for stage in task.stages:
        if not set(stage.depends_on) <= seen:
            raise ValueError('Stages must be topologically ordered; no cycles or forward references')
        seen.add(stage.id)
        for sid in stage.skill_ids:
            if sid not in skills.inventory():
                raise ValueError('Task references an unknown skill')
            if sid not in loaded:
                raise ValueError('Every selected skill must be loaded before finalization')
            selected.add(sid)
    if len(selected) < 4:
        raise ValueError('Task must use at least four distinct downloaded skills')


def finalize_finance_task(task_json: str, tool_context: ToolContext) -> dict:
    """Validate, save, and complete the goal only with a multi-skill task and evidence."""
    goal = tool_context.state.get('finance_goal')
    if not goal or goal.get('status') != 'active':
        return {'error': 'Start a finance goal first'}
    try:
        task = FinanceTask.model_validate_json(task_json)
        validate_task(task, tool_context.state.get('finance_loaded_skills', []))
    except (ValidationError, ValueError) as exc:
        return {'error': str(exc), 'expected_schema': FinanceTask.model_json_schema()}
    selected = sorted({sid for stage in task.stages for sid in stage.skill_ids})
    record = {'goal': {**goal, 'status': 'complete'}, 'task': task.model_dump(),
              'skills': [{'id': sid, 'source': skills.inventory()[sid]['url'],
                          'license': skills.inventory()[sid]['license']} for sid in selected]}
    path = ROOT / 'outputs/finance_tasks' / (goal['id'] + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2))
    tool_context.state['finance_goal'] = record['goal']
    tool_context.state['finance_task'] = task.model_dump()
    return {'status': 'complete', 'artifact': str(path), 'task': task.model_dump(), 'skills': record['skills']}


async def delegate_finance(agent_name: str, objective: str, skill_ids: list[str], tool_context: ToolContext) -> dict:
    """Route to a finance agent; create the missing role with selected allowed skills.

    Existing roles are reused. Request skill_ids must match the existing role's
    skills; choose a new role name to create a differently equipped specialist.
    """
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', agent_name) or agent_name in {'finance_dynamic', 'finance_react', 'finance_goal'}:
        return {'error': 'Invalid or reserved agent name'}
    if not objective.strip() or len(objective) > 10000:
        return {'error': 'Objective must be 1-10000 characters'}
    if not 1 <= len(set(skill_ids)) <= 5 or any(sid not in skills.inventory() for sid in skill_ids):
        return {'error': 'Select 1-5 known source-qualified skill IDs'}
    count = tool_context.state.get('temp:finance_calls', 0)
    if count >= 12:
        return {'error': 'Finance delegation budget exhausted'}
    agents = dict(tool_context.state.get('finance_agents', {}))
    scope = registry_scope(tool_context)
    registry = capability_registry()
    saved = registry.get('agent', agent_name, scope) if scope else None
    if saved and 'skill_ids' in saved and agent_name not in agents:
        agents[agent_name] = {'name': agent_name, 'skill_ids': saved['skill_ids'], 'initial_objective': saved['goal'], 'spec': saved}
    created = agent_name not in agents
    if created:
        if len(agents) >= 8:
            return {'error': 'Maximum eight finance specialists per session'}
        agents[agent_name] = {'name': agent_name, 'skill_ids': sorted(set(skill_ids)), 'initial_objective': objective}
    elif set(agents[agent_name]['skill_ids']) != set(skill_ids):
        return {'error': 'Existing role has different skills; use a new role name'}
    # The current request governs every invocation, including reuse of an existing role.
    parent_profile = tool_context.state.get('finance_policy_profile', 'synthetic_analysis')
    local_profile = classify_intent(objective)
    profile = max((parent_profile, local_profile), key=lambda p: {'synthetic_analysis': 0, 'task_design': 1, 'real_world_review': 2}[p])
    tool_registry = {f.__name__: f for f in [get_finance_case, analyze_finance_case,
                     skills.search_finance_skills, load_finance_skill, skills.read_finance_resource]}
    spec = AgentSpec(name=agent_name, goal=objective, skill_ids=sorted(set(skill_ids)),
                     policy_profile=profile, tool_names=sorted(PROFILES[profile][0]),
                     completion_checks=['Address the goal using selected skills',
                                        'Cite observed evidence and distinguish missing evidence',
                                        'Respect the approved policy and runtime limitations'])
    if scope:
        registry.register('agent', agent_name, spec.model_dump(), scope)
    agents[agent_name]['spec'] = spec.model_dump()
    tool_context.state['finance_agents'] = agents
    tool_context.state['temp:finance_calls'] = count + 1
    docs = [load_finance_skill(sid, tool_context) for sid in agents[agent_name]['skill_ids']]
    instruction = compose_policy(profile) + '\nReport only skills actually supplied or loaded through tools; do not invent skill provenance.\nCURRENT GOAL: ' + objective + '\nCOMPLETION CHECKS: ' + json.dumps(spec.completion_checks)
    for doc in docs:
        instruction += '\nREFERENCE SKILL ' + doc['id'] + ':\n' + doc['instructions']
    child = LlmAgent(name=agent_name, model=build_model(MODEL_NAME),
                     description='Financial specialist: ' + objective[:200],
                     instruction=lambda context: instruction,
                     tools=registry.bind_tools(spec.tool_names, PROFILES[profile][0]))
    output = await AgentTool(agent=child,include_plugins=True).run_async(args={'request': objective}, tool_context=tool_context)
    result = {'agent': agent_name, 'created': created, 'spec': spec.model_dump(), 'skills': agents[agent_name]['skill_ids'], 'output': output}
    observations = list(tool_context.state.get('finance_observations', []))
    observations.append(result)
    tool_context.state['finance_observations'] = observations[-12:]
    return result


async def create_goal_agent(agent_name: str, goal: str, tool_context: ToolContext) -> dict:
    """Discover relevant catalog skills from a goal, create/reuse a bounded specialist, and run it.

    No caller-supplied policy or executable tool names are accepted. Use a fresh role name
    when the goal requires different skills from an existing role.
    """
    if not goal.strip() or len(goal) > 10000:
        return {'error': 'Goal must be 1-10000 characters'}
    concepts = [
        (r'due diligence|diligence', 'due diligence checklist'),
        (r'borrower|credit|debt|underwrit', 'credit analysis underwriting'),
        (r'borrower|kyc|customer|sanction', 'know your customer KYC'),
        (r'discounted cash|dcf|valuation', 'dcf valuation'),
        (r'leveraged|lbo|sponsor return', 'lbo modeling returns'),
        (r'treasury|liquidity', 'treasury liquidity'),
        (r'committee|memo', 'investment committee memo'),
    ]
    queries = [query for pattern, query in concepts if re.search(pattern, goal.lower())][:3]
    matches = []
    for query in queries:
        found = search_registered_skills(query, 1)['results']
        if found and found[0]['id'] not in {item['id'] for item in matches}:
            matches.append(found[0])
    if not matches:
        matches = search_registered_skills(goal, 3)['results']
    if not matches:
        return {'error': 'No matching skills; clarify the goal with financial concepts'}
    return await delegate_finance(agent_name, goal, [item['id'] for item in matches], tool_context)


FINANCE_TOOLS = [skills.search_finance_skills, load_finance_skill, skills.read_finance_resource,
                 get_finance_case, analyze_finance_case, delegate_finance, create_goal_agent, *MEMORY_TOOLS]
