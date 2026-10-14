# Dynamic Google ADK router

Python starter for intent-driven orchestration with Google ADK. The root model discovers a small capability catalog, chooses tools and skills by meaning, delegates to specialists, or executes a validated graph path. The general catalog uses model selection; the financial prototype also uses local lexical discovery and conservative intent rules.

## Run

Python 3.11+ for ADK; Node 24 with SQLite FTS5 and pnpm 11.25.0 for the selected private MemLayer dependency.

```sh
./scripts/setup.sh
# Configure ANTHROPIC_API_KEY in .env; never commit it.
./scripts/setup_memlayer.sh  # GitHub access to letslego/memlayer required
./scripts/start_memlayer.sh # Terminal 1: SDK bridge on localhost:61002
./scripts/start.sh          # Terminal 2: ADK and chat on localhost:8000
```

Open http://127.0.0.1:8000/chat. The default app is `finance_registry`.
Set `MEMLAYER_NODE` if your Node executable lacks SQLite FTS5 support.

See [architecture and diagrams](docs/architecture.md), [memory write/read scenarios](docs/memory-scenarios.md),
the [runnable prompt library](examples/prompts/README.md), and [validation results](docs/validation.md).

Select `dynamic_router` in the ADK UI. Alternatively run `adk run dynamic_router`.

Examples:

- “Draft a short announcement of our new opening hours and review it for clarity.”
- “Write an article, count its words, and then polish the final draft.”
- “Create a specialist for customer apology emails and draft one for a delayed shipment.”
- “What time is it in UTC?”

## How routing works

`discover_capabilities` reads agent JSON manifests and skill descriptions on each call. The LLM selects relevant capabilities from descriptions, then uses `delegate`, `load_skill`, direct tools, or `run_graph`. This is semantic selection by an LLM, not an embedding index or a guarantee of perfect matching.

`delegate` automatically creates a session-local agent when the requested name is missing, using the model-selected `fallback_template` (default: `writer`). Removed prebuilt roles use their original approved template retained at server startup. Existing dynamic agents are reused, and template allowlists and session/delegation limits still apply. Provider errors propagate; they do not trigger agent creation. A restart reloads the approved template snapshot from disk.

`delegate` constructs an ADK LlmAgent at call time and invokes it through AgentTool. This explicit wrapper permits late-bound agents without modifying a live sub-agent tree. ADK's newer static single-turn sub-agents are another option when the agent set is known ahead of time. Specialists receive only their allowlisted executable tools, plus capability discovery and skill reading. They cannot recursively create or delegate agents.

`create_specialist` creates up to eight session-local roles from approved templates. It specializes instructions while preserving the template's tools and skills. It does not generate or execute Python code, or persist a manifest to disk.

`run_graph` validates a complete model-selected path before execution. The example graph supports `writer → reviewer` and `writer → analyst → reviewer`. Each node receives the original request and all prior outputs. Forbidden edges, unknown nodes, cycles, and paths over eight nodes are rejected. This is a small application-level graph executor built on ADK agents, not ADK's native graph API. Branch selection occurs before executing the path; outcome-driven rerouting can be performed by the router in a subsequent call.

Skills use local `SKILL.md` files with name and description frontmatter. Their descriptions are discovered first and their full instructions loaded only when selected. Template-bound skills are included in specialist instructions. This intentionally small loader supports instruction-only skills; it does not implement the full ADK SkillToolset resource/script lifecycle.

## Extend

Add a JSON file to `dynamic_router/catalog/`:

```json
{
  "name": "planner",
  "description": "Break complex projects into actionable plans",
  "instruction": "Produce a prioritized plan with assumptions and dependencies.",
  "tools": [],
  "skills": []
}
```

It becomes discoverable on the next catalog lookup. Names must be lowercase identifiers. Add skills under `dynamic_router/skills/<name>/SKILL.md` using the existing frontmatter format. Agent and skill files are trusted application configuration.

Register executable Python tools in `dynamic_router/tools.py` and add their names to a specialist manifest. Restart after changing Python code. A discovered tool description alone does not grant executable access. Add approved routes in `catalog/graphs.json`; their start, terminal nodes, and edge lists constrain the selected path. Catalogs are read from package files, so run from this editable source tree when editing them.

## Verification and limits

```sh
python -m pytest -q
```

Tests cover runtime discovery of a newly added agent, graph validation, output chaining, dynamic agent session isolation, and delegation limits. Agent responses are mocked: tests do not call a model provider or evaluate model routing quality. Live model calls require your API key and incur provider usage.

The default model is `anthropic/claude-sonnet-5-5` through ADK LiteLlm. Set `ANTHROPIC_API_KEY` in `.env` using a key from https://platform.claude.com/settings/keys. Both the root router and dynamically created specialists use this configured model. Set `ADK_MODEL` to another Anthropic model with the `anthropic/` prefix, or a Gemini model name with `GOOGLE_API_KEY`, to switch providers.

Claude requests have a 60-second timeout and up to two provider retries. The router permits up to 12 specialist invocations per user invocation; graph budgets are checked before starting. This is a delegation limit, not a token or spending limit. For production, add provider budgets, persistent session services, authentication, tracing, and routing evaluations for your domain. The example tools only inspect text and time; research, filesystem access, MCP, and external actions are not configured.

