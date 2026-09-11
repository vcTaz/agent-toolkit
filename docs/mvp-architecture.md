# The MVP architecture, as implemented

Date: 2026-09-10. Status: complete. This describes the system that exists after Stages 1–8.

This is a *map of the implementation*, not a design proposal and not a history. The
full-system design, including features deliberately left unimplemented, is
[`architecture-review.md`](architecture-review.md). The reasoning behind each layer is in
its stage report; this document does not repeat it:

| Layer | Stage report |
|---|---|
| Domain, persistence, execution seam | [`stages-1-3-report.md`](stages-1-3-report.md) |
| Scheduling, groups, messaging, bounded context | [`stage-4-report.md`](stage-4-report.md) |
| Criticism, validation, verification, consolidation | [`stage-5-report.md`](stage-5-report.md) |
| Cross-pollination, reconsideration, cycles, branch stopping | [`stage-6-report.md`](stage-6-report.md) |
| Synthesis gate, result versions, final review, terminal outcomes | [`stage-7-report.md`](stage-7-report.md) |
| CLI, scenarios, inspection, evaluation, packaging | [`stage-8-report.md`](stage-8-report.md) |

## The invariant chain

Everything below is an elaboration of three sentences:

```text
model / executor proposes
controller decides
repository commits
```

and of three consequences of them:

```text
model agreement != verification      the epistemic boundary
propagate discoveries, not transcripts   the circulation rule
readiness is computed, never asserted    the completion rule
```

## Layers

```text
                        ┌──────────────────────────────────────────────┐
   configuration        │ scenario   validated, fail-closed            │
                        │ runner     seeds one run, drives it          │
                        │ cli        run / inspect / list / evaluate   │
                        └───────────────────┬──────────────────────────┘
                                            ↓
                        ┌──────────────────────────────────────────────┐
   run workflow         │ workflow   guarded run state machine         │
                        │ completion the synthesis gate                │
                        │ synthesis  controller-owned answer building  │
                        │ finalreview independence, verdicts, repair   │
                        └───────────────────┬──────────────────────────┘
                                            ↓
                        ┌──────────────────────────────────────────────┐
   work engine          │ engine       admitted work to quiescence     │
                        │ circulation  knowledge movement              │
                        │ controller   identity, transactions, seam    │
                        └───────────────────┬──────────────────────────┘
                                            ↓
                        ┌──────────────────────────────────────────────┐
   services             │ policies admission review verification       │
                        │ knowledge propagation cycles context scope   │
                        └───────────────────┬──────────────────────────┘
                                            ↓
                        ┌──────────────────────────────────────────────┐
   foundation           │ domain invariants schema serialization       │
                        │ persistence audit events contracts           │
                        └──────────────────────────────────────────────┘

   inspection / timeline / metrics / render / evaluation read the foundation only.
```

## Domain

`domain.py` holds every canonical record as a frozen dataclass, every enum as a `StrEnum`
with stable serialized values, and the guarded lifecycle function `transition`. Records
carry `schema_version` (4) and a monotonic `revision`.

The eight core objects are `Run`, `Task`, `Agent`, `Role`, `Finding`, `Message`,
`SwarmState` and `AgentGroup`. `Assignment` and `ReviewRecord` preserve provenance across
dynamic role reassignment. Stage 5 added `Conflict`; Stage 6 added `Propagation` and
`Cycle`; Stage 7 added `Result` and `TerminalReport`, both written once.

Three things live in the domain because they are structural, not policy:

- **Legal transitions.** `TRANSITIONS` and `RUN_TRANSITIONS` refuse an illegal step wherever
  it comes from. The four terminal run states are absent from `RUN_TRANSITIONS`, so they are
  absorbing by construction rather than by a special case.
- **Promotion's preconditions.** `transition(finding, VALIDATED, review=…)` refuses unless
  the review is a validation, by a different assignment, at the exact revision, with no
  blocking issues, carrying host-verified tool evidence.
- **Snapshot invariants.** `invariants.py` validates a whole committed snapshot: reference
  integrity, classification consistency, acyclic task/finding/result graphs, singletons
  (one projection, one open cycle, one accepted result, one terminal report per run), and
  the fact that `COMPLETED` and an accepted result are one thing.

Domain code imports no provider, no prompt and no storage.

## Persistence

`persistence.SQLiteRepository` is one local SQLite database with a `records` table keyed by
`(run_id, id)` and an append-only `events` table with a per-run monotonic `sequence`. One
controller transition writes its changed records **and** its events in a single SQLite
transaction, so state and audit cannot drift apart.

`commit` refuses more than it stores: stale or skipped revisions, cross-run writes,
duplicate writes in one transaction, a mutation without a matching event, an event
describing an unwritten revision, a snapshot that fails validation, an initial record in a
non-initial lifecycle state, and any update that would edit an immutable field — a reviewed
`Result`, a `ReviewRecord`, a `Role`, a `TerminalReport`, an admitted `TaskRequest`,
assignment provenance, propagation decisions, message content, or a run's acceptance
criteria.

Persistence offers inspection, not resumption. `_open_run` refuses to adopt a run with
unfinished assignments: there is no automatic crash resume, and saying so is part of the
contract. `repository.runs()` indexes the database for the CLI; `repository.inspect(run_id)`
returns the records, the events and the terminal status.

## Execution

`execution.execute` is the whole seam between the host and a model. It receives an already
built context, the role, the provider, the tool registry, a shared budget and a durable
audit sink; it returns **drafts only**.

Inside it: budget reserved before dispatch, the request event written before the call, tool
calls preflighted as a batch and validated against their schemas before any of them runs,
recorded arguments canonicalised by the host, one bounded schema repair, and hard limits on
context size, output size, tool-argument size and call count. Provider errors are normalised
to a closed set of codes. The transcript never leaves this function.

`output.py` parses the returned envelope into draft types that have no authoritative fields:
a draft cannot set a status, an identity, an assignee, run state, or `verified` evidence,
and it cannot cite a tool result the host did not record.

## Controller

`controller.ControllerCore` owns identity generation, transactions, scheduling and the
execution seam. It selects a task deterministically, checks admissibility, chooses a role
and a compatible agent, builds a bounded context, pins everything the assignment relied on
— records and revisions, criterion and tool hashes, the context hash — and only then
dispatches. When output returns, `admission.check_assignment_admissibility` re-validates it
against current state, so a late or superseded result is rejected rather than merged.

`circulation.Circulation` adds the methods that move knowledge rather than work:
cross-pollination, retraction, consolidation, cycle accounting and branch stopping. None of
them spends a provider request.

`engine.WorkEngine` is the loop that drives admitted work to quiescence, with four hooks and
no opinion about whether the run is finished. `orchestration.WorkController` layers the run
workflow over it. The Stage-4/5/6 suites run the engine directly; that is what makes "the
state machine coordinates the services, it does not replace them" checkable.

## Communication

Message delivery is targeted: `agent:<id>`, `group:<id>` or `orchestrator`. There is no
broadcast recipient and no global chatroom. `messaging.route_message` records a membership
snapshot at delivery, and `scope.py` decides disclosure, failing closed.

`context.ContextBuilder` constructs every assignment's view: at most eight validated
findings, four candidate summaries, five messages, three failed approaches and three
propagations, within 24,000 characters, with every selection, omission and reason recorded.
Host-assigned evidence is admitted first and indispensable content is never silently
truncated — context construction fails with a reason instead. A contested finding is never
admitted without its conflict peers, so no assignment sees one side of an open conflict
presented as agreed.

## Knowledge and verification

This is the epistemic boundary, and it is the point of the project.

`review.py` schedules criticism and validation as controller-authored tasks. A finding is
critiqued by an identity that is not its author, then validated by an identity that is
neither the author nor the critic — decided before a provider request is spent.

`verification.py` is the only writer of `verified` evidence. A policy is keyed by the
criterion's `verifier_kind` and reads the authoritative recorded tool arguments and result.
`ArithmeticVerification` checks that the operands are the claim's own operands and that the
recorded output states they match; a successful call over other numbers proves nothing. An
unsupported claim form is `INCONCLUSIVE`, never guessed, and `VerificationRegistry` fails
closed on a verifier kind it does not implement.

`review._settle` combines the reviewer's decision with the host verdict, and the host can
only lower the outcome. A model `PASS` is necessary and never sufficient.

`knowledge.py` projects shared state, consolidates duplicates by exact claim plus evidence
*content* signature, opens conflicts on incompatible structured values or declared
contradictions, and invalidates transitively when support stops standing. Consolidation is
deterministic and costs no provider request.

## Propagation

`propagation.py` implements one replaceable interface: one validated fact in, a bounded set
of target tasks out. Eligibility requires the finding to be validated with valid
dependencies and not already delivered at that revision. Relevance scores +4 for an explicit
dependency, +2 for a shared criterion and +1 per shared tag capped at two, requiring at
least 2; at most three targets are selected, ordered by score, priority then id.

The payload is a bounded insight composed by the host from an already-validated claim —
never evidence, tool arguments or another branch's history. Delivery is idempotent against a
stored `(kind, knowledge_key, revision, target_task_id)` key, and a running assignment's
snapshot is never mutated. Invalidation sends a targeted retraction to exactly the targets
that received the knowledge.

A delivery *requests reconsideration*; it never proves the receiving branch wrong. A worker
may answer `APPLIED`, `NO_CHANGE` or `FOLLOW_UP_REQUESTED`; silence is recorded by the host
as `UNREPORTED`, never read as agreement.

`cycles.py` bounds re-exploration. A wave is charged against `cycle_limit` only when it is
opened *with* admitted executable work. Branch progress is a digest over what a branch
actually changed, so a duplicate claim, a reworded claim with the same signature, a repeated
`NO_CHANGE` and a redelivered propagation all leave it untouched. A branch that stops moving
it is closed with a reason.

## Run workflow

```text
RECEIVED → DECOMPOSING → EXPLORING → EVALUATING → CONSOLIDATING
                             ↑            ↓
                             └────────────┤
                                          ↓
                                    SYNTHESIZING ⇄ CONSOLIDATING
                                          ↓
                                    FINAL_REVIEW
                                     ↓    ↓    ↓
                              COMPLETED  SYNTHESIZING  EXPLORING
```

Two guards protect every step: `domain.RUN_TRANSITIONS` refuses an illegal step, and
`workflow.GUARDS` refuses a legal step whose precondition does not hold. `workflow.check`
also refuses any non-terminal step on a stopped or expired run.

`completion.evaluate_gate` computes readiness as a pure function of one snapshot. Every
required criterion needs currently validated, host-verified, dependency-valid support that
no open conflict contests and no unresolved blocking critique touches; no required review or
branch work may be outstanding; and enough provider budget must remain for one synthesis and
one final review. The decision is `READY`, `NOT_READY` or `EXHAUSTED`, always with reasons.

`synthesis.py` authors the synthesis task, choosing the support itself; the synthesizer
cannot create a finding, request work or answer a delivery. Its citations must be knowledge
it was given and still valid, and its criterion coverage is recomputed from the findings it
actually cited, so a declaration cannot manufacture support.

`finalreview.py` dispatches an independent reviewer — a different identity from every
synthesizer in the run — pinned to one exact result version. `PASS` is re-checked against
current state before `COMPLETED` is written, in the same transaction that accepts the
result. `REVISE` is classified from the record, not from the reviewer's wording: presentation
when current knowledge already supports every required criterion, evidence otherwise, and
`NONE` when the complaint locates nothing the record confirms. Repair work is
controller-authored and bounded by cycle, round, task, budget, capacity and duplicate checks,
and every refusal is recorded with its reason.

A reviewed result version is never edited. A revision creates a new version naming the one
it supersedes.

**Generic worker `TaskRequest` adoption remains closed.** Models may propose one; an admitted
request stays an inert proposal. All new schedulable work comes from narrow controller-owned
factories: review, reconsideration, follow-up, repair, synthesis and final review.

## Configuration and surface

`scenario.py` is the only way a run enters from outside. It validates fail-closed and
refuses rather than repairs: unknown fields, unsupported schema version, unsupported
verifier kind, unknown criterion/group/dependency, dependency cycles, duplicate identities,
impossible permissions, invalid limits, unknown provider kinds, and any task kind the
controller alone may author. Its fields carry the names of the record fields they fill, so
JSON and Python describe a run in one vocabulary.

`runner.execute_scenario` seeds the records and hands them to `WorkController`. There is no
CLI-only orchestration path.

`inspection.py`, `timeline.py` and `metrics.py` project persisted state into structured
reports; `render.py` renders them. Every fact they present is a stored decision, so
provenance is reconstructed rather than narrated. Provider transcripts are absent, context
payloads are represented by their hash and their selected/omitted identities, and the trace
prints only allowlisted event fields.

`evaluation.py` checks architectural properties across the packaged scenarios and fails
closed on an expectation it does not recognise.

## Where the limits are

The system's honesty rests on one thing: `verifier_kind`. A criterion whose kind has no
registered policy can never reach validated knowledge, so a run declaring it would exhaust
correctly and uselessly — which is why such a scenario is refused before it starts.

The shipped policy is arithmetic. Extending the system to a domain means writing a
verification policy that can say what that domain's evidence establishes. Everything else —
scheduling, review, circulation, gating, synthesis, review independence, terminal
semantics — is domain-independent and already in place.
