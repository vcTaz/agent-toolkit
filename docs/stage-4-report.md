# Stage 4 checkpoint — work scheduling, groups, messaging, bounded context

Implemented only the Stage-4 authorization: concurrent work coordination. Nothing decides whether a
finding is true. Criticism, validation, knowledge promotion, consolidation, cross-pollination,
synthesis, final review, the full run state machine, real providers, embeddings, distributed
execution, UI and crash resume remain unimplemented.

## Pipeline

```text
Task DAG → READY tasks → bounded scheduler → Agent + Role assignment → pinned Assignment snapshot
       → bounded Context → Executor → structured proposals → controller admission
```

## Controller boundary

`swarm.orchestration.WorkController` owns one run on one event-loop thread. It alone determines
readiness, selects work, assigns idle agents and compatible roles, creates Assignments, transitions
Agent/Task/Assignment lifecycles, builds the assignment snapshot, invokes execution, validates
returned proposals against current state, commits permitted outcomes, rejects stale or invalid
responses, handles cancellation/failure and updates durable accounting.

`swarm.execution.execute` stays non-authoritative: it returns draft proposals and never touches
canonical records. The invariant `model/executor proposes → controller decides → repository commits`
holds because the executor has no repository handle; its only host callback is a synchronous audit
sink that the controller wraps with its own authorization checks.

### Transaction boundaries

Every authoritative change is a `SQLiteRepository.commit(run_id, records, events)` call: records and
their events land in one `BEGIN IMMEDIATE` transaction that re-reads current state, compares every
revision, validates the merged snapshot, checks per-type update rules and rolls back on any failure.

The controller performs each commit synchronously with no `await` between reading a snapshot and
committing state derived from it, so concurrent executions cannot interleave inside a decision.
Dispatch is two commits: preparation (assignment + context event + role assignment) then activation
(task RUNNING, agent RUNNING, assignment RUNNING). Completion is one commit carrying the admitted
proposals, the lifecycle transitions and the message read receipts.

Durable accounting (`swarm.audit.RepositoryAudit`) also commits synchronously, from inside the
worker coroutine but still on the controller's thread, so a provider request is counted durably
before it is dispatched. Any `StorageError` stops the controller instead of continuing with
unaudited authoritative state.

## Readiness and scheduling

`policies.ready_decision` admits a task only when it is PENDING/READY, the run is neither stopped nor
past its deadline, every dependency exists in the same run and is COMPLETED, no dependency failed or
was cancelled, and its group is still ACTIVE. Decisions carry a reason and a `permanent` flag;
permanent blocks cancel the task with that reason rather than leaving it pending forever.

`parent_task_id` expresses decomposition and never implies readiness; only `dependency_ids` orders
execution. A failed or cancelled dependency permanently blocks its dependents, which the controller
records as `DEPENDENCY_FAILED`; work left with no possible progress is cancelled as
`DEPENDENCY_BLOCKED`.

### Scheduler algorithm

Deterministic, no model involvement:

1. Read a snapshot; stop if cancelled, stopped or past deadline.
2. Deliver queued messages.
3. Order candidate tasks by `(-priority, created_at, id)` (`policies.select_tasks`).
4. For each task in order, while `len(active) < run.concurrency_limit`:
   readiness → role (`role_for`) → any compatible agent at all → budget admission → an *idle*
   compatible agent (`compatible_agents`) → mark READY → prepare and activate → dispatch.
5. Await the first of: any running execution, a wake event, the run deadline.
6. Finish completed executions in sorted assignment-id order, one commit each.
7. Repeat; when nothing is active and nothing is dispatchable, cancel the remainder with a reason and
   return.

Enforced limits: `concurrency_limit`; one RUNNING assignment per agent (only idle agents are
selectable, and `validate_records` rejects a snapshot violating it); one active assignment per task
(only PENDING/READY tasks are selectable, and the same snapshot rule applies); the run deadline;
`assignment_attempt_limit`; the durable provider/tool budgets; and no dispatch at all once a terminal
or cancellation condition is recorded in `Run.work_stop_reason`.

## Assignment snapshot and stale-output protection

An Assignment pins task id + revision, role id + version, agent, group, input finding ids +
revisions, message ids + delivery revisions, dependency task ids + revisions, criterion ids +
content hashes, tool names + spec hashes, `SwarmState` id + revision, attempt number, and the
context JSON with its hash.

