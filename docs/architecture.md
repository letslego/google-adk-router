# Architecture and execution paths

This repository runs Google ADK Python with Claude, a registry-first router, and the
[letslego/memlayer](https://github.com/letslego/memlayer) TypeScript SDK. The dependency is
pinned in `memlayer-dependency.json`; its private source is cloned locally and not copied into this repo.

```mermaid
flowchart TD
    User[User prompt and demo persona] --> Chat[Chat UI and prompt library]
    Chat --> API[Local FastAPI and ADK Runner]
    API --> Policy[Intent profile and tool guard]
    Policy --> Router[Registry-first router]
    Router --> Cache[Write-through capability cache]
    Cache --> Registry[(SQLite agents / skills / tools)]
    Router -->|skill coverage found| Existing[Rebuild and reuse registered agent]
    Router -->|no suitable agent| Planner[New ADK PlanReActPlanner agent]
    Planner --> DAG[Validated dependency plan]
    DAG --> Parallel[Up to three independent stages]
    Parallel --> Join[Join actual observations]
    Join --> Synthesis[Dependent synthesis stage]
    Existing --> Tools[Approved Python tool bindings]
    Synthesis --> Tools
    API --> Hooks[Persistent memory plugin]
    Hooks --> Bridge[Local Node 24 SDK bridge]
    Bridge --> SDK[letslego/memlayer SDK]
    SDK --> Native[(Native MemLayer SQLite)]
    SDK --> Hot[Working and profile cache]
    Bridge --> Index[(Stable-key snapshot index)]
    Tools --> Hooks
```

## Registry consistency and agent creation

The registry commits metadata to SQLite before publishing cache entries. A durable version counter
invalidates caches in other instances. Agent records are scoped by application, user and session;
verified skill descriptions and approved tool metadata are shared. Stored JSON never contains executable
code. Runtime functions come from a code-side allowlist and are rechecked against the current policy.

The root looks up all three registries. A registered agent with the requested skill coverage is reused,
including a Plan/ReAct agent. Otherwise the router registers a new `LlmAgent` using ADK's
`PlanReActPlanner`. Creation changes the goal, selected skills and permitted tool set; it does not invent
an executable connector. Missing integrations are reported as gaps.

`execute_goal_plan` validates stage IDs and dependencies before execution. Ready stages run through
`asyncio.gather` with isolated invocation/session state, at most three at a time. Selected output
collections merge after the batch joins. Dependent stages receive actual previous outputs. Failed stages
stop dependent work. Delegation is capped at 12 calls and eight session roles; the server configures
24 model calls per invocation (nested invocations have their own ceiling).

## Memory reads and writes

```mermaid
sequenceDiagram
    participant UI as Chat
    participant ADK as ADK Runner
    participant Hook as Memory plugin
    participant Bridge as Python adapter / Node bridge
    participant ML as letslego/memlayer
    UI->>ADK: Send prompt
    ADK->>Hook: before_run_callback
    Hook->>Bridge: Save working user turn
    Bridge->>ML: commitExchange journal + appendTurn hot state
    Bridge->>Bridge: Publish durable keyed snapshot
    ADK->>Hook: before_model_callback
    Hook->>Bridge: Read working, profile, episodic, knowledge
    Bridge->>ML: Profile revision / knowledge retrieval / working cache
    Bridge-->>Hook: Bounded records
    Hook-->>ADK: Historical context marked untrusted
    ADK->>Bridge: Explicit store_custom_memory when requested
    Bridge->>ML: Native fact / document / episode / audit write
    ADK->>Hook: after_tool_callback
    Hook->>Bridge: Operational tool name and result status
    ADK->>Hook: on_event_callback
    Hook->>Bridge: Save visible agent text as working history
    ADK-->>UI: Response, agent cards, memory viewer
```

Operational memory is never loaded by `before_model_callback`. Model reasoning marked as thought is
excluded from conversation persistence. Tool audit records omit tool arguments and credentials.

## Persistence boundaries

Native profile facts, documents, episodes, audits and journal records live in
`.adk/letslego-memlayer.sqlite`. The bridge keeps `.adk/memlayer-bridge-index.sqlite` for stable custom
keys, latest versions and durable session snapshots. It writes native MemLayer first, then publishes
the snapshot. Those two stores do not form one distributed transaction: a snapshot-write failure can
leave an orphaned native record. Native episodic/knowledge/audit writes are append-only; replacing a
custom key updates the bridge's current snapshot and can leave prior native versions.

`appendTurn` alone is transient. The bridge also commits each working item to MemLayer's journal and
persists its keyed snapshot, so our session view survives restart and hot-cache TTL. This is an adapter
for keyed items, not a claim that MemLayer's generic append API is durable or that every saved item is
a complete real user/assistant exchange. The journal's question carries the key envelope and its answer
carries the saved text. The SDK indexing worker runs in the bridge process.

Profile reads use MemLayer's revision-aware `getProfile`. Knowledge queries use its tenant-filtered
HNSW/BM25 retrieval and explicit user ACLs; empty-query memory browsing uses the snapshot index.
Episodic and operational custom-item browsing also uses the keyed snapshot index after native SDK writes.
The SDK's default hash embedder works offline; it is not a learned semantic embedding model.

Only profile-fact deletion is supported by the upstream public SDK. The bridge returns an explicit
conflict for deletion of working, knowledge, episodic or operational items rather than pretending the
native records were removed. A retention/deletion implementation is needed for those layers.

## Enterprise boundary

The persona selector and localhost API are demonstrations, not SSO or tenant authorization. The bridge
binds an application to a deterministic tenant and restricts knowledge documents to the supplied user;
production must derive both from authenticated server context. SQLite is single-host storage. Add
SSO, authorization, encryption/secret management, retention, operational access controls and deployment
hardening before enterprise exposure. Memory is historical data, never policy, permissions or verified
financial evidence.
