I want you to help me turn this repository into a reusable multi-agent swarm framework.

The core design principle is:

> Do not model the system as a fake human company with rigid titles. Model it as a distributed computational system where agents dynamically take on functional roles such as exploration, criticism, validation, specialization, consolidation, cross-pollination, synthesis, and final review.

Before writing significant code, inspect the entire repository and read all architecture/documentation files, especially:

- `AGENTS.md`
- `README.md`
- `docs/`
- `agents/`
- `orchestration/`
- `protocols/`
- `prompts/`
- `schemas/`

Treat the Markdown files as the architectural source of truth.

## Primary objective

Build a minimal but extensible implementation of the swarm architecture described in the repository.

Do not try to implement a huge production system immediately.

First create a clean foundation that makes the following workflow possible:

```text
objective
    ↓
orchestrator
    ↓
task decomposition
    ↓
parallel agents
    ↓
exploration / specialization
    ↓
criticism
    ↓
validation
    ↓
consolidation
    ↓
cross-pollination
    ↓
further exploration if needed
    ↓
synthesis
    ↓
final review
    ↓
final result
```

## Architectural requirements

### 1. Agent

Create a generic `Agent` abstraction.

An agent should not be permanently tied to a role.

An agent should have concepts such as:

```text
id
model/provider
current role
objective
context
tools
permissions
state
assigned task
message history
```

The exact implementation is up to you, but keep the abstraction simple and composable.

---

### 2. Roles

Roles should be configuration/behavior definitions rather than separate hard-coded agent classes wherever practical.

Initial roles:

```text
EXPLORER
SPECIALIST
CRITIC
VALIDATOR
COLLABORATOR
CONSOLIDATOR
CROSS_POLLINATOR
SYNTHESIZER
FINAL_REVIEWER
```

The orchestrator is a system-level component and does not necessarily need to behave exactly like a normal worker agent.

A role may define:

```text
instructions
allowed tools
input expectations
output schema
communication permissions
validation requirements
termination conditions
```

Agents should be able to change roles dynamically.

---

### 3. Task model

Create a structured `Task` representation.

It should support at least:

```text
id
parent_task_id
objective
description
status
priority
dependencies
assigned_agents
created_at
updated_at
candidate outputs/findings
```

Tasks should be decomposable into subtasks.

---

### 4. Finding model

Agents should not communicate only through raw chat messages.

Create a first-class structured `Finding` object representing useful knowledge discovered by the swarm.

A finding should be able to contain concepts such as:

```text
id
task_id
agent_id
claim
evidence
reasoning summary
confidence
status
dependencies
related findings
validation state
```

Possible states may include:

```text
PROPOSED
CRITIQUED
VALIDATED
REJECTED
SUPERSEDED
```

Do not over-engineer this state machine initially.

---

### 5. Messaging

Create a structured inter-agent message model.

Messages should support targeted communication such as:

```text
agent → agent
agent → group
agent → orchestrator
orchestrator → agent
system → group
```

Avoid building an uncontrolled global chatroom.

Communication should be routable and inspectable.

---

### 6. Shared state

Implement a swarm-level shared state or knowledge store.

It should contain compact, useful information such as:

```text
active tasks
validated findings
important candidate findings
known failed approaches
open questions
current priorities
active agent groups
```

Do not simply dump every agent transcript into shared context.

The architecture should distinguish between:

```text
raw communication
vs.
compressed shared knowledge
```

---

### 7. Orchestrator

Implement an initial orchestrator.

Its responsibilities should include:

```text
receive objective
decompose work
create tasks
spawn/assign agents
assign roles
monitor task state
route important findings
trigger criticism
trigger validation
trigger consolidation
expand promising branches
stop low-value branches
determine when synthesis should begin
```

Keep policy logic modular.

I want to be able to improve orchestration strategies later without rewriting the entire framework.

---

### 8. Consolidation

Implement a basic consolidation mechanism.

Its purpose is to periodically transform many agent outputs into a smaller set of useful findings.

Conceptually:

```text
collect
→ deduplicate
→ compare
→ rank
→ summarize
→ update shared state
```

The implementation can initially be simple.

The important thing is that consolidation exists as a separate architectural concept.

---

### 9. Cross-pollination

Implement a mechanism for important discoveries from one branch to influence other relevant branches.

Do not broadcast every message to every agent.

Prefer:

```text
important finding
    ↓
identify relevant tasks/groups
    ↓
send compact insight
    ↓
agents reconsider their approach
```

This mechanism should be explicit enough that we can inspect when and why information was propagated.