Official references: [ADK agent tools](https://github.com/google/adk-python/blob/main/src/google/adk/tools/agent_tool.py), [ADK skills](https://google.github.io/adk-docs/skills/), [ADK workflows](https://google.github.io/adk-docs/workflows/).

## Local development commands

- `./scripts/setup.sh`: create the virtual environment, install the project, and run tests.
- `./scripts/start.sh`: validate configuration and start the local UI (loopback only).
- `.venv/bin/python scripts/smoke_test.py`: live test of discovery, automatic agent creation, delegation, and persisted session state.
- `.venv/bin/python scripts/smoke_test.py --graph`: live test of writer → analyst → reviewer.

Smoke tests send example text to the configured provider and use API credits. The server stores sessions and artifacts locally under the agent's `.adk` directory; these files and `.env` are ignored by Git. Start a new UI session for a clean demonstration. Model provider availability, account quota, and billing remain external requirements.

## Verified locally

On October 8, 2026, Claude Sonnet 5.5 completed both live smoke tests: `delegate` created `apology_writer` with `created: true` and returned an email; `run_graph` completed writer → analyst → reviewer with text statistics. The 17 offline routing tests also passed, and `pip check` found no broken dependencies.

## Financial-services examples

The project now includes `finance_goal`, `finance_dynamic`, and `finance_react`. See [the finance example guide](examples/finance/README.md) for the skill inventory, goal-first workflow, synthetic case, and commands. All 199 downloaded skills retain their source licenses and provenance.


### Goal-driven agents and intent policies

The dynamic app exposes `create_goal_agent(agent_name, goal)`: it extracts common financial concepts and searches the local skill
catalog, selecting up to three matching skills, validates a structured `AgentSpec`, creates
an ADK `LlmAgent`, and runs it. `delegate_finance` remains available for explicit skill selection.
Specs and observations are saved in session state under `finance_agents` and `finance_observations`.
Example: “Create a valuation specialist on the fly to assess discounted cash flow and downside risk.”

Application-owned policy profiles are in `finance_common/policies.py`. Conservative local rules
select `task_design`, `synthetic_analysis`, or `real_world_review` from the current user request.
Every profile includes mandatory base policy. Tool callbacks enforce the root allowlist; specialists
receive only permitted tools; the ReAct dispatcher checks permissions before execution. Reuse
rebuilds the spec against the current goal and policy instead of retaining previous permissions.
Task designers cannot calculate; real-world reviewers can only read skill references and report gaps,
with human review required before real decisions. This runtime has no real-world data connectors.

Intent detection and skill matching are local lexical heuristics, not a semantic classifier or an
authorization system. Unrecognized intent stays within the fictional sandbox; all available data and
calculators remain synthetic. Policy permissions come from application configuration, never user text
or downloaded skills. Completion checks in specialist specs guide output; they do not automatically
validate arbitrary financial prose. The task designer and ReAct loop retain their existing completion gates.


### Task-to-agent chat

Run `scripts/start.sh` and open http://127.0.0.1:8000/chat. Describe a task in natural language.
Choose financial dynamic routing, general specialists, or financial ReAct. Created agents and their
skills/policies/tools appear beside the conversation. New chat starts a fresh session; the ADK event
inspector remains available. Credentials stay on the server.


### Persistent MemLayer integration

Default startup uses `MEMORY_BACKEND=memlayer` with the pinned private
[letslego/memlayer](https://github.com/letslego/memlayer) SDK. Its five native layers are working,
profile, knowledge, episodic and operational. Working and profile replace the former short-term and
long-term labels through compatibility aliases. Operational logs remain outside automatic model context.

The Node bridge writes native MemLayer SQLite records and maintains a persistent stable-key snapshot
index. Working snapshots survive process restart even though the upstream `appendTurn` cache itself is
transient. Profile facts support deletion; other native layers currently return an explicit unsupported
retention/deletion error. See the architecture document for transaction and indexing boundaries.

The Python `MemoryRepository` protocol remains replaceable. `MEMORY_BACKEND=sqlite` selects the original
local database adapter; the earlier Scitrera adapter is optional via `MEMORY_BACKEND=memorylayer`.
Existing memory databases are preserved locally. Databases, logs, credentials and run output are ignored
by Git and are not uploaded. Persona selection is a local demo, not enterprise authentication.


### Banker profiles

The chat includes **Senior banker** and **Junior banker**, with separate sessions and memory.
Their role focus and response preferences are defined in `examples/personas/banker-profiles.json`.
Create their persistent profile facts with `.venv/bin/python -m scripts.create_banker_profiles`
after starting the MemLayer bridge. The senior profile favors concise strategic and risk summaries;
the junior profile favors methods, sources, calculations and checklists for senior review. Neither
profile grants extra tool permissions or approval authority.


Explicit “remember” requests now create an episodic event in `before_run_callback`, before model
routing. Profile and knowledge saves remain complementary. The event records the user's statement
as unverified context, scoped to that user/application, with a stable per-invocation key. Callback
retries do not append duplicate native episodes. Ordinary chat, recall questions and nested
model-generated agent goals do not trigger this capture. Common credential patterns are excluded
from this new episodic path; this is not a complete secret-detection system.
