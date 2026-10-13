from memory_layer.tools import MEMORY_TOOLS
from google.adk.agents import LlmAgent
from finance_common.policies import root_instruction, policy_guard, initialize_policy
from dynamic_router.agent import build_model, MODEL_NAME
from finance_common.runtime import POLICY, start_finance_goal, finalize_finance_task, load_finance_skill
from finance_common.skills import search_finance_skills, read_finance_resource
from finance_common.calculations import get_finance_case

root_agent = LlmAgent(
    name='finance_goal', model=build_model(MODEL_NAME),
    description='Goal-driven designer of a complex finance task using downloaded skills.',
    instruction=root_instruction('''\nYour goal is to CREATE a complex, executable analytical task for the
fictional Northstar acquisition case, not approve an investment or finish the analysis.
Get the case and call start_finance_goal with the user's objective or the case goal.
Search the skill catalog by concepts. Select and LOAD at least four complementary downloaded
skills before authoring the task: include valuation, debt stress, due diligence, returns, and memo.
Include 4-8 topologically ordered stages. Each stage needs id, objective, agent_name, skill_ids,
depends_on, deliverable, acceptance_checks. Require numerical evidence from analyze_finance_case
and reference the base/downside scenarios and supplied risk facts. Define at least four completion
gates, missing evidence, and runtime limitations. Case ID is synthetic_northstar_acquisition;
synthetic must be true. Finalize by calling finalize_finance_task with a JSON document containing
title, goal, case_id, synthetic, stages, completion_gates, missing_evidence, runtime_limitations.
If validation fails, repair the JSON and retry. Only claim the goal complete after successful finalization.
Summarize the created task and link its saved artifact. Do not claim external data or Excel outputs.
'''),
    before_agent_callback=initialize_policy,
    before_tool_callback=policy_guard,
    tools=[get_finance_case, start_finance_goal, search_finance_skills, load_finance_skill,
           read_finance_resource, finalize_finance_task, *MEMORY_TOOLS],
)