`admission.check_assignment_admissibility(assignment, execution_result, snapshot)` returns a
`Decision(allowed, reason)`. The stored assignment record is the authority: a caller-supplied copy
whose provenance differs is rejected as `ASSIGNMENT_PROVENANCE_MISMATCH`, so a forged snapshot cannot
widen its own admissibility. Rejection reasons are structured: `ASSIGNMENT_NOT_RUNNING`,
`RUN_STOPPED`, `ASSIGNMENT_ID_MISMATCH`, `TASK_NOT_ASSIGNED`, `TASK_REVISION_CHANGED`,
`AGENT_NOT_ASSIGNED`, `ROLE_CHANGED`, `PROVIDER_CHANGED`, `GROUP_CHANGED`, `GROUP_UNAVAILABLE`,
`DEPENDENCY_TASK_CHANGED`, `INPUT_FINDING_CHANGED`, `MESSAGE_DELIVERY_CHANGED`, `CRITERION_CHANGED`,
`PERMISSIONS_CHANGED`, `TOOL_DEFINITION_CHANGED`, `LATER_STAGE_PROPOSAL_FORBIDDEN`.

Only pinned dependencies are checked, so unrelated revisions — another agent's read receipt, an
unrelated `SwarmState` field, the run's own request counter — do not reject a result. A late result
from a cancelled or superseded assignment finds its record no longer RUNNING and is discarded with
`OUTPUT_REJECTED`; it can never mutate canonical state.

Everything an execution relies on is pinned, including the transitive dependency findings of any
disclosed candidate and the findings referenced by a delivered message, so invalidating that
supporting knowledge rejects the dependent output.

## Groups and messaging

`AgentGroup` stays flat: branch scope, membership, task association, routing boundary and tags, with
`ACTIVE → CLOSED`. A closed group rejects ordinary delivery; only `SYSTEM`-kind messages pass.

`messaging.route_message` validates the run, message state, kind, bounded payload, sender identity,
references, and recipient — `agent:<id>`, `group:<id>` or `orchestrator` only. There is no broadcast
address. Group delivery records the membership snapshot in `delivered_to` with `delivery_revision`;
later membership changes do not retroactively deliver or undeliver. A sender must be a current member
of the target group unless its role scope is wider. References must resolve inside the run and inside
the delivery scope, otherwise `REFERENCE_OUT_OF_SCOPE` or `REFERENCE_NOT_DELIVERED`, so a message
cannot smuggle another branch's records to its recipients. Delivery metadata is recorded once; the
message is not copied into a per-agent transcript. Context construction selects from delivered,
unread messages, and the read receipt is recorded only when the assignment that consumed it
succeeded, so a bounded retry sees the same targeted messages the failed attempt did.

## Context selection

`context.ContextBuilder.build` is a separate service from scheduling, execution, provider adapters
and state transitions. It emits an immutable `ContextSnapshot` with the serialized payload, its
hash and size, the pinned finding/message ids and revisions, criterion hashes, and the selected ids,
omitted ids and per-id reasons that are recorded through `CONTEXT_SELECTED`.

Order, indispensable first:

1. assignment/task objective and description
2. acceptance criteria
3. target claim (`target_finding_id`) with full evidence
4. required dependency evidence, transitively closed, with full evidence
5. relevant validated findings projected into `SwarmState`
6. targeted unread messages, plus the findings they reference
7. optional permitted candidate summaries
8. failed-approach summaries

Limits: 8 validated findings, 4 candidate summaries, 5 messages, 3 failed-approach summaries and
24,000 serialized characters, measured on the exact executor framing. Steps 1–4 are indispensable:
if they do not fit, construction fails with `INDISPENSABLE_CONTEXT_OVERFLOW`,
`INDISPENSABLE_COUNT_OVERFLOW`, `REQUIRED_FINDING_MISSING`, `REQUIRED_FINDING_UNAVAILABLE`,
`CANDIDATE_NOT_PERMITTED`, `DEPENDENCY_MISSING` or `UNKNOWN_CRITERION`, and no provider request is
made. Optional material is dropped deterministically with `COUNT_LIMIT`, `SIZE_LIMIT`,
`NOT_DISCLOSABLE` or `GROUP_DROPPED`; a finding is admitted only together with its full dependency
closure, so a partial pin is never recorded.

There is at most one `SwarmState` per run; several would mean silently serving one agent's stale
projection, so construction fails with `AMBIGUOUS_SWARM_STATE` instead of choosing. Closure walks are
iterative and memoized, so a deep or widely shared dependency graph returns a decision rather than
overflowing the stack or re-walking shared subgraphs. Failure reasons are order-independent: the
lexicographically first offending required finding is reported regardless of set iteration order.

