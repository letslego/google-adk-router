# Validation

Verified locally on 2026-10-13 against the pinned `letslego/memlayer` dependency:

- 109 offline Python tests passed, including persona isolation, registry cache consistency,
  real ADK invocation-context copying, policy restrictions and operational-context exclusion.
- All eight prompt-library scenarios passed their observable checks (14 ordered steps).
  The two initially failing context-copy scenarios were rerun after the regression fix.
- Actual MemLayer SDK writes and reads passed for working, profile, knowledge, episodic and
  operational layers. Knowledge-query retrieval and other-user isolation were also checked.
- Seven legacy custom-memory records were copied to the selected backend; the source database
  was left intact. Private runtime records and reports are not committed.
- The initial GitHub offline-test workflow completed successfully.

Run reports live locally under `outputs/prompt_library/`. Reproduce with:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.run_prompt_library
```

These checks verify routing/state/persistence boundaries. They do not certify financial correctness,
production authorization, multi-host durability or provider availability. Live model calls can still
fail or refuse a request. See [architecture](architecture.md) for the bridge's two-store consistency
and upstream deletion limitations.
