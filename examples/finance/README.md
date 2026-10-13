# Financial-services routing examples

Start from the project root with `./scripts/start.sh`, then open http://127.0.0.1:8000.
All examples use the configured Claude model, the downloaded skill catalog, and fictional inputs.

## 1. Create the multi-skill task first

Select `finance_goal` and ask:

> Create a complex acquisition-underwriting task for the synthetic Northstar case using multiple available skills. Include valuation, downside debt stress, leveraged returns, diligence, and an investment-committee memo. Save it with dependencies, acceptance checks, missing evidence, and completion gates.

The agent starts a session goal, searches skill descriptions, loads full instructions, and calls
`finalize_finance_task`. The goal is complete only after code validates 4–8 ordered stages,
at least four distinct loaded skill IDs, acceptance checks, and completion gates. The saved JSON
includes source URLs and licenses. Completion means the task design was created; it does not mean
an acquisition analysis, regulatory screening, or investment decision was completed.

Run from the terminal:

```sh
.venv/bin/python scripts/run_finance_example.py goal
```

The runner saves the generated task at `examples/finance/generated-task.json` and reuses it in
subsequent routing examples. Original goal artifacts remain in `outputs/finance_tasks/`.

## 2. Dynamic routing

Select `finance_dynamic` and ask:

> Assess Northstar's proposed acquisition. Discover the right skills and create specialists for valuation, credit and leveraged returns, and diligence and committee synthesis. Include base and downside evidence, breached gates, and missing evidence.

The model discovers skill descriptions and chooses specialist names, skills, and ordering.
`delegate_finance` creates a missing agent at call time with only the selected skills and approved
local tools. It reuses an existing role with the same skill set. Each downstream objective can
include prior findings. This differs from a predefined graph: there is no fixed specialist list or
fixed route, though creation and call budgets are enforced in code.

```sh
.venv/bin/python scripts/run_finance_example.py dynamic
```

## 3. ReAct agent routing

Select `finance_react` and ask:

> Use your ReAct loop to assess Northstar: inspect inputs, discover skills, observe base and downside calculations, route to complementary specialists, and synthesize an evidence-backed memo.

A code-controlled loop asks a tool-free planner for one structured decision, executes one
allowlisted action, records the observation, and returns it to the next planning step.
Actions are `case`, `search`, `load`, `calculate`, `route`, and `finish`.
The session state shows `react_observations`, each with its step, action, short decision summary,
and real observation. The system exposes action summaries, not private chain of thought.
It stops after 12 steps and will not mark itself complete unless it has two distinct successful
specialist routes and numerical evidence. The live runner additionally verifies both scenarios.

```sh
.venv/bin/python scripts/run_finance_example.py react
```

## Download scope and provenance

199 source-qualified canonical skills were downloaded at pinned commits:

- `anthropics/financial-services`: 60 skills, Apache-2.0. Vertical and partner collections included;
  duplicate agent-plugin copies and the Microsoft 365 deployment-verification skill omitted.
- `JoelLewis/finance_skills`: 91 skills, MIT.
- `rkalathy/Skills-For-AI-Agent-in-Finance`: 48 skills, MIT.

This is all canonical skills in these three collections, not a claim to every finance skill on the
internet. The complete source and checksum inventory is `vendor/skills-manifest.json`.
Original directories include their resources and scripts. Licenses are retained in `vendor/licenses/`
and original skill-level notices are preserved. Downloaded scripts are not executed by these apps.
Vendor sources are source-qualified (for example `anthropics--dcf-model`) so similarly named skills
from different authors can coexist. Search uses lexical overlap over descriptions, with model-created
queries and synonyms; this implementation does not use an embedding store.

`load_finance_skill` reveals selected instructions. `read_finance_resource` permits bounded text
reads inside that skill's directory. Only our local synthetic-case and calculation tools execute.
Full Excel models, paid market data, MCP tools, filings retrieval, sanctions checks, and production
compliance systems described in downloaded skills need separate integrations. Each example must
report these gaps rather than claim they ran.

To reproduce downloads using the same pinned source inventories:

```sh
.venv/bin/python scripts/download_finance_skills.py
```

The downloader currently uses the installed Codex skill-installer helper under `~/.codex/skills/.system/skill-installer/`. Override its location with
`FINANCE_SKILL_INSTALLER` if needed. Skill files are checksum-verified at runtime; restart after intentionally rebuilding the manifest.

## Synthetic data and calculations

`case.json` is fictional and labels currency and units. `get_finance_case` supplies historical data,
base/downside assumptions, transaction terms, thresholds, and explicitly missing evidence.
`analyze_finance_case` returns deterministic five-year DCF, leverage and simplified DSCR stress,
debt repayment schedules, illustrative sponsor returns, formulas, and limitations.
The DSCR definition is a demonstration convention, not a lender contract. The LBO is intentionally
simplified and flags funding deficits instead of silently refinancing. None of this is a real lending,
investment, KYC, or regulatory approval.

The offline tests verify provenance, resource boundaries, model reconciliation, goal completion gates,
and creation/reuse limits. Live runs use provider credits and are recorded in `outputs/finance_runs/`.

## Verified runs

On October 8, 2026, Claude Sonnet 5.5 completed all three live examples. The goal designer saved seven task stages using eight skills; dynamic routing created seven specialists; ReAct recorded case → search → base calculation → downside calculation → specialist route → specialist route, then reached its completion gate. Run IDs and artifacts are listed in `verified-runs.json`. These runs demonstrate orchestration and synthetic calculations; they do not establish production financial accuracy or completion of external checks.

26 offline tests pass, including the literal skill-text regression and the ReAct early-finish/step-limit gate.