### Privacy boundaries

Nothing is injected automatically. Provider transcripts stay inside the execution seam, another
agent's messages are never selected, group membership permits selection rather than injection of
group history, only explicitly permitted candidates are eligible, tool outputs enter only as
host-attributed evidence on selected findings, and the event history is never context. Findings the
builder chooses *on its own* — the validated pool, message references and optional candidates — are
disclosable only if they come from this task, a declared dependency task, or a task in the same group
branch (`scope.visible_finding`).

`Task.required_finding_ids` and `Task.target_finding_id` deliberately sit outside that filter. They
are host authority: the controller states exactly which evidence an assignment must have, and the
architecture requires critics and validators to receive explicitly assigned targets across scopes.
No model-reachable path can set them — `TaskDraft` has no finding fields and no task request becomes
a Task — so this is a controller decision, not an escape hatch. Both halves of the rule are pinned by
test: host-assigned evidence crosses a group boundary, and the same finding offered only as an
optional candidate does not.

`scope.owning_group` classifies references by their owning branch — a review is exactly as private as
what it reviews, a task request as private as its parent — and fails closed: a record type it does
not recognize is `UNRESOLVED` and therefore undisclosable, so a record type added in a later stage
cannot silently inherit delivery rights.

## Output admission

After execution returns, the controller re-validates against current state and then admits only
structurally valid Stage-4 proposals: findings as PROPOSED, messages as QUEUED for the next delivery
pass, and task requests as immutable `TaskRequest` proposals. Findings are never promoted, no review
or result proposal is accepted, and identities are always controller-generated. Model references
cannot escape the run: finding evidence may reference only successful tool results of that
execution, and message references only what the assignment's own context pinned.

### Task requests

`admission.check_task_request` validates parent ownership, run ownership, objective/description
size, remaining run limits and budget, dependency existence and uniqueness, DAG integrity including
the proposed node, criterion relationships against the parent task, and a normalized fingerprint
that rejects duplicates. Admitted requests persist as proposals with `executable: false`; nothing in
Stage 4 converts one into a Task, so agents cannot recursively spawn work. Rejections are recorded
with reasons such as `INVALID_REQUEST_PARENT`, `REQUEST_SIZE`, `REQUEST_BUDGET_EXHAUSTED`,
`TASK_LIMIT`, `INVALID_REQUEST_DEPENDENCY`, `REQUEST_CYCLE`, `INVALID_REQUEST_CRITERIA` and
`DUPLICATE_REQUEST`.

## Execution outcomes

| Outcome | Controller behaviour |
|---|---|
| SUCCEEDED | Admit proposals, complete the task, record receipts, idle the agent. A completed task is not validated knowledge. |
| NEEDS_INPUT | Recorded as the task outcome with its stated gap, then the bounded retry path; never an open-ended wait. |
| FAILED | Recorded, then retried while attempts and budget remain, otherwise the task fails. Retry authorization belongs to the controller, not the provider adapter. |
| Timeout | Execution is cancelled at `min(execution_timeout, remaining run seconds)`, recorded as a timeout and treated as a bounded failure. |
| Cancelled | Local work is cancelled, records transition, `work_stop_reason` persists, and any late result is rejected. |
| Stale | `OUTPUT_REJECTED` with the structured reason; no proposal is committed. |
| Malformed after repair | One bounded repair inside the attempt, then an execution failure through the retry path. |
| Storage failure | Propagates, marks the controller failed and prevents further dispatch. |

## Budgets

One authoritative run-level budget lives in the `Run` record and is incremented durably before each
provider request and tool call, so nothing resets per execution. The in-process `Budget` is a mirror
of that ledger, not a second authority: a dispatch the host refuses releases its reservation, so the
mirror can never claim more of the run than the durable record shows and cannot starve later work. `policies.BudgetPolicy` is the
separate, replaceable admission policy: it refuses dispatch when remaining capacity would fall to
the reserved floor, counts in-flight first-request reservations, and additionally reserves capacity
for every outstanding required task before admitting an optional one. The mechanism (counters and
the reservation set) is independent of that policy, so later synthesis reservations can plug in.

## Events

