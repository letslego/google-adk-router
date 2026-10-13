# When MemLayer is written and read

The active backend is [letslego/memlayer](https://github.com/letslego/memlayer), not the similarly named
Scitrera MemoryLayer service. Its five native layers are exposed in the chat and custom-memory API.
The older Scitrera adapter remains optional; it is not the default startup backend.

## Working: current conversation or task

On incoming prompts, `before_run_callback` saves the user's text. On visible response events,
`on_event_callback` saves agent text. Each write calls the bridge, commits a native journal item,
updates MemLayer's working hot state, and publishes a durable keyed snapshot. Reads happen before
model calls and when the chat restores the current session. A new session cannot read the prior
session's working items. Example: “Remember the active evidence checklist for this conversation.”

## Profile: persistent facts and preferences

An explicit request such as “Remember that I prefer USD and short reports” calls
`store_custom_memory(kind="profile")`, which invokes `setProfileFact`. Later `getProfile` reads the
revision-aware profile. It is available in new sessions for the same user/application. It is not
shared with other personas. The `long_term` and `semantic` names are compatibility aliases.

## Knowledge: reusable documents and workflows

An explicit request to save a review methodology or document uses `kind="knowledge"` and
`ingestDocument`. Documents receive restricted user ACLs. A query invokes `searchKnowledge` with
the current user identity; browsing recent saved items uses the bridge index. The `procedural` alias
maps to this layer; the selected MemLayer project does not have a separate procedural layer.

## Episodic: significant past events

An explicit request to save a synthetic review outcome uses `recordEpisode`. The episode is persistent
and user-scoped, and the bridge can retrieve its current keyed representation in later sessions.
Conversation journaling also creates MemLayer-native exchange episodes, but those are not automatically
promoted to arbitrary verified user facts. Example: “Save that the fictional review requested more
DSCR evidence.”

## Operational: execution records

`after_tool_callback` records the executed tool's name and whether a structured error was returned.
It invokes `recordAudit`, then publishes the snapshot. Operational entries can be inspected through
the memory viewer/API. They are not automatically retrieved into the model prompt. A returned tool
result is an observation, not independent proof of business success. Costs are not estimated by this
prototype's audit hook.

## Retrieval before generation

`before_model_callback` retrieves up to 10 working and 10 profile items, plus five episodic and five
knowledge items. The serialized context has a 14,000-character cap and is marked untrusted. This is
bounded recent-context loading, not an automatic relevance classifier. Explicit memory queries use the
custom retrieval tool; knowledge queries use upstream hybrid retrieval. No operational items are
included by this hook.

## Personas and persistence checks

Analyst, risk reviewer, relationship manager and auditor have separate demo user IDs. Tests cover
native-layer persistence, application/user separation and working-session separation. These personas
do not grant permissions. The prompt runner creates disposable user partitions with unique run IDs,
so demo preferences do not overwrite the interactive user's preferences.

See [the prompt library](../examples/prompts/README.md) for ordered write/read scenarios and runnable
checks. Runtime databases, memory snapshots, logs and run reports are excluded from GitHub.
