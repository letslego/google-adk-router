# Prompt library

Open `/chat`, choose a library entry, click **Load prompt**, then send it. The loader selects its app
and demo persona. Follow each scenario's steps in order. Steps marked `new_session` start a fresh chat;
creation and reuse steps intentionally keep the same session.

Scenarios in `library.json`:

- `create_and_reuse`: create a DCF Plan/ReAct agent, then route to the same registered agent.
- `parallel_analysis`: valuation and credit run independently; synthesis consumes both outputs.
- `real_world_policy`: real-borrower review gets references and evidence gaps, without synthetic numerical tools.
- `semantic_preference`: write/read a native **profile** preference across sessions (legacy scenario ID retained).
- `working_context`: write/read active context, then verify isolation in a new session.
- `episodic_review`: persist and recall a synthetic past event.
- `procedural_workflow`: write/read native **knowledge** containing a reusable workflow (legacy ID retained).
- `operational_audit`: verify that a memory tool execution produces an operational record.

Run from the repository root with both services running:

```sh
.venv/bin/python -m scripts.run_prompt_library --list
.venv/bin/python -m scripts.run_prompt_library --scenario create_and_reuse
.venv/bin/python -m scripts.run_prompt_library --scenario semantic_preference --scenario working_context
.venv/bin/python -m scripts.run_prompt_library
```

The runner checks ADK session state, route decisions, dependency batches, actual memory API records,
and observed tool calls. It reports failures instead of treating narrative claims as proof. Each run
uses isolated persona-specific user IDs; reports are saved under ignored `outputs/prompt_library/`.
Running these scenarios makes model API calls using the configured provider. A provider refusal,
timeout or invalid plan can fail a scenario; routing correctness does not guarantee task completion.