Stage-4 coverage: `TASK_READY`, `TASK_ASSIGNED`, `TASK_COMPLETED`, `TASK_FAILED`, `TASK_CANCELLED`,
`AGENT_STARTED`, `AGENT_COMPLETED`, `AGENT_FAILED`, `ROLE_ASSIGNED`, `CONTEXT_SELECTED`,
`MESSAGE_SENT`, `MESSAGE_DELIVERED`, `MESSAGE_REJECTED`, `RETRY_SCHEDULED`, `OUTPUT_REJECTED`,
`TASK_REQUEST_ADMITTED`, `TASK_REQUEST_REJECTED`, `WORK_STOPPED`, `GROUP_CLOSED`, `RECORD_CHANGED`,
plus the Stage-3 execution envelopes. Each carries structured reasons for stale results, blocked
dependencies, context overflow, rejected task requests, permission incompatibility and cancellation,
and every record mutation carries its before/after. Events have a contiguous per-run sequence;
external provider completion order is deliberately not forced to match scheduler start order.

## Policy separation

Replaceable decisions live outside the controller: `policies` (readiness, selection, role choice,
agent compatibility, retry, budget admission), `admission` (assignment admissibility, task-request
admission), `context` (context selection), `messaging` (routing and delivery), `scope` (disclosure
boundaries) and `outcomes` (proposal admission). They are plain functions and frozen dataclasses; no
plugin framework was introduced.

## Verification

99 unittest tests pass from source on CPython 3.13.5 and 3.12.12, and the same suite passes against
the built wheel (`swarm_foundations-0.2.0-py3-none-any.whl`, built with locally available setuptools,
no downloaded runtime dependencies) imported from an isolated environment with `src` off the path.

| File | Tests | Area |
|---|---|---|
| `tests/test_domain.py` | 14 | records, transitions, cycles, provenance |
| `tests/test_persistence.py` | 12 | SQLite atomicity, revisions, update rules |
| `tests/test_execution.py` | 21 | bounded execution seam, hostile output, budgets |
| `tests/test_audit_integration.py` | 2 | durable counters across executions |
| `tests/test_stage4_services.py` | 27 | routing, context, readiness, admissibility, disclosure scope |
| `tests/test_stage4_controller.py` | 23 | controller scheduling, staleness, privacy, budgets, cancellation |

Beyond the suite, a 15-trial randomized stress run (12 tasks in a dependency chain, 4 agents,
concurrency 3, varying provider delays) confirmed that dependencies never start before their
predecessor completed, that every snapshot passes `validate_records`, that per-run event sequences
stay contiguous, and that identical provider timing reproduces identical outcomes while different
timing profiles produce genuinely different interleavings.

Guards were checked by mutation rather than assumed. Disabling each of these makes at least one test
fail: the reference scope check, the fail-closed scope default, the undelivered-message guard,
atomic closure admission, candidate visibility, message-reference pinning, dependency-closure
walking, the count cap, the size cap, the indispensable-overflow check, the ambiguous-state check,
assignment provenance comparison, recipient-based message selection, the readiness gate, budget
admission, the permission gate, the idle-agent requirement, output admissibility, the concurrency
cap, and the durable stop gate. Notably, message pinning is defended twice — selecting a message for
the wrong agent is caught again at output admission as `MESSAGE_DELIVERY_CHANGED`, because the
assignment pinned a delivery the agent was not part of.

Two independent reviews and the mutation work produced eight defects, all fixed rather than
documented away: a bounded retry silently lost the targeted messages its failed attempt consumed; a
failing repository could leave an execution exception unretrieved; `scope.owning_group` failed open
for record types it did not classify, so a message could reference another branch's review or task
request; optional dependency closures recursed and could raise `RecursionError` instead of a
decision, and re-walked shared subgraphs; several `SwarmState` projections silently resolved to the
oldest; the reason reported for simultaneously invalid required findings depended on set iteration
order; a refused dispatch left its in-process budget reservation consumed, drifting from the durable
ledger; and the concurrency cap, the durable deadline stop reason and a dangling sender group had no
test that bound them.

One branch is deliberately kept without a reachable trigger: when the loop finds nothing active and
nothing dispatchable, it cancels any surviving PENDING/READY task as `DEPENDENCY_BLOCKED`. Every
path that refuses a task already records its own reason, so this is a backstop for the requirement
that work is never silently left pending forever, not a case the current design can produce.

## Deviations from the architecture review

1. **Optional-context ranking omits recency.** The review ranks optional context by direct
   dependency, criterion match and recency. `Finding` carries no timestamp, so ranking is by
   dependency-task first, then stable id. Deterministic, but not recency-aware.
2. **Character budget is measured on the full executor framing** — role instructions, the JSON
   envelope with escaping, and the output contract — rather than the context payload alone. This is
   stricter than the review's wording and prevents a context that fits in isolation from overflowing
   once framed.
3. **Run workflow states are not transitioned.** `transition()` still refuses `Run`, and the
   repository rejects run state changes. A durable `Run.work_stop_reason` provides the
   stop-all-dispatch signal instead of `RUN_STATE_CHANGED`, deferring the state machine to a later
   stage as instructed.
4. **Finding lifecycle events are generic.** New findings are recorded as `RECORD_CHANGED` with
   before/after detail rather than the review's `FINDING_CREATED`; the review's finding/review event
   names belong to the promotion workflow that Stage 4 does not implement.
5. **`Assignment.context_revision` is left at its default.** The review lists a "context revision";
   Stage 4 pins the content-addressed `context_hash` instead, which is strictly stronger for
   staleness. The counter field is retained untouched for a later stage that may update a running
   assignment's context in flight.
6. **`AgentGroup` has no parent group id.** The review lists it as optional; Stage 4 was instructed
   to keep groups flat, so nesting was not added.
7. **`SwarmState` is read-only.** Stage 4 selects from it but never writes it, because writing it is
   knowledge promotion.

## Design issues that should shape Stage 5

1. **Nothing adopts a `TaskRequest`.** Admitted requests are inert proposals; no code converts one
   into a Task. Stage 5 (or a decomposition stage) needs an explicit controller adoption policy with
   its own budget and DAG checks, otherwise requests accumulate without effect.
2. **Run workflow authority must be opened deliberately.** Two guards currently forbid run state
   changes: `domain.transition` and `persistence._validate_update`. Both must be replaced by a gated
   transition table in the same change, or the repository will reject the controller's own writes.
3. **Review roles are excluded end to end.** `policies.WORK_ROLES` admits only EXPLORER, SPECIALIST
   and COLLABORATOR; `policies.role_for` maps only three task kinds; and
   `admission.check_assignment_admissibility` rejects any `review`/`result` proposal as
   `LATER_STAGE_PROPOSAL_FORBIDDEN`. Enabling criticism and validation means extending all three
   together, per role, rather than loosening the admission check alone.
4. **Validation evidence needs a host verifier.** `transition(finding, VALIDATED)` demands a review
   whose evidence is `verified`, tool-backed and from a different agent. Stage 4 always records
   proposal evidence as `verified=False`. Stage 5 must add the host path that checks a tool result
   actually proves the exact claim before marking review evidence verified — that check, not the
   role name, is what makes validation meaningful.
5. **NEEDS_INPUT currently ends in FAILED.** The bounded retry path is deterministic and cannot hang,
   but once task requests can be adopted, the better shape is a recorded prerequisite gap plus an
   admissible request, with a distinct blocked outcome rather than a failure.
6. **Budget reservation covers only the first provider request per assignment.** That is sufficient
   for Stage-4 optional-versus-required protection but not for reserving whole-workflow capacity.
   `BudgetPolicy` is already the single pluggable seam for the synthesis/final-review reservation.
7. **One active assignment per task** means criticism and validation of the same finding must be
   modelled as separate tasks carrying `target_finding_id`, not as extra assignments on the original
   task. Stage 5 should confirm that shape before building the review workflow.
8. **Promotion must update `SwarmState` atomically with finding transitions.** `validate_records`
   already rejects a snapshot whose `SwarmState` classification disagrees with finding status, so a
   promotion that writes one without the other will be refused at commit time.
9. **`validate_records` should enforce one `SwarmState` per run.** Stage 4 now refuses to build a
   context from an ambiguous set, but the invariant belongs in the domain so a second projection can
   never be committed. Promotion must also decide, and record, whether it bumps the existing state's
   revision or creates a new identity.
10. **`validate_records` still walks dependency and parent edges recursively.** Stage 4 removed the
    recursive walk from context construction, but the same unbounded pattern remains in domain
    validation, where a pathologically deep chain would raise `RecursionError` instead of
    `DomainError`. Worth converting when the graph starts growing from admitted task requests.
11. **An agent cannot reference the finding it just proposed.** Identities are controller-generated
    after the output is parsed, and a proposed message may only reference what the assignment's
    context pinned, so a worker that proposes a finding and a message about it cannot link them.
    That is correct for Stage 4, but cross-pollination will need the controller to attach the
    reference on the agent's behalf.
12. **`Task.required_finding_ids` and `target_finding_id` are host authority that bypasses group
    scope.** That is correct and necessary for cross-scope review targets, but it means whatever
    Stage 5 builds to create critic and validator tasks becomes the sole guard against accidental
    cross-branch disclosure. Give that code an explicit, audited decision rather than letting it
    inherit fields from a template task.
