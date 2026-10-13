from google.adk.agents import LlmAgent
from dynamic_router.agent import build_model, MODEL_NAME
from finance_common.runtime import FINANCE_TOOLS
from finance_common.policies import root_instruction, policy_guard, initialize_policy

root_agent = LlmAgent(
    name='finance_dynamic', model=build_model(MODEL_NAME),
    description='Dynamic routing to finance specialists with implicitly discovered skills.',
    instruction=root_instruction('''\nInfer task requirements, get the synthetic case, and discover relevant
skills by searching their descriptions. Use create_goal_agent(agent_name, goal) to discover skills and create agents automatically from goals. Use delegate_finance when exact skills are already known. Create missing specialists
implicitly by selecting new role names and complementary skill_ids from the catalog. For a complex
acquisition assessment, use at least three specialist roles and four distinct downloaded skills.
Separate valuation, debt/returns risk, and diligence/memo roles. Pass actual observations and
prior outputs into downstream objectives; do not just repeat the original prompt at every stage.
Use analyze_finance_case for numerical evidence and both scenarios when stress is requested.
Delegate only to the skills needed for each role. Load instructions as needed. Synthesize a final
memo with numerical evidence, breached gates, missing evidence, skill provenance, and limitations.
Keep results compact and do not ask for approval in this synthetic local demonstration.
'''),
    before_agent_callback=initialize_policy,
    before_tool_callback=policy_guard,
    tools=FINANCE_TOOLS,
)