---

### 10. Criticism and validation

A candidate result should not automatically become accepted because one agent produced it.

Where practical, use separate agents or separate passes for:

```text
generation
criticism
validation
```

Conceptually:

```text
candidate
    ↓
critic attempts to break it
    ↓
validator attempts to independently verify it
    ↓
accepted / revised / rejected
```

The validator should not merely ask the original agent whether it is correct.

---

### 11. Synthesis and final review

Once enough validated information exists:

```text
SYNTHESIZER
```

should construct the candidate final result.

Then:

```text
FINAL_REVIEWER
```

should independently inspect the complete output.

Possible final-review decisions:

```text
PASS
REVISE
REJECT
```

A failed review should be able to generate new tasks.

---

## Implementation philosophy

Prioritize:

```text
clarity
modularity
observability
testability
replaceable components
structured data
small interfaces
```

Avoid:

```text
premature distributed infrastructure
unnecessary microservices
huge inheritance hierarchies
hard-coded provider logic everywhere
fake organizational hierarchy
magic global state
unstructured prompt spaghetti
```

Start with an architecture that can run locally in a single process.

Concurrency can initially use something simple such as async tasks if appropriate.

The system should be designed so that more sophisticated distributed execution could be introduced later.

---

## Model-provider abstraction

Do not tightly couple the architecture to a single model API.

Create a narrow model interface such as:

```text
generate(...)
```

or an equivalent abstraction.

Provider-specific implementations should sit behind that interface.

If credentials or provider configuration are not available, create a mock/fake provider so the framework and tests can still run.

Do not insert secrets into the repository.

---

## Tools

Tools available to agents should also use a simple interface.

Conceptually:

```text
Tool
    name
    description
    execute()
```

Role/tool permissions should be explicit.

We should eventually be able to give different roles different tool access.

---

## Observability

This is important.

I want to be able to understand what the swarm is doing.

Create structured events/logging for meaningful operations such as:

```text
agent spawned
role assigned
task created
task completed
finding created
finding criticized
finding validated
finding rejected
message routed
cross-pollination event
branch stopped
synthesis started
final review completed
```

Prefer structured events over random print statements.

---

## Persistence

For the first version, keep persistence simple.

A local JSON/JSONL/SQLite implementation is acceptable.

Do not introduce a heavy external database unless the existing repository clearly requires one.

Persist enough information that a swarm run can be inspected afterward.

---

## Tests

Add tests for the important control logic.

At minimum, I want coverage for things like:

```text
task creation/decomposition
dynamic role assignment
finding lifecycle
message routing
validation transitions
shared-state updates
cross-pollination routing
orchestrator state transitions
```

Also create at least one end-to-end test using fake agents/models.

The test should demonstrate a tiny swarm solving a toy problem through multiple roles.

---

## Example execution

Create a minimal runnable example.

Something roughly equivalent to:

```bash
python -m swarm run "Investigate X and produce a validated answer"
```

or whatever interface best fits the existing project.

The example should visibly demonstrate:

```text
objective received
tasks created
multiple agents spawned
candidate findings generated
criticism performed
validation performed
knowledge consolidated
synthesis produced
final review executed
result returned
```

The exact CLI is your choice.

---

## Repository documentation

As implementation progresses, update the architecture documentation when necessary.

Keep:

```text
documentation
implementation
schemas
tests
```

consistent with each other.

Do not let the Markdown architecture drift away from the actual implementation.

If you discover that an architectural assumption in the docs is problematic, do not silently ignore it.

Document the discrepancy and implement the cleaner design.

---

## First task

Do NOT immediately build everything.

Start by doing the following:

1. Inspect the repository.
2. Summarize the architecture you believe the documentation describes.
3. Identify ambiguities, contradictions, and missing concepts.
4. Propose the minimal internal data model and module/package structure.
5. Identify what belongs in the MVP versus later versions.
6. Then implement the MVP foundation.
7. Run tests.
8. Show me what was created, what design decisions you made, and what should be implemented next.

Make reasonable architectural decisions yourself instead of repeatedly stopping for minor clarifications.

When uncertain, prefer the simplest design that preserves future extensibility.

## MVP success criteria

The first implementation is successful if a local test run can demonstrate this loop:

```text
objective
→ orchestrator
→ multiple tasks
→ multiple agents
→ findings
→ criticism
→ validation
→ consolidation
→ synthesis
→ final review
→ result
```

It does NOT need to be production-ready.

It DOES need to make the architecture real enough that we can begin experimenting with swarm behavior.