from google.adk.agents import LlmAgent
from dynamic_router.agent import build_model, MODEL_NAME
from finance_common.policies import root_instruction, initialize_policy, policy_guard
from memory_layer.tools import MEMORY_TOOLS
from .routing import lookup_capabilities, route_registered_goal, execute_goal_plan

root_agent = LlmAgent(name='finance_registry',model=build_model(MODEL_NAME),
    description='Registry-first goal routing, Plan/ReAct fallback, and parallel dependency plans.',
    instruction=root_instruction('''For substantive tasks first call lookup_capabilities to inspect registered agents, skills and tools.
Choose relevant source-qualified skill IDs from the returned metadata; pass them to route_registered_goal.
Reuse an existing agent only when it covers the requested skills. Otherwise route_registered_goal
creates an ADK PlanReActPlanner loop with approved tools. For complex prompts, identify independent
stages and dependencies: valuation and credit risk can run concurrently, synthesis depends on both.
Use execute_goal_plan with a JSON stages list (id, goal, skill_ids, depends_on) when explicit planning
is more direct. Do not invent external connectors. Explain registry reuse, new agents, parallel batches,
missing tools, and evidence in the final response. Memory-only requests use memory tools directly.'''),
    before_agent_callback=initialize_policy,before_tool_callback=policy_guard,
    tools=[lookup_capabilities,route_registered_goal,execute_goal_plan,*MEMORY_TOOLS])
