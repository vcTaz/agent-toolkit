Architecture approved with the following decisions and amendments.

## Confirmed decisions

Treat `/home/taz/agents` as the intended new project workspace.

Use:

- Python
- a `src/` package layout
- one async process for the MVP
- standard library where practical
- SQLite persistence
- a deterministic fake model provider initially
- objectively/tool-verifiable claims for the first validation scenario

A separate agent agreeing with a claim does **not** constitute factual verification.

## Architecture amendments

### 1. Add an explicit `INVALIDATED` Finding state

Do not overload `CRITIQUED` to represent knowledge that was previously validated but later lost a valid dependency.

Support a lifecycle conceptually like:

```text
PROPOSED
→ CRITIQUED
→ VALIDATED
→ INVALIDATED

PROPOSED → REJECTED
VALIDATED → SUPERSEDED

INVALIDATED → CRITIQUED → VALIDATED
INVALIDATED → REJECTED
```

Exact transition implementation may be refined if needed, but preserve the semantic distinction between:

- reviewed
- validated
- subsequently invalidated

### 2. Use `validated knowledge` terminology

Prefer names such as:

```text
candidate_findings
validated_findings
invalidated_findings
rejected_findings
```

Avoid using `accepted` when `validated` is the precise domain concept.

### 3. Keep `AgentGroup` lightweight

`AgentGroup` is a routing and branch-scope abstraction.

Do not turn it into a simulated human organization or introduce managers/subteams/hierarchy.

### 4. Keep orchestration policies modular

Do not let `orchestration.py` become a god object.

The controller should coordinate replaceable policy functions/services such as:

```text
decomposition
scheduling
budgets
review
branch stopping
synthesis gating
propagation
```

The deterministic controller still owns authoritative state transitions.

### 5. Preserve deterministic cross-pollination for the MVP

Keep the proposed explicit relevance scoring and delivery-history mechanism.

Do not introduce embeddings, vector search, or LLM-based routing yet.

We want routing decisions to be deterministic and inspectable before experimenting with semantic routing.

---

# Implementation authorization

Implement **Stages 1 through 3 only** from `docs/architecture-review.md`.

Do not implement Stages 4–8 yet.

The purpose of this checkpoint is to establish reliable foundations before introducing scheduler and swarm-loop complexity.

## Stage 1 — Domain foundation

Implement:

- package/project scaffolding
- `pyproject.toml`
- domain enums and records
- Agent
- Role
- Task
- Finding
- Message
- SwarmState
- AgentGroup
- Run
- Assignment
- ReviewRecord
- supporting evidence/result value records as needed
- serialization
- schema versioning
- legal lifecycle transitions
- domain invariants

Important:

Models/provider outputs must never mutate authoritative domain state directly.

The controller/domain services own legal transitions.

Test at least:

- serialization round trips
- invalid transitions
- task dependency cycles
- finding dependency cycles
- cross-run references
- dynamic role reassignment while idle
- rejection of role reassignment while running
- Finding invalidation behavior
- immutable substantive Finding content/revision behavior

---

## Stage 2 — Audit and persistence foundation

Implement:

- structured event envelope
- event types required for these first stages
- SQLite repository
- transaction boundaries
- per-run monotonic event sequence
- record persistence
- event persistence
- inspection/reload support

A domain state mutation and the events describing that mutation must commit atomically where applicable.

Do not implement full event sourcing.

The canonical domain records remain directly persisted records.

Test:

- atomic rollback
- event sequence ordering
- record/event consistency
- reload for inspection
- storage failure behavior
- multiple independent runs
- revisions
- interrupted/incomplete run inspection

No crash-resume behavior is required yet.

---

## Stage 3 — Execution seam

Implement the narrow provider and tool contracts.

Target interfaces should remain roughly:

```python
await provider.generate(request)
```

and:

```python
await tool.execute(arguments, execution_context)
```

but choose idiomatic Python types.

Implement:

- ModelProvider protocol/interface
- ModelRequest
- ModelResponse
- normalized provider errors
- Tool / ToolSpec
- ToolResult
- ExecutionContext
- ExecutionResult envelope
- output validation
- fake/scripted provider
- pure arithmetic verification tool
- role-based tool permissions
- execution timeout handling
- provider request accounting
- schema/output repair limit
- structured execution events

The fake provider should support scripted scenarios including:

- valid structured response
- malformed response
- incorrect claim
- provider disagreement
- timeout
- tool request
- forbidden tool request

Important security/control rule:

A model output may **propose**:

```text
findings
messages
task requests
reviews
results
```

but it may not authoritatively:

```text
validate a finding
change run state
complete arbitrary tasks
manufacture tool evidence
change another agent
bypass permissions
```

Those operations remain controller-owned.

---

# Constraints

Do not yet implement:

- scheduler
- full orchestrator loop
- consolidation
- cross-pollination execution
- synthesis
- final review workflow
- real OpenAI provider
- embeddings
- vector database
- distributed workers
- UI
- crash recovery

Interfaces/placeholders are acceptable where later stages require them, but do not prematurely implement those systems.

---

# Completion criteria

When Stages 1–3 are finished:

1. Run the full test suite.
2. Fix failures.
3. Show the final repository tree.
4. Summarize important implementation decisions.
5. Show the domain lifecycle definitions.
6. Show the provider/tool interfaces.
7. Show how SQLite records and events are stored.
8. Report tests passed/failed.
9. Identify any deviations from `docs/architecture-review.md`.
10. Identify anything discovered during implementation that should change the later architecture.

Then stop.

Do not begin Stage 4 until I explicitly authorize it.