# Stage 6 checkpoint — propagation, reconsideration, cycling and branch stopping

Implemented only the Stage-6 authorization: making validated discoveries useful outside the
branch that found them, without turning the swarm into a broadcast network.

```text
validated finding → deterministic relevance → named targets → compact propagation
                  → reconsideration → controller-authored work when justified
                  → criticism + validation → consolidation → repeat, bounded
```

The central rule is **propagate discoveries, not transcripts**. Nothing here creates
knowledge: propagation *consumes* the Stage-5 validated projection. A PROPOSED or CRITIQUED
claim, a confident model, a critic PASS and a validator's model PASS are all still short of
shared validated knowledge, and none of them can be propagated as knowledge.

Synthesis, final review, the final-result repair loop, the complete run state machine, the
production CLI, real providers, embeddings, learned routing, distributed workers, UI and
crash resume remain unimplemented.

## 1. Preserving the Stage-5 epistemic boundary

Propagation reads three things and writes none of them: `Finding.status`, the transitive
dependency closure, and `SwarmState.validated_findings`. There is no path from a propagation
to a finding's status, and `Propagation` carries no evidence at all — only a bounded insight
string the host composed from an already-validated claim.

The one new worker-reachable field in the whole stage is `ReconsiderationDraft`, which names
a delivery and returns one of three outcomes. It cannot create a finding, promote one, reach
another branch's delivery, or report the host-only `UNREPORTED`.

## 2. Propagation eligibility

`propagation.knowledge_units` is the eligibility policy. A fact is eligible when **all** of:

- its canonical representative is currently `VALIDATED`;
- every finding in its transitive dependency closure is `VALIDATED`;
- it is present in `SwarmState.validated_findings` — the projection, not merely the status;
- it is not contested by an open conflict (§8 below);
- the run is not stopped and its deadline has not passed.

`REJECTED`, `INVALIDATED` and `SUPERSEDED` are excluded by the status check; a superseded
claim is additionally absent from the projection.

### Propagation identity under consolidation

Stage 5 revealed that "a finding became VALIDATED" and "the canonical projection changed"
are different events. Stage 6 therefore does **not** use a `newly_promoted` boolean. A
propagation names three separate things:

| field | meaning |
|---|---|
| `knowledge_key` | the *fact*: the consolidation duplicate signature, `digest(normalized claim, evidence signature)` |
| `knowledge_revision` | the canonical representative's revision at decision time |
| `canonical_finding_id` | which record represented the fact when the decision was taken |
| `source_finding_ids` | every validated member of the duplicate group — full provenance |
| `state_revision` | the `SwarmState` revision the decision was read from |
| `cycle` | the wave the decision belongs to |

So the audit answers *what exact knowledge change caused this propagation* by naming the
fact, its revision, the record that represented it, and the projection revision it came from.

Choosing the duplicate signature rather than the canonical id as the identity matters. The
canonical representative is "highest status, then lowest id", so validating a second copy of
the same claim with a lower id would change the representative. Keyed on the canonical id,
that would look like new knowledge and redeliver one fact; keyed on the signature, it is
correctly recognised as the same fact and delivered once. `test_duplicate_findings_do_not_
cause_a_second_delivery` pins both halves.

## 3. Relevance and target selection

`propagation.relevance` is the architecture's scoring rule, unchanged in weights:

```text
+4  explicit dependency  — the source task is in the target's dependency_ids, or a group
                           member is in the target's required/candidate finding ids
+2  shared acceptance criterion
+1  per shared controlled tag, capped at +2
    minimum score 2, maximum 3 targets
```

Every clause records the feature that produced it (`DEPENDENCY:ta`, `CRITERION:c1`,
`TAG:sums,integers`), and those strings are stored on the record, so a score is never an
unexplained number.

Target eligibility, in `candidate_targets`:

- same run; task status `PENDING`, `READY`, `RUNNING` or `COMPLETED` — never terminal;
- the owning group exists and is `ACTIVE`; a `COMPLETED` task is a target only inside a
  branch that is still open, because only there can reconsideration happen;
- never a review task — review work is host-assigned against one exact target, and a
  delivery there would be noise against the independence the target is being reviewed for;
- never work already authored to consume this same fact (`_already_carries`), which is what
  stops one discovery from fanning out through the tasks created to receive it;
- outside the source branch, unless there is an explicit declared dependency, which is
  local routing rather than cross-pollination.

Sorting is `score` descending, then task `priority` descending, then the stable task id, and
the first three are taken. The whole path is a pure function of the snapshot: verified as one
distinct result across **8 `PYTHONHASHSEED` values × 3 insertion orders**.

`PropagationPolicy` carries the thresholds, so a semantic router replaces the policy without
touching the `Propagation` record, its delivery key, the context section or any consumer.

## 4. No broadcast

There is no broadcast recipient and no new addressing scheme. Each `Propagation` names
exactly one `target_task_id`, and the count per fact is capped by policy. The cap is enforced
in `select_targets` and tested through both the service and the controller.

Deliveries deliberately do **not** reuse `Message`. A `Message` carries a summary and
reference ids; it cannot carry the score, the matched features, the knowledge revision or the
reconsideration outcome, so decision provenance would be lost — and routing a message that
references another branch's finding would require weakening the Stage-4
`REFERENCE_OUT_OF_SCOPE` rule. A first-class record keeps both the provenance and the
privacy boundary intact.

## 5. The propagation record

`Propagation` is immutable in its decision and mutable only in its delivery lifecycle;
`persistence._validate_update` enforces exactly that, and the recorded outcome and the
follow-up links are write-once.

```text
SELECTED ─┬─> DELIVERED ─┬─> CONSUMED ──> RETRACTED
          │              ├─> SKIPPED
          │              └─> RETRACTED
          ├─> SKIPPED
          └─> RETRACTED
```

The record reconstructs the full decision: source fact and revision, canonical
representative, every source finding, target task and group, score, matched features, reason,
delivery status, projection revision, cycle, creation time, the conflict or prior delivery it
concerns, the reconsideration outcome with its reason and the assignment that gave it, and
the controller-authored task it produced.

### Idempotency is stored, not queried

```text
delivery_key = digest(kind, knowledge_key, knowledge_revision, target_task_id)
```

`plan_propagations` skips any key already present, and `invariants._check_singletons`
**refuses to commit a snapshot containing two propagations with the same delivery key**. So
idempotency is a canonical invariant rather than a best-effort filter: a duplicate cannot be
stored even if a caller tried. A genuinely new knowledge revision produces a different key and
may propagate to the same target again.

## 6. Compact payload

`MAX_INSIGHT = 800` characters, whitespace-normalised and truncated with a marker. The
insight is composed by the host from the already-validated claim:

```text
INSIGHT     VALIDATED <finding>@<rev>: <claim>
CONFLICT    OPEN CONFLICT <id> (<kind>): <reason>. Contested claims: <id>@<rev> <claim>; …
RETRACTION  RETRACTED <finding>@<rev> is now <status>: <reason>. It was delivered to
            <task> as <propagation>. Do not rely on it.
```

No evidence, no tool arguments, no transcript, no unrelated findings, no branch history.
`test_the_delivery_carries_the_insight_and_not_the_other_branch_evidence` asserts that the
receiving context contains no `tool_result` or `arguments_json` anywhere in its propagation
section.

## 7. Delivery semantics

| target state | behaviour |
|---|---|
| `PENDING` / `READY` | delivered immediately; the next assignment for that task reads it and owes an outcome |
| `RUNNING` | stays `SELECTED`. The running assignment's snapshot is never amended |
| `COMPLETED`, branch open | becomes a controller-authored `reconsideration` task that carries the delivery |
| `FAILED` / `CANCELLED` / branch closed | `SKIPPED` with the reason recorded |

Stage-4 snapshot semantics are untouched: a propagation is pinned into
`Assignment.propagation_ids`/`propagation_revisions` at context construction and nowhere
else. Nothing is injected into an assignment that did not start with it, and every recorded
outcome comes from an assignment that had the delivery pinned from the start.

## 8. Conflicts and propagation

The explicit rule is: **a contested claim never propagates as uncontested knowledge; the
conflict propagates instead.** This mirrors the Stage-5 context invariant that a validated
finding is never presented without every open conflict it participates in.

One `CONFLICT` propagation is emitted per open conflict — not one per participant — keyed on
the conflict signature, carrying both sides' claims and the reason. Neither side is silently
chosen, and the target learns that a contradiction exists. When the conflict resolves, the
`CONFLICT` delivery is retracted and the surviving validated claims become ordinary
`INSIGHT` facts again, which is itself a reconsideration trigger; a resolved conflict also
counts as branch progress.

## 9. Reconsideration

A delivery is a request to reconsider, never proof that the receiving branch is wrong. The
closed outcome set is:

| outcome | meaning | source |
|---|---|---|
| `APPLIED` | the discovery materially changes the branch's next action | worker |
| `NO_CHANGE` | considered, with a concrete reason the existing work stands | worker |
| `FOLLOW_UP_REQUESTED` | a bounded question worth investigating | worker |
| `UNREPORTED` | the assignment returned no answer for a delivery it owed one for | **host only** |

Silence is never read as agreement. `outcomes._consume` settles every consumable delivery
the assignment pinned; an unanswered one is recorded `UNREPORTED` with an explicit reason,
emits `RECONSIDERATION_COMPLETED`, and creates no follow-up work. `parse_output` refuses
`UNREPORTED` from a model outright, and refuses two answers for one delivery.

Every outcome is linked to the delivery that caused it and to the assignment that gave it.
A failed assignment consumes nothing.

## 10. Controller-authored reconsideration work

Worker `TaskRequest` adoption stays closed. Stage 6 opens one narrow, controller-owned path,
built the way `review.review_task` was: `propagation.follow_up_task` is the only writer of
`Task.source_propagation_id`, and it is called only from `WorkController._open_cycle`.

`admissible_follow_up` must return `None` first, checking that:

- the run is live and within its deadline;
- the knowledge is still current — the fact is still VALIDATED at the recorded revision, or
  the conflict is still open (a retraction is exempt, since its whole subject is knowledge
  that stopped being current);
- the target task exists and its branch is still open;
- the task limit permits another node;
- provider budget remains;
- no equivalent work already exists — the same fact reaching the same target as the same
  kind of task, whichever propagation carried it.

The created task has an explicit parent (`parent_task_id` = the target), inherits the
target's group, criteria (intersected with the fact's) and tools, and is marked
`required=False` with `priority=1`. It creates no dependency edges, so the DAG stays acyclic
by construction and `validate_records` confirms it. Every refusal is recorded as
`PROPAGATION_SKIPPED` with its reason.

`TaskDraft` still has no propagation, finding or kind fields, `parse_output` rejects those
names, and an admitted `TaskRequest` still becomes nothing.

## 11. Cycles

A `Cycle` record holds the number, trigger, trigger ids, reason, admitted task ids, the
unresolved triggers it could not admit, status and timestamps. `Run.cycle` tracks the current
number and `Run.cycle_limit` bounds it at the architecture's default of **3 waves including
the initial one**. At most one cycle is open per run and numbers are unique — both are
snapshot invariants.

Cycle one is the initial exploration wave, opened by `_open_run`. A later wave opens only
through `_advance_cycle`, and only when the controller can actually admit bounded work:

```text
triggers = undeliverable propagations  (NEW_KNOWLEDGE / RETRACTION → reconsideration task)
         + consumed FOLLOW_UP_REQUESTED without a task  (FOLLOW_UP_REQUESTED → follow_up task)
```

Since each trigger is consumed permanently when its task is created, and the wave count is
bounded, the loop terminates twice over. A wave never opens on "keep investigating": there is
no path from model text to a trigger.

Re-entering a settled run counts as a wave and is refused once the limit is spent, so the
bound cannot be escaped by calling `run_until_idle` again.

**Coverage loss is recorded, not used as a trigger.** `cycles.coverage_gaps` reports every
criterion without clean coverage, classified `CONFLICTED`, `COVERAGE_LOST` (validated support
was invalidated) or `UNSUPPORTED`, and emits `COVERAGE_GAP`. Naming the work that would
repair a gap needs the synthesis gate, which is Stage 7; manufacturing a wave for it here
would be a guess.

## 12. No-progress detection

Progress is measured, never asserted. `cycles.measure_branch` digests five components over a
branch's own findings:

1. the set of **consolidation duplicate keys** among its known claims;
2. its **validated** finding ids;
3. the references of **host-verified evidence** on reviews of its findings;
4. the **resolved conflicts** touching its findings;
5. its criteria's **coverage** — supporting count and clean flag.

The signature changes, so progress is recorded, for: a new nonduplicate candidate, a new
validated finding, newly verified evidence, a resolved conflict, and materially changed
criterion coverage. It does not change for: an exact duplicate, a reworded claim that maps to
the same deterministic duplicate signature, a repeated `NO_CHANGE`, a redelivered
propagation, or another model agreeing without evidence — none of those touch any component.

Each cycle boundary folds the measurement into the branch: `idle_cycles` resets to 0 on
change and increments otherwise, and `BRANCH_PROGRESS` records the measurement, the previous
signature and the decision, so *why* a branch counted as making or not making progress is
inspectable rather than inferred.

## 13. Branch stopping

`cycles.branch_stop_reason` returns the first applicable reason:

| reason | when |
|---|---|
| `CANCELLED` | the run itself stopped |
| `NO_PROGRESS` | `idle_cycles >= Run.no_progress_limit` (default 2) |
| `CYCLE_LIMIT` | the wave limit is spent and an unadmitted trigger targets this branch |
| `SUPERSEDED` | every claim it still holds is a duplicate represented in another branch |
| `CRITERION_COVERED` | all its criteria have clean coverage |
| `BUDGET_LIMIT` / `DEPENDENCY_FAILED` / `ATTEMPT_LIMIT` | attributed from its own failed task outcomes |

Only the first three cancel work that is still open. `SUPERSEDED` and `CRITERION_COVERED`
stop *redundant open work*; the outcome-derived reasons are recorded once nothing is running.
A branch that simply finished its work with nothing left open is not closed — it has no
dormant work to stop, and closing it would only remove the host's ability to extend it.

Stopping a branch cancels only that branch's `PENDING`/`READY` tasks, closes the group with
`stop_reason`, and emits `BRANCH_TERMINATED` naming the cancelled tasks and the validated
findings the branch keeps. Independent branches are untouched, accepted knowledge stays in the
projection, and a closed group cannot reopen (there is no `CLOSED → ACTIVE` transition). A
group carrying a `stop_reason` while still `ACTIVE` is refused at commit.

## 14. Targeted retraction

Stage 5 left the payload; Stage 6 adds the routing. `propagation.retractions` walks the
stored deliveries — not the event log, and not a re-derivation of consumers — and for each
one whose knowledge is no longer carried:

- transitions it to `RETRACTED` with the reason;
- if it had actually been received (`DELIVERED` or `CONSUMED`), emits a `RETRACTION`
  propagation to **that same target**, naming the finding, the invalidated revision, the
  current status, the reason and the delivery it retracts.

A delivery that was never received is closed silently — nothing to retract. Targets that never
received the knowledge are never told. The retraction's delivery key is derived from the
retracted delivery's own key, so repeating `retract()` creates nothing further. Because a
delivery is pinned to `knowledge_revision`, retracting an old revision leaves a newer valid
delivery of the same fact alone.

A retraction is controller-authored: it has no author assignment, and no worker envelope can
produce one.

## 15. Retraction consequences

All reuse of existing mechanisms, with no parallel path:

- **future context** — an invalidated finding leaves `SwarmState.validated_findings`, so
  `select_validated` cannot reach it, and a `RETRACTED` propagation is not selected either;
- **in-flight staleness** — retraction moves the propagation's revision, so an assignment
  pinned to it is rejected `PROPAGATION_CHANGED`, exactly as Stage 4 rejects a changed
  finding pin with `INPUT_FINDING_CHANGED`;
- **dependent knowledge** — Stage-5 transitive invalidation is unchanged;
- **reconsideration** — the retraction is consumed like any delivery and reports an outcome;
- **criterion gaps** — `coverage_gaps` reports the criterion as `COVERAGE_LOST` and
  `COVERAGE_GAP` records it.

The full chain is traceable: `F validated → propagated to T → T consumed it → F invalidated →
retraction delivered to T → T applied it`, and §19 shows it end to end.

## 16. Reviewer resource prioritization

Stage 5 established that one finding consumes three distinct identities, so the independence
pool is a real resource. Stage 6 adds `policies.reserved_for_review`, a deliberately small
rule rather than a resource optimizer:

- required work and review work reserve nobody and are never deprioritized;
- for optional work, each **already-dispatchable** due review reserves one eligible idle
  identity, and the optional task may not take those.

Restricting the reservation to reviews that pass `ready_decision` and have an eligible agent
is what prevents a deadlock: a review that will never run reserves nobody. Because reviews
carry priority 5, reconsideration 1 and exploration 0, review work is also dispatched first
within a pass, so the reservation only has to cover the case where a lower-priority task
would otherwise take the last independent reviewer.

## 17. Budgets

Routing is free: `propagate()` and `retract()` make **zero** provider requests, asserted with
a provider that raises if called. Controller-authored work consumes ordinary assignment
budget through the ordinary path, and because reconsideration and follow-up tasks are
`required=False`, `BudgetPolicy.admit` already subordinates them to every pending required
task — the Stage-4 mechanism, not a new one. Run-level counters remain authoritative; the
in-process `Budget` stays a mirror. Whole-workflow reservation for synthesis and final review
is still deferred to the stage that owns them.

## 18. Events

Added: `PROPAGATION_SELECTED`, `CROSS_POLLINATION`, `PROPAGATION_DELIVERED`,
`PROPAGATION_SKIPPED`, `PROPAGATION_RETRACTED`, `RETRACTION_DELIVERED`,
`RECONSIDERATION_STARTED`, `RECONSIDERATION_COMPLETED`, `CYCLE_STARTED`, `CYCLE_COMPLETED`,
`BRANCH_PROGRESS`, `BRANCH_TERMINATED`, `COVERAGE_GAP`.

Propagation events carry the knowledge key and revision, the canonical finding, every source
finding, the target task and group, the score, the matched features, the projection revision,
the cycle and the reason, and correlate on the delivery key. Branch events carry the full
measurement. The information-flow graph is reconstructible from the log alone.

## 19. Stage-6 integration trace

Branch A validates `sum([1, 2, 3]) = 6`. Branch B (shares criterion `c1`) and branch C
(shares nothing) are then opened. Sequence numbers are the per-run event sequence.

```text
  18  CYCLE_STARTED            wave 1 INITIAL 
  40  TASK_CREATED             criticism criticism
  57  TASK_CREATED             validation validation
  74  FINDING_VALIDATED        
  75  KNOWLEDGE_PROMOTED       
  80  BRANCH_PROGRESS          ga progress=True idle=0
  81  CYCLE_COMPLETED          wave 1 INITIAL 
  88  CYCLE_STARTED            wave 2 INITIAL 
  91  PROPAGATION_SELECTED     INSIGHT -> tb score=2 CRITERION:c1 score 2 from CRITERION:c1
  92  CROSS_POLLINATION        INSIGHT -> tb score=2 CRITERION:c1
  93  PROPAGATION_DELIVERED    INSIGHT -> tb score=2 CRITERION:c1
 100  RECONSIDERATION_STARTED  ['r:propagation:000002']
 124  RECONSIDERATION_COMPLETED FOLLOW_UP_REQUESTED on tb: the combined total needs rechecking
 134  TASK_CREATED             criticism criticism
 135  TASK_CREATED             criticism criticism
 169  TASK_CREATED             validation validation
 170  TASK_CREATED             validation validation
 202  FINDING_VALIDATED        
 203  KNOWLEDGE_PROMOTED       
 214  PROPAGATION_SELECTED     INSIGHT -> ta score=2 CRITERION:c1 score 2 from CRITERION:c1
 215  CROSS_POLLINATION        INSIGHT -> ta score=2 CRITERION:c1
 216  BRANCH_PROGRESS          ga progress=True idle=0
 217  BRANCH_PROGRESS          gb progress=True idle=0
 218  BRANCH_PROGRESS          gc progress=True idle=0
 219  CYCLE_COMPLETED          wave 2 INITIAL 
 220  CYCLE_STARTED            wave 3 NEW_KNOWLEDGE 
 222  TASK_CREATED             reconsideration NEW_KNOWLEDGE
 223  RECONSIDERATION_STARTED  NEW_KNOWLEDGE
 224  TASK_CREATED             follow_up FOLLOW_UP_REQUESTED
 225  RECONSIDERATION_STARTED  FOLLOW_UP_REQUESTED
 227  PROPAGATION_DELIVERED    INSIGHT -> ta score=2 CRITERION:c1
 234  RECONSIDERATION_STARTED  ['r:propagation:000021']
 249  RECONSIDERATION_COMPLETED FOLLOW_UP_REQUESTED on ta: the combined total needs rechecking
 258  BRANCH_PROGRESS          ga progress=False idle=1
 259  BRANCH_PROGRESS          gb progress=False idle=1
 260  BRANCH_PROGRESS          gc progress=False idle=1
 261  CYCLE_COMPLETED          wave 3 NEW_KNOWLEDGE ['r:task:000023', 'r:task:000024']
 262  CYCLE_STARTED            wave 4 FOLLOW_UP_REQUESTED 
 264  TASK_CREATED             follow_up FOLLOW_UP_REQUESTED
 265  RECONSIDERATION_STARTED  FOLLOW_UP_REQUESTED
 279  BRANCH_PROGRESS          ga progress=False idle=2
 280  BRANCH_PROGRESS          gb progress=False idle=2
 281  BRANCH_PROGRESS          gc progress=False idle=2
 282  CYCLE_COMPLETED          wave 4 FOLLOW_UP_REQUESTED ['r:task:000028']
 283  FINDING_INVALIDATED      FIXTURE_CORRECTION
 284  KNOWLEDGE_REMOVED        FIXTURE_CORRECTION
 286  PROPAGATION_RETRACTED    INSIGHT -> tb score=2 CRITERION:c1 FIXTURE_CORRECTION
 287  PROPAGATION_SELECTED     RETRACTION -> tb score=2 CRITERION:c1 retracts r:propagation:000002: FIXTURE_C
 288  CYCLE_STARTED            wave 5 INITIAL 
 290  BRANCH_PROGRESS          ga progress=True idle=0
 291  BRANCH_PROGRESS          gb progress=True idle=0
 292  BRANCH_PROGRESS          gc progress=False idle=3
 293  CYCLE_COMPLETED          wave 5 INITIAL 
 294  CYCLE_STARTED            wave 6 RETRACTION 
 296  TASK_CREATED             reconsideration RETRACTION
 297  RECONSIDERATION_STARTED  RETRACTION
 299  RETRACTION_DELIVERED     RETRACTION -> tb score=2 CRITERION:c1
 305  RECONSIDERATION_STARTED  ['r:propagation:000030']
 310  RECONSIDERATION_COMPLETED APPLIED on tb: dropped the retracted total from this branch
 314  BRANCH_PROGRESS          ga progress=False idle=1
 315  BRANCH_PROGRESS          gb progress=False idle=1
 316  BRANCH_PROGRESS          gc progress=False idle=4
 317  BRANCH_TERMINATED        NO_PROGRESS keeps []
 319  CYCLE_COMPLETED          wave 6 RETRACTION ['r:task:000006']
```

```text
propagations
  r:propagation:000002   INSIGHT     -> tb     score=2 RETRACTED  outcome=FOLLOW_UP_REQUESTED
      key=e7cf102aa71709b4… rev=3 features=['CRITERION:c1'] state_rev=5 cycle=2
  r:propagation:000021   INSIGHT     -> ta     score=2 CONSUMED   outcome=FOLLOW_UP_REQUESTED
      key=2e64a29253d0530b… rev=3 features=['CRITERION:c1'] state_rev=11 cycle=2
  r:propagation:000030   RETRACTION  -> tb     score=2 CONSUMED   outcome=APPLIED
      key=e7cf102aa71709b4… rev=3 features=['CRITERION:c1'] state_rev=5 cycle=4

cycles
  1  CLOSED  INITIAL              tasks=[] unresolved=[]
  2  CLOSED  INITIAL              tasks=[] unresolved=[]
  3  CLOSED  NEW_KNOWLEDGE        tasks=['r:task:000023', 'r:task:000024'] unresolved=[]
  4  CLOSED  FOLLOW_UP_REQUESTED  tasks=['r:task:000028'] unresolved=[]
  5  CLOSED  INITIAL              tasks=[] unresolved=[]
  6  CLOSED  RETRACTION           tasks=['r:task:000006'] unresolved=[]

branches
  ga  ACTIVE  stop=None idle_cycles=1
  gb  ACTIVE  stop=None idle_cycles=1
  gc  CLOSED  stop=NO_PROGRESS idle_cycles=4

tasks
  r:task:000005          criticism        COMPLETED  grp=None  from=None
  r:task:000006          reconsideration  COMPLETED  grp=gb    from=r:propagation:000030
  r:task:000008          validation       COMPLETED  grp=None  from=None
  r:task:000009          criticism        COMPLETED  grp=None  from=None
  r:task:000010          criticism        COMPLETED  grp=None  from=None
  r:task:000015          validation       COMPLETED  grp=None  from=None
  r:task:000016          validation       COMPLETED  grp=None  from=None
  r:task:000023          reconsideration  COMPLETED  grp=ga    from=r:propagation:000021
  r:task:000024          follow_up        COMPLETED  grp=gb    from=r:propagation:000002
  r:task:000028          follow_up        COMPLETED  grp=ga    from=r:propagation:000021
  ta                     exploration      COMPLETED  grp=ga    from=None
  tb                     exploration      COMPLETED  grp=gb    from=None
  tc                     exploration      COMPLETED  grp=gc    from=None

findings
  r:finding:000004       INVALIDATED  sum([1, 2, 3]) = 6
  r:finding:000006       VALIDATED    sum([10, 20]) = 30
  r:finding:000007       CRITIQUED    sum([7, 7]) = 14

shared state    validated=['r:finding:000006'] invalidated=['r:finding:000004']
budgets         provider_requests=19 tool_calls=6
cycle           6 of 7
```

## 20. Verification

299 unittest tests pass with 0 failures in three environments:

| Environment | Result |
|---|---|
| CPython 3.13.5, from source (`PYTHONPATH=src`) | 299 passed |
| CPython 3.11.9, from source — the declared `requires-python` floor | 299 passed |
| `swarm_foundations-0.4.0-py3-none-any.whl`, installed into a clean venv with `src` off the path | 299 passed |

| File | Tests | Area |
|---|---|---|
| `tests/test_domain.py` | 15 | records, transitions, cycles, provenance, deep graphs |
| `tests/test_persistence.py` | 12 | SQLite atomicity, revisions, update rules |
| `tests/test_execution.py` | 21 | bounded execution seam, hostile output, budgets |
| `tests/test_audit_integration.py` | 2 | durable counters across executions |
| `tests/test_stage4_services.py` | 27 | routing, context, readiness, admissibility, disclosure scope |
| `tests/test_stage4_controller.py` | 23 | controller scheduling, staleness, privacy, budgets, cancellation |
| `tests/test_stage5_verification.py` | 26 | claim entailment, consolidation, conflicts, supersession, invalidation |
| `tests/test_stage5_review.py` | 37 | review planning, independence, admissibility, review contracts, context |
| `tests/test_stage5_controller.py` | 28 | end-to-end review, promotion atomicity, invalidation, conflicts |
| `tests/test_stage6_propagation.py` | 27 | relevance, eligibility, target selection, idempotency, conflicts, no broadcast |
| `tests/test_stage6_reconsideration.py` | 22 | delivery semantics, context provenance, outcomes, follow-up authority |
| `tests/test_stage6_controller.py` | 33 | retraction, cycles, branch progress and stopping, resource integrity, integration |
| `tests/test_stage6_guards.py` | 26 | guards a first mutation battery showed were untested |

### Guards checked by mutation, not assumed

Fifty-two mutations were applied one at a time, each disabling a single Stage-6 guard.

The first battery caught 33 and **18 survived** — 18 guards that no test was actually
exercising. That is a finding, not a pass, and each was bound before being re-mutated:

- the delivery-key filter in `outcomes._consume`, so a delivery the context cap dropped is
  never settled by an assignment that did not see it;
- the pinned and the owed halves of reconsideration admission, which had been masking each
  other — one test each now isolates them;
- the reviewer refusal in admission, previously masked by the role output allowlist;
- `KNOWLEDGE_NOT_CURRENT` and `DUPLICATE_FOLLOW_UP` in `admissible_follow_up`, the latter
  reachable only when a *second* delivery carries the same fact to the same target;
- the re-entry cycle limit, reachable only when a settled run is reopened after the limit;
- the retraction-only-to-recipients rule;
- the projection-membership and VALIDATED-status halves of eligibility, which had also been
  masking each other, plus the `DELIVERED`-only rule in `for_task`;
- the validated-set and resolved-conflict components of the branch measurement, both masked
  by the coverage component until the isolating tests removed criteria from the fixture;
- five snapshot and repository invariants: consumed-implies-outcome, outcome-implies-consumed,
  follow-up-implies-FOLLOW_UP_REQUESTED, retraction-names-its-source, unique cycle numbers,
  one open cycle, propagation-decision immutability and append-only cycle work.

Two of the fifty-two were initially written as no-op mutations and were replaced with ones
that change behaviour: the `for_task` status filter (first aimed at the wrong module) and the
retraction key (the first variant was an injective re-encoding of the same tuple, so it could
not differ; the replacement makes repeated retractions produce distinct keys).

**Final battery: 52 applied, 52 caught, 0 survivors.**

### Determinism

Relevance scoring, target selection and delivery keys were run over a six-branch fixture
under eight `PYTHONHASHSEED` values and three insertion orders: **one distinct result across
all twenty-four runs** — identical targets, scores, matched features and delivery keys.

## 21. Deviations from the architecture review and the Stage-6 brief

| # | Deviation | Class |
|---|---|---|
| 1 | Record `schema_version` bumped to 3 and the SQLite `user_version` with it, so a stage-5 database is refused rather than silently reread with defaults for the new fields. Consistent with the Stage-5 precedent; there is still no migration, because persistence offers inspection and not resumption. | IMPROVEMENT |
| 2 | A propagation is a first-class `Propagation` record and **not** a `Message`. The architecture described emitting a message; a `Message` cannot carry the score, matched features, knowledge revision or reconsideration outcome, and routing one that references another branch's finding would require weakening the Stage-4 `REFERENCE_OUT_OF_SCOPE` rule. The record keeps both the decision provenance and the privacy boundary. | IMPROVEMENT |
| 3 | Idempotency is enforced as a snapshot invariant on `delivery_key`, not only as a filter in the planner. A duplicate delivery cannot be stored even by a caller that bypasses the planner. | IMPROVEMENT |
| 4 | Propagation identity is the **consolidation duplicate signature**, not the canonical finding id. Keying on the canonical id would redeliver one fact whenever a lower-id duplicate became validated and took over as representative. | IMPROVEMENT |
| 5 | A contested claim propagates as a `CONFLICT` delivery naming both sides, never as an uncontested `INSIGHT`. The brief allowed either withholding or annotating; this mirrors the Stage-5 context invariant instead of inventing a third rule. | NEUTRAL |
| 6 | Reconsideration/follow-up tasks are excluded as targets for the fact that created them (`_already_carries`). Found by running the loop: without it, a reconsideration task inherits its target's criteria, scores against the knowledge that created it, and fans one discovery out indefinitely. | IMPROVEMENT |
| 7 | `UNREPORTED` was added as a fourth, host-only outcome. The brief said not to treat silence as `NO_CHANGE`; recording it as its own outcome is stronger than leaving the delivery unsettled, and it is unreachable from a model envelope. | IMPROVEMENT |
| 8 | Coverage loss is recorded as a `COVERAGE_GAP`, not used as a cycle trigger. A trigger must name admissible work, and naming the work that repairs a coverage gap belongs to the synthesis gate in Stage 7. | NEUTRAL |
| 9 | A branch with no open work is not closed merely because its criteria are covered. `CRITERION_COVERED` and `SUPERSEDED` stop *redundant open work*; a quiescent branch has nothing dormant to stop, and closing it would only remove the host's ability to extend it. Found by a Stage-5 test that legitimately adds work to a settled branch. | NEUTRAL |
| 10 | Re-entering a settled run counts as an exploration wave and is refused once `cycle_limit` is spent. Without this the bound could be escaped by calling `run_until_idle` again. | IMPROVEMENT |
| 11 | Stage-5 behaviour changed observably: a run with two branches sharing an acceptance criterion now cross-pollinates, so more tasks and one more wave appear. Three Stage-5 tests were updated — one count assertion became a direct assertion that no worker request became a Task, and the invalidation fixture is unaffected once branch closing is correctly scoped. No Stage-5 guarantee was weakened. | NEUTRAL |
| 12 | `domain.py` was split: records, enums and transitions stay there (558 lines), and the snapshot invariants moved to `invariants.py` (311 lines). Stage 5 deferred this split; adding two record types made it necessary. `domain.validate_records` remains the public entry point. | NEUTRAL |
| 13 | `orchestration.py` is now 709 lines — the largest module, under the 800-line ceiling but the obvious next split candidate. The propagation, cycle and branch methods are cohesive enough to move together when the run state machine arrives. | RISK |
| 14 | Stage-4 design issues 1 (nothing adopts a `TaskRequest`), 2 (run workflow authority) and 5 (NEEDS_INPUT ends in FAILED) are still untouched. Stage 6 opened a *controller-owned* task factory, which is deliberately not `TaskRequest` adoption; the brief asked to keep them separate unless there was a compelling reason, and there was not. | RISK |

Nothing in the brief was skipped or narrowed. Items 13 and 14 are the only RISK entries, and
14 is a carried-forward Stage-4 risk rather than a Stage-6 decision.

## 22. What Stage 6 revealed that should influence Stage 7

1. **The synthesis gate now has almost everything it needs, and one thing it does not.**
   `knowledge.criterion_coverage` already reports per-criterion support and cleanliness, and
   `cycles.coverage_gaps` already classifies every gap as `CONFLICTED`, `COVERAGE_LOST` or
   `UNSUPPORTED`. What is missing is the *decision*: whether an unresolved gap means another
   wave, an EXHAUSTED terminal state, or a partial result. Stage 6 deliberately records the
   gap rather than guessing, so Stage 7 should consume `coverage_gaps` directly.

2. **`Run.state` is still never written.** Stage 6 added `Run.cycle` and `Run.cycle_limit` and
   left `RunState` untouched, so the run has bounded waves but no workflow. The cycle records
   are the natural spine for that state machine: each wave already knows its trigger, its
   admitted work and its unresolved remainder, which is most of what `EXPLORING → EVALUATING
   → CONSOLIDATING` would need to record.

3. **Branch stopping needs a run-level counterpart.** A branch now ends with a recorded reason
   and its knowledge preserved, but nothing decides what it means when *every* branch has
   stopped and criteria remain uncovered. That is exactly the EXHAUSTED outcome, and the
   `BRANCH_TERMINATED` reasons are the diagnostics it should carry.

4. **Reviewer reservation should become budget reservation too.** `reserved_for_review`
   protects the independence pool from optional work, but synthesis and final review need
   *provider budget* held back as well — the Stage-4 issue-6 reservation that is still open.
   The two are the same idea at different resources, and Stage 7 owns the consumer.

5. **`REVISE` and `REJECT` need the propagation machinery, not a new one.** A final review
   that finds an evidence gap must reach the branches that produced the evidence. That is a
   targeted delivery with a recorded reason to specific tasks — the `Propagation` record, a
   new kind, and the existing reconsideration outcomes. Adding a second delivery mechanism
   for review feedback would undo the concentration Stage 6 preserved.

6. **`TaskRequest` adoption is now the only unopened work path, and its shape is settled.**
   Stage 5 proved the controller can create review work safely; Stage 6 proved it can create
   reconsideration work safely, with an admissibility function, a duplicate check, a bounded
   budget and a recorded reason. Adopting a `TaskRequest` needs exactly that shape plus one
   more check — that a model's proposal names a real gap — and Stage 7's repair loop is the
   first consumer with a reason to want it.

7. **The independence pool and the wave limit interact, and the interaction is visible.** In
   the integration trace, branches reach `NO_PROGRESS` while follow-up work is still being
   admitted, because reconsideration produces answers rather than findings. Stage 7 should
   decide whether a wave that produces only `NO_CHANGE` answers ought to count against the
   wave limit at all, or whether the no-progress rule alone should end it.

8. **A run can now end with knowledge that nothing consumed.** A delivery can be `SELECTED`
   or `DELIVERED` and never answered when the run settles, and a `FOLLOW_UP_REQUESTED`
   outcome can go unadmitted at the wave limit. Both are recorded — on the propagation and in
   the closing cycle's `unresolved` — but nothing yet reports them as a run-level result.
   The terminal-outcome stage is where "we learned this and never used it" should surface.
