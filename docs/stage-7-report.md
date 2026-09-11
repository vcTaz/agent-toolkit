# Stage 7 checkpoint — synthesis gating, synthesis, final review, repair and terminal outcomes

Date: 2026-09-10. Status: implemented and verified. Supersedes nothing; extends
`docs/stage-6-report.md`.

Stage 7 answers the question Stages 1–6 deliberately left open:

```text
Do we have enough trustworthy knowledge to produce a final result?
```

and then turns the answer into a durable outcome:

```text
validated knowledge
        ↓
synthesis gate            computed, never asserted
        ↓
synthesizer               proposes one candidate answer
        ↓
candidate Result          immutable, pinned to its exact support
        ↓
independent final review  PASS / REVISE / REJECT
        ↓
COMPLETED / repair / EXHAUSTED
```

The invariant chain is unchanged at every new layer:

```text
model / executor proposes
controller decides
repository commits
```

A model never decides that a run is complete. It cannot: `RunState.COMPLETED` is reachable
only from `FINAL_REVIEW`, only through `WorkController._settle_pass`, and only in a
transaction that also writes the accepted `Result` — and `_check_run` refuses any snapshot
where one exists without the other.

---

## 1. The run state machine

`RunState` already existed and was never written. Stage 7 activates it.

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

Every active state may also end `FAILED`, `EXHAUSTED` or `CANCELLED`. The four terminal
states are **absorbing by construction**: they are absent from `RUN_TRANSITIONS`, so
`transition()` refuses every step out of them without a special case.

`domain.transition` grew a `Run` branch. That is deliberate: a run lifecycle is a lifecycle
like any other, and what makes it controller-owned is not that it lives elsewhere but that
only the controller may call it and that the *readiness predicates* guarding each step live
in `workflow` and `completion`, where they are pure functions over one snapshot.

Two guards exist per transition:

| Layer | What it refuses |
|---|---|
| `domain.RUN_TRANSITIONS` | an illegal step, wherever it comes from |
| `workflow.GUARDS` | a legal step whose precondition does not hold |

`workflow.check` also refuses any non-terminal step on a run that is stopped or past its
deadline, so no phase can advance on a dead run.

`persistence._validate_update` now calls `transition(old, new.state)` for a stored run, so a
caller that hand-builds a successor cannot skip the machine. It also makes `result_id` and
`outcome_id` write-once and refuses a change to the acceptance criteria inside a run.

### Guards

| Transition | Guard | Refusal |
|---|---|---|
| RECEIVED → DECOMPOSING | `configured` | `NO_ACCEPTANCE_CRITERIA`, `DUPLICATE_CRITERION_IDS`, `NO_REQUIRED_CRITERION`, `INVALID_LIMITS` |
| DECOMPOSING → EXPLORING | `decomposed` | `NO_TASKS` |
| EXPLORING → EVALUATING | `wave_settled` | `ASSIGNMENTS_IN_FLIGHT`, `EXPLORATION_WORK_OPEN` |
| EVALUATING → CONSOLIDATING | `reviews_settled` | `ASSIGNMENTS_IN_FLIGHT`, `REVIEW_WORK_OPEN` |
| CONSOLIDATING → SYNTHESIZING | gate decision + `synthesis_dispatchable` | `GATE_NOT_READY`, `GATE_EXHAUSTED`, `SYNTHESIS_ATTEMPT_LIMIT` |
| SYNTHESIZING → FINAL_REVIEW | `candidate_ready` | `NO_CANDIDATE_RESULT` |
| FINAL_REVIEW → COMPLETED | reviewer PASS + `pass_blockers` empty | any blocker |

The transitions out of CONSOLIDATING and FINAL_REVIEW depend on a gate decision or a review
verdict rather than on the snapshot alone, so the controller supplies those explicitly
through `workflow.advance(..., guard=...)` instead of hiding them in the guard table.

## 2. Integration with Stages 4–6, not replacement

Nothing about exploration, review or circulation was rebuilt. The state machine is a
coordinator over the existing services:

| State | What actually runs |
|---|---|
| EXPLORING | the Stage-4 scheduler, the Stage-6 cycle records, repair tasks |
| EVALUATING | Stage-5 criticism and validation, with host verification |
| CONSOLIDATING | Stage-5 consolidation and conflicts, Stage-6 propagation, reconsideration and branch stopping, then the gate |
| SYNTHESIZING | one ordinary assignment on the ordinary execution seam |
| FINAL_REVIEW | one ordinary assignment, through the ordinary independence policy |

That claim is checkable rather than a comment, because Stage 7 split the controller so the
work engine is independently runnable:

```text
ControllerCore   controller.py   scheduling, execution seam, admission, transactions
Circulation      circulation.py  cross-pollination, retraction, consolidation, cycles, branches
WorkEngine       engine.py       the loop that drives admitted work to quiescence
WorkController   orchestration.py the run workflow layered over all of it
```

`WorkEngine.run_until_idle` is the Stage-6 controller loop with four hooks — `_prologue`,
`_terminated`, `_halt`, `_settled` — that `WorkController` overrides. The Stage-4/5/6 test
suites run against `WorkEngine`; the Stage-7 suites run against `WorkController`.

## 3. The synthesis gate

`completion.evaluate_gate(snapshot, run_id)` returns a `GateDecision`:

```text
status      READY | NOT_READY | EXHAUSTED
reasons     every reason it is not READY
readiness   one CriterionReadiness per acceptance criterion
gaps        one Gap per criterion the gate refuses
repairable  the required gaps for which bounded repair is admissible
support     the validated findings a synthesis would be built from
```

It is a pure function. It commits nothing, calls no provider, and never asks a model
whether it is ready to answer. Every condition the brief listed is a computation:

| Condition | Where it is computed |
|---|---|
| every required criterion has valid support | `knowledge.criterion_coverage` |
| supporting findings remain VALIDATED | same |
| supporting dependencies remain valid | `_support_dependencies_valid` over `review.dependency_closure` |
| no unresolved blocking review issue | `_unresolved_blocking` |
| no unresolved OPEN conflict over required coverage | `Coverage.clean` |
| no required review/revalidation outstanding | `_review_outstanding` / `policies.outstanding_reviews` |
| required task/branch work settled | `_open_required_work`, `_unsettled_branch_work` |
| no unresolved required knowledge gap | `gap_records` over `cycles.coverage_gaps` |
| budget for synthesis and final review | `budget_sufficient` / `completion_cost` |
| the run is still live | `policies.stopped`, `remaining_seconds` |

One condition is stricter than the brief required: support must carry **host-verified**
evidence, not merely a passing review. `CriterionReadiness.verified_ids` reads the
`verified=True` evidence that only `verification.VerificationRegistry` can write, and a
criterion whose support has none is gapped `SUPPORT_UNVERIFIED`. This is the Stage-5
epistemic boundary carried into the gate: model agreement is not verification.

`GateStatus.EXHAUSTED` is returned when the gate is not ready *and* nothing is settling and
no required gap admits repair — that is the run-level decision Stage 6 deliberately refused
to make.

## 4. Criterion coverage

Stage 7 introduces no second coverage model. `criterion_readiness` consumes
`knowledge.criterion_coverage` for support and conflicts and `cycles.coverage_gaps` for the
`CONFLICTED` / `COVERAGE_LOST` / `UNSUPPORTED` classification, and adds only what the gate
needs on top. For every criterion it can state:

```text
criterion id · supporting validated findings · host-verified subset · open conflicts
coverage state · clean/unclean · blocking gap
```

A criterion "covered" by two contradictory validated findings is **not** clean support:
`Coverage.clean` requires `supporting_ids and not conflict_ids`, exactly as Stage 5 defined
it, and the gate inherits that unchanged.

`REVIEW_OUTSTANDING` is scoped per criterion (`_review_outstanding_for`). A finding awaiting
review elsewhere delays the whole run — the wave is not settled — but it is not *a gap in
this criterion*, and the gate says which is which.

## 5. Unresolved gaps: repair or exhaustion

`completion.repair_admissible(snapshot, run_id, gap, review_id)` is the whole decision, and
it is deterministic:

| Refusal | Meaning |
|---|---|
| `RUN_STOPPED` | the run is not live |
| `GAP_NOT_REPAIRABLE` | the gap reason names no work a repair task could do |
| `REPAIR_LIMIT` | `run.repair_rounds >= run.repair_round_limit` |
| `CYCLE_LIMIT` | `run.cycle >= run.cycle_limit` |
| `TASK_LIMIT` | the task graph is full |
| `BUDGET_EXHAUSTED` | less than the completion reserve remains |
| `DUPLICATE_REPAIR` | the same gap, from the same trigger, already has a task |
| `NO_REPAIR_CAPACITY` | no repair role is registered, or no unbranched agent is free |

`NO_REPAIR_CAPACITY` is an addition. Admitting work nothing can execute would spend an
exploration wave to arrive back at the same gap, so capacity is part of admissibility rather
than something discovered at dispatch.

Repairable gap reasons are a closed set: `UNSUPPORTED`, `COVERAGE_LOST`, `CONFLICTED`,
`REVIEW_OUTSTANDING`, `SUPPORT_DEPENDENCY_INVALID`, `BLOCKING_ISSUE_OUTSTANDING`. Anything
else — `SUPPORT_UNVERIFIED`, for instance — is a defect of the run's configuration that more
exploration will not fix.

## 6. The synthesis task

`SYNTHESIZER` is a real role executing a real assignment through the ordinary seam. What
makes it safe is what it is *given*:

- `synthesis.synthesis_task` sets `required_finding_ids = gate.support` — the controller's
  deliberate selection, transitively closed by `completion.support_findings`.
- `candidate_finding_ids = ()`, so no unvalidated claim is disclosable.
- `ContextBuilder.required_closure` raises `REQUIRED_FINDING_UNAVAILABLE` if any member has
  become INVALIDATED, REJECTED or SUPERSEDED — an invalidated claim cannot reach the answer
  even as text.
- `Task.limitations` carries the bounded caveats `completion.limitations` computed: every
  open conflict, and every optional criterion that is not cleanly supported.
- The role's `output_fields` are `('result', 'messages')`, so a synthesizer cannot create a
  finding, request work or answer a propagation.
- `propagation.candidate_targets` excludes synthesis and final-review tasks, so no delivery
  can become a second, unaudited path into the answer.

Propagation is **not** a prerequisite for use: `support_findings` offers every current
validated, criterion-relevant finding regardless of whether anything ever consumed it.

## 7. Provenance

A `Result` version records:

```text
version · answer · created_by_assignment · created_at
criterion_ids · coverage (criterion → supporting finding ids, with required flag)
finding_ids + finding_revisions   (the exact revisions it was built from)
claims (claim text → finding ids) · limitations · unresolved_issues
supersedes_id · review_id · decision · revision_kind
```

`synthesis._coverage` recomputes coverage **from the cited findings**, never from the
model's declaration: a synthesizer may say it covered `c2`, and only the findings it cited
decide whether it did. `admit_result` then refuses:

| Reason | Refused because |
|---|---|
| `RESULT_STALE` | pinned support moved while the synthesis ran |
| `RESULT_SUPPORT_MISSING` | a citation resolves to nothing |
| `RESULT_SUPPORT_NOT_IN_CONTEXT` | a citation was never supplied to this assignment |
| `RESULT_SUPPORT_NOT_VALIDATED` | a citation is not currently VALIDATED |
| `RESULT_CLAIM_UNSUPPORTED` | a claim names no finding |
| `RESULT_CLAIM_REFERENCE_NOT_CITED` | a claim names a finding the result did not cite |
| `RESULT_REQUIRED_CRITERION_UNSUPPORTED` | the citations do not cover a required criterion |
| `RESULT_UNKNOWN_CRITERION`, `RESULT_DUPLICATE_SUPPORT`, `RESULT_SIZE` | contract violations |

`_check_result` repeats the structural half as a snapshot invariant, so a hand-built record
cannot cite coverage or a claim the result did not reference.

## 8. Result versions are immutable

`Result` is a first-class `RunRecord`, not an embedded value. Storage enforces the
immutability: `_validate_update` allows only `revision`, `status`, `review_id`, `decision`
and `revision_kind` to change, and makes the verdict fields write-once. A revision creates a
**new version** naming the one it supersedes; the version the reviewer actually judged keeps
its answer, its citations and its verdict forever.

Only a version that is still a live `CANDIDATE` is *marked* `SUPERSEDED`; a version already
judged `REVISED` or `REJECTED` keeps its verdict and is named through `supersedes_id`
instead. `_check_singletons` refuses two accepted results or two versions with one number.

## 9. Candidate admission

Before `admit_result` runs at all, `check_assignment_admissibility` has re-validated the
whole Stage-4 pin set on current state, and `_check_result_proposal` has checked:

- the task kind is `synthesis` and the role is `SYNTHESIZER` (`SYNTHESIS_ROLE_MISMATCH`);
- the envelope carries no review, reconsideration, finding or task request
  (`SYNTHESIS_SCOPE_VIOLATION`);
- the declared criteria exist.

Everywhere else, `execution_result.result is not None` is refused outright as
`RESULT_PROPOSAL_FORBIDDEN` — the Stage-5 reason `LATER_STAGE_PROPOSAL_FORBIDDEN` under its
real name now that the stage has arrived.

## 10. Independent final review

`FINAL_REVIEWER` is a separate assignment on a separate task carrying `target_result_id` —
a field only `finalreview.final_review_task` writes.

Independence is decided **before** the provider request is spent. `policies.review_kind`
recognises the final-review kind, so `_schedule`'s existing pre-dispatch check applies
unchanged: `compatible_review_agents` subtracts `excluded_review_agents`, which for a final
review is `excluded_final_reviewers` — every identity that has authored *any* result version
in the run. When no independent identity exists, the task fails with a recorded
`NO_INDEPENDENT_REVIEWER` gap and the run exhausts with
`NO_INDEPENDENT_FINAL_REVIEWER`; it never falls back to self-review.

The exclusion is authorship of the answer, not of the branches whose findings it rests on.
Excluding those would collapse the reviewer pool as soon as the run produced knowledge, and
would buy no independence the Stage-5 finding reviews have not already provided.
`_check_review` repeats the rule as a snapshot invariant.

## 11. The final-review contract

The reviewer returns `PASS`, `REVISE` or `REJECT` — a closed set restricted per review kind
by `REVIEW_DECISIONS[ReviewKind.FINAL]`. It also *locates* defects with two structured
fields added to `ReviewDraft` and `ReviewRecord`:

```text
criterion_ids        criteria the review says the result fails to cover
unsupported_claims   claims it says nothing supports
```

Those are locators, not classifications. The reviewer proposes; it never mutates a Finding,
a Run or a Result — `admit_final_review` returns exactly one `ReviewRecord` and nothing
else, which the tests assert directly.

## 12. PASS semantics

PASS is necessary and never sufficient. After a passing review the controller recomputes
the gate and re-checks the citations against **current** state
(`finalreview.pass_blockers`):

```text
review starts
→ a supporting Finding is invalidated
→ reviewer returns PASS
→ pass_blockers reports SUPPORT_INVALIDATED
→ the run does not complete
```

Blockers also cover: the gate no longer READY, a supporting revision moved, a required
criterion is unsupported in the result, a required criterion is missing from the result, and
every stale reason the review itself carried. Only with **no** blockers does
`_settle_pass` write `ACCEPTED` + `TerminalReport` + `COMPLETED` in one transaction.

A stale PASS is not silently discarded: it is recorded as `RESULT_REJECTED` with its
blockers and re-enters the evidence-repair path.

## 13. REVISE semantics

The controller — not the reviewer — decides what a revision requires, because only the
controller can tell the difference from the record. `finalreview.classify`:

```text
gate not READY                     → EVIDENCE
a citation is no longer valid      → EVIDENCE
a named criterion is uncovered     → EVIDENCE
unsupported claims are named       → EVIDENCE
a named criterion is covered but the answer omits it   → PRESENTATION
only wording/organisation issues                        → PRESENTATION
nothing the record confirms                             → NONE
```

**Presentation revision** returns `FINAL_REVIEW → SYNTHESIZING` and authors a new synthesis
task carrying bounded feedback — the review's blocking and nonblocking issues and its named
criteria — through `Task.limitations` and `Task.source_review_id`. The `ContextBuilder`
serves the prior final review's issues via `review_targets`, so the synthesizer sees exactly
the review that asked for the change and nothing else.

**Evidence revision** creates controller-authored repair work and returns to EXPLORING.
Synthesis prose is never offered as a repair for missing evidence.

`RevisionKind.NONE` is the honest third case: a reviewer who disagreed but pointed at
nothing the record confirms has located nothing, and neither prose nor evidence can act on
it. The run exhausts with `NO_CONFIRMED_DEFECT`.

## 14. REJECT semantics

A rejected version is discarded as a candidate: its status becomes `REJECTED` and it is
never accepted. **No underlying finding is invalidated** — the tests assert that every
validated finding survives a REJECT and appears in the terminal report.

If the review located a defect and limits permit, REJECT creates bounded repair work exactly
as an evidence REVISE does. Otherwise the run terminates EXHAUSTED with diagnostics:
`UNREPAIRABLE_REJECT: NO_CONFIRMED_DEFECT`, `REPAIR_LIMIT after REJECT`, `CYCLE_LIMIT after
REJECT` or `NO_ADMISSIBLE_REPAIR after REJECT`.

## 15. Review feedback and the propagation mechanism — decision

The Stage-6 report suggested reusing `Propagation` for REVISE/REJECT feedback. **Evaluated
and declined**, for one concrete reason: a `Propagation` is structurally *one validated fact
routed to one task*. `_check_propagation` requires `canonical_finding_id` to resolve to a
`Finding`, and a repair request frequently has no finding at all — an `UNSUPPORTED`
criterion is precisely the case where none exists. Making that field optional would weaken
the invariant for every propagation kind in order to accommodate a record that is not a
fact.

What was reused is the *shape*, which is what the Stage-6 report was actually asking for:

| Property | How Stage 7 provides it |
|---|---|
| explicit provenance | `Task.source_review_id`, `Task.source_result_id` |
| targeted recipient | one repair task per gap, with `acceptance_criterion_ids` |
| bounded payload | `bounded(...)` description naming the gap and the current support |
| delivery identity / idempotency | `repair_key(gap, review_id)`, stored in `Task.outcome`, checked by `existing_repair` |
| context provenance | `ContextBuilder.review_targets` serves the triggering review |
| recorded refusal | `REPAIR_WORK_CREATED` with `admitted: false` and a reason |

No second delivery mechanism was introduced, and `Propagation` kept its meaning.

## 16. Repair work is controller-authored

`finalreview.repair_task` is the only writer of a repair task. Generic worker `TaskRequest`
adoption **remains closed**: nothing a model proposed reaches this path. Every repair task
carries its triggering review and result, the criterion and gap it must close, its round
number, a suppression key, `required=True`, and the tool its criterion's verifier needs.

`WorkController._authorize_repair` offers *every* required gap to `repair_admissible`, not
only the admissible ones, so each refusal is recorded with its reason rather than being
silently absent. Admitted tasks are committed together with the wave that charges them.

## 17. Repair and revision limits

Two counters, tracked separately, as the brief asked:

| Counter | Default | Meaning |
|---|---|---|
| `repair_rounds` / `repair_round_limit` | 2 | evidence-repair rounds |
| `presentation_revisions` / `presentation_revision_limit` | 2 | resyntheses that changed only presentation |
| `synthesis_attempts` / `synthesis_attempt_limit` | 5 | total synthesis executions |

`synthesis.repeated_attempt` adds a tighter bound: a synthesis over the *same support* after
the *same feedback* has nothing new to try, so it is refused before it is dispatched
(`SYNTHESIS_REPEATED_FAILURE`) rather than burning the attempt budget on identical failures.

The run can always explain both directions. Admission is `REPAIR_WORK_CREATED
{admitted: true, round: n, criterion_id, repair_key, review_id, result_id}`; refusal is the
same event with `admitted: false` and one of the reasons in §5.

## 18. EXHAUSTED as a first-class outcome

`TerminalReport` is written in the same transaction as the terminal state and keeps:

```text
state · stop_reason · result_id (COMPLETED only)
validated_finding_ids     the partial knowledge the run established
gaps                      every unresolved criterion, with its reason
branch_stops              every closed branch and why
final_review_issues       every issue any final review raised
unconsumed_knowledge      deliveries never answered, follow-ups never opened
```

`_check_report` refuses a report whose `result_id` is set outside COMPLETED, or whose
`validated_finding_ids` name anything not currently VALIDATED. Partial knowledge is
preserved and is never reported as a successful completed result — the tests assert both
halves.

Observed exhaustion reasons: `REQUIRED_CRITERION_UNRESOLVED`, `CYCLE_LIMIT`, `REPAIR_LIMIT`,
`PRESENTATION_REVISION_LIMIT`, `SYNTHESIS_ATTEMPT_LIMIT`, `SYNTHESIS_REPEATED_FAILURE`,
`NO_INDEPENDENT_FINAL_REVIEWER`, `COMPLETION_BUDGET_INSUFFICIENT`, `DEADLINE`,
`UNREPAIRABLE_REVISE`/`UNREPAIRABLE_REJECT`, `STALE_PASS`.

## 19. FAILED vs EXHAUSTED

The distinction is preserved and tested.

**FAILED** — the system could not operate correctly:

- invalid required configuration (`workflow.configured` refuses at RECEIVED);
- no admitted work at DECOMPOSING;
- a `StorageError`, which propagates and stops the controller without adjudicating the run
  at all, so a storage failure can never be mistaken for exhaustion.

**EXHAUSTED** — the system operated correctly and could not satisfy the objective within its
evidence, resources or limits. A deadline is EXHAUSTED, not FAILED.

## 20. Budget reservation

`policies.completion_reserve(snapshot, run)` holds back, for any live run:

```text
COMPLETION_REQUESTS (2: one synthesis, one final review)
+ outstanding_reviews(...)   required finding review/revalidation not yet scheduled
```

`BudgetPolicy.admit` adds that floor for **optional** tasks only, on top of the Stage-4
pending-required-work term. Required completion work is never blocked by its own reserve.

The reserve is for work *ahead*: `completion_cost(run)` is 2 before synthesis, 1 while
SYNTHESIZING (the synthesis is already being paid for) and 0 in FINAL_REVIEW. Charging the
full reserve at the post-PASS re-check would refuse a result the run had already paid for.

An authorized repair round adds required repair tasks, which the existing pending-required
term already counts; it is not reserved twice.

## 21. Reviewer resource reservation

`reserved_for_review` — the Stage-6 mechanism — now also calls `_final_review_holder`, which
holds back **one** eligible independent final-review identity once completion is imminent:
the run is SYNTHESIZING or in FINAL_REVIEW, a CANDIDATE result exists, or a synthesis or
final-review task is open. The controller enters SYNTHESIZING only after the gate said
READY, so those states are exactly "ready or near-ready" without recomputing the gate inside
a selection policy.

It is an explicit reservation rule, not a scheduler: it names the first eligible identity in
deterministic order and takes nothing else.

## 22. Cycle semantics — resolved

**The rule:** an exploration wave is charged against `cycle_limit` when it is opened *with*
admitted executable work. `_open_cycle` now builds the cycle record and the run's counter
increment but commits them only in the same transaction as the first admitted task; a wave
that admits nothing was never opened at all, so it costs nothing.

Concretely:

- a wave that admits a reconsideration or repair task **counts**, even if that task later
  answers `NO_CHANGE` — executable investigation really was admitted;
- pure bookkeeping — propagation considered, every trigger refused, only `NO_CHANGE`
  answers, no new task — **does not count**;
- the initial wave counts, because it carries the seeded task graph;
- re-entering a settled run still counts (the Stage-6 rule that prevents escaping the bound
  by calling `run_until_idle` again).

`open_repair_cycle` charges a wave by the same rule and closes any open wave first, so a run
never holds two open cycles.

## 23. Run state and cycle records

No second wave-history structure was added. `Run.state` is the coarse phase; the Stage-6
`Cycle` records remain the bounded-iteration history beneath it, and the run-level workflow
reads and closes them through the same `circulation` methods Stage 6 wrote.

## 24. Branch stopping and run stopping

Branch termination stays local and unchanged. `workflow.branch_stops` aggregates closed
branches into the terminal report without altering what a stop meant. The tests cover both
directions:

- three branches all `NO_PROGRESS` and one required criterion unsupported → EXHAUSTED, with
  every branch stop in the report;
- a branch whose claim was rejected while another cleanly covers the required criterion →
  COMPLETED;
- a branch whose prerequisite could not run → `DEPENDENCY_FAILED`, and the run still
  adjudicates on coverage rather than on the stop.

## 25. Knowledge nothing consumed

`completion.unconsumed_knowledge` reports three things Stage 6 recorded but nothing
surfaced: a delivery still `SELECTED`/`DELIVERED` when the run settled, a
`FOLLOW_UP_REQUESTED` outcome that never became a task, and an `UNREPORTED` outcome. They
appear in every terminal report.

Synthesis selects from current validated knowledge by criterion relevance; propagation is
not a prerequisite for final use.

## 26. Conflicts

The deterministic rule:

- an open conflict over any finding supporting a **required** criterion makes that coverage
  unclean, gaps it `CONFLICTED`, and blocks synthesis;
- a resolved conflict does not;
- a conflict over a **non-required** criterion does not block, but is carried into
  `Task.limitations` and into the `Result.limitations` as `OPEN CONFLICT <id> (<kind>) over
  <findings>: <reason>`, so contested information is never presented as settled;
- a conflict that opens *during* a final review is a stale reason and a PASS blocker.

## 27. Events

Added: `RUN_STATE_CHANGED`, `SYNTHESIS_GATE_EVALUATED`, `SYNTHESIS_STARTED`,
`SYNTHESIS_STALE`, `RESULT_CREATED`, `RESULT_REJECTED`, `FINAL_REVIEW_STARTED`,
`FINAL_REVIEW_COMPLETED`, `FINAL_REVIEW_STALE`, `RESULT_REVISION_REQUESTED`,
`REPAIR_WORK_CREATED`, `RUN_COMPLETED`, `RUN_EXHAUSTED`, `RUN_FAILED`, `RUN_CANCELLED`.

`SYNTHESIS_STARTED` and `FINAL_REVIEW_STARTED` fire twice with a `phase` field —
`AUTHORIZED` when the controller creates the work (carrying the support or the result
version) and `DISPATCHED` when an assignment activates (carrying the agent and assignment).

The causation chain is queryable end to end. Correlating on the result id links
`RESULT_CREATED → FINAL_REVIEW_STARTED → FINAL_REVIEW_COMPLETED`; `causation_id` on those
carries the assignment; `REPAIR_WORK_CREATED` names its `review_id`, `result_id`,
`criterion_id` and `repair_key`; and `SYNTHESIS_GATE_EVALUATED` carries the full per-criterion
readiness that justified the next step.

## 28. Stale synthesis

A synthesis assignment pins every supporting finding and revision through the ordinary
Stage-4 context pins. `synthesis.stale_support` re-checks exactly those pins and nothing
else, so support that moved makes the output stale (`RESULT_STALE`) while an unrelated
change does not. There is no global run-revision invalidation rule.

## 29. Stale final review

A final-review assignment additionally pins the exact result version
(`Assignment.result_id` + `result_revision`). `check_assignment_admissibility` refuses the
envelope outright when that version moved or left CANDIDATE (`RESULT_VERSION_CHANGED`), and
`finalreview.stale_reasons` computes the explicit reasons that are recorded on the review
itself:

```text
RESULT_MISSING · RESULT_VERSION_CHANGED · RESULT_<status>
SUPPORT_MISSING · SUPPORT_<status> · SUPPORT_REVISION_CHANGED
CONFLICT_OPENED: <conflict id>
CRITERION_CHANGED
```

A stale review is still recorded — the run must be able to say that a review happened and
why it could not authorize completion — with `verification = 'STALE: ...'` and a
`FINAL_REVIEW_STALE` event. It never completes the run.

## 30. Stage-7 integration trace (COMPLETED)

Three branches: `ga` and `gc` both work criterion `c1`; `gb` works `c2`. Real committed
events, abridged to the workflow-bearing ones.

```text
CYCLE_STARTED                wave 1 INITIAL
RUN_STATE_CHANGED            RECEIVED -> DECOMPOSING (configuration validated)
RUN_STATE_CHANGED            DECOMPOSING -> EXPLORING (task graph admitted)
FINDING_CREATED              sum([1, 2, 3]) = 6
FINDING_CREATED              sum([4, 5]) = 9
FINDING_CREATED              sum([10, 20]) = 30
TASK_CREATED                 criticism  x3
FINDING_CRITIQUED            PASS x3
TASK_CREATED                 validation x3
FINDING_VALIDATED            PASS: c1:TOOL_RESULT_ENTAILS_CLAIM
FINDING_VALIDATED            PASS: c1:TOOL_RESULT_ENTAILS_CLAIM
FINDING_VALIDATED            PASS: c2:TOOL_RESULT_ENTAILS_CLAIM
CROSS_POLLINATION            finding:000005 -> tc (score 2)
CROSS_POLLINATION            finding:000006 -> ta (score 2)
RUN_STATE_CHANGED            EXPLORING -> EVALUATING (exploration wave settled)
RUN_STATE_CHANGED            EVALUATING -> CONSOLIDATING (candidates reviewed)
CYCLE_COMPLETED              wave 1
CYCLE_STARTED                wave 2 NEW_KNOWLEDGE
TASK_CREATED                 reconsideration x2
RUN_STATE_CHANGED            CONSOLIDATING -> EXPLORING (admitted follow-up work)
PROPAGATION_DELIVERED        -> tc ; -> ta
RECONSIDERATION_COMPLETED    NO_CHANGE: the branch rechecked its own sum   x2
RUN_STATE_CHANGED            EXPLORING -> EVALUATING (exploration wave settled)
RUN_STATE_CHANGED            EVALUATING -> CONSOLIDATING (candidates reviewed)
CYCLE_COMPLETED              wave 2  ['task:000030', 'task:000031']
SYNTHESIS_GATE_EVALUATED     READY
TASK_CREATED                 synthesis
SYNTHESIS_STARTED            AUTHORIZED / DISPATCHED
RUN_STATE_CHANGED            CONSOLIDATING -> SYNTHESIZING (synthesis gate READY)
RESULT_CREATED               v1 cites finding:000005, finding:000022
TASK_CREATED                 final_review
RUN_STATE_CHANGED            SYNTHESIZING -> FINAL_REVIEW (candidate result admitted)
FINAL_REVIEW_COMPLETED       REVISE on v1 criteria=['c1']
SYNTHESIS_GATE_EVALUATED     READY
RESULT_REVISION_REQUESTED    PRESENTATION: PRESENTATION_ONLY
RUN_STATE_CHANGED            FINAL_REVIEW -> SYNTHESIZING (presentation revision)
TASK_CREATED                 synthesis
RESULT_CREATED               v2 cites finding:000005, finding:000006, finding:000022
TASK_CREATED                 final_review
RUN_STATE_CHANGED            SYNTHESIZING -> FINAL_REVIEW (candidate result admitted)
FINAL_REVIEW_COMPLETED       PASS on v2
SYNTHESIS_GATE_EVALUATED     READY
RUN_COMPLETED                FINAL_REVIEW_PASS
RUN_STATE_CHANGED            FINAL_REVIEW -> COMPLETED (final review PASS and current gate valid)

COMPLETED  requests=21 tools=6 cycles=2 repairs=0 revisions=1
report: knowledge=[finding:000005, finding:000006, finding:000022] gaps=[] branches=[]
answer: total: sum([1, 2, 3]) = 6; sum([4, 5]) = 9; sum([10, 20]) = 30
```

The repair path in this trace is a **presentation-only** revision: version 1 omitted one of
two validated totals supporting `c1`; the reviewer named `c1`; the controller confirmed from
the record that the knowledge existed and the result simply failed to present it; version 2
cites all three findings and passes.

Nothing here is satisfied by the fake provider's assertion. Every validated claim carries
`TOOL_RESULT_ENTAILS_CLAIM` from `ArithmeticVerification`, which compares the claim's own
operands and asserted total against the host-recorded tool arguments and output.

## 31. Stage-7 exhausted trace (EXHAUSTED)

Same three branches; branch `gb` asserts `sum([10, 20]) = 99`, and every repair attempt
repeats it.

```text
CYCLE_STARTED                wave 1 INITIAL
RUN_STATE_CHANGED            RECEIVED -> DECOMPOSING -> EXPLORING
FINDING_VALIDATED            PASS: c1:TOOL_RESULT_ENTAILS_CLAIM  x2
FINDING_CREATED              sum([10, 20]) = 99
FINDING_REJECTED             FAIL: c2:TOOL_RESULT_CONTRADICTS_CLAIM
RUN_STATE_CHANGED            EXPLORING -> EVALUATING -> CONSOLIDATING
CYCLE_COMPLETED              wave 1
COVERAGE_GAP                 c2:UNSUPPORTED
CYCLE_STARTED                wave 2 NEW_KNOWLEDGE
TASK_CREATED                 reconsideration x2
RUN_STATE_CHANGED            CONSOLIDATING -> EXPLORING (admitted follow-up work)
RECONSIDERATION_COMPLETED    NO_CHANGE x2
RUN_STATE_CHANGED            EXPLORING -> EVALUATING -> CONSOLIDATING
CYCLE_COMPLETED              wave 2
COVERAGE_GAP                 c2:UNSUPPORTED
SYNTHESIS_GATE_EVALUATED     NOT_READY: CRITERION_UNSUPPORTED: c2
CYCLE_STARTED                wave 3 FINAL_REVIEW_REPAIR ['task:000034']
TASK_CREATED                 repair
REPAIR_WORK_CREATED          admitted c2
RUN_STATE_CHANGED            CONSOLIDATING -> EXPLORING (repair work admitted from the synthesis gate)
FINDING_CREATED              sum([10, 20]) = 99
FINDING_REJECTED             FAIL: c2:TOOL_RESULT_CONTRADICTS_CLAIM
RUN_STATE_CHANGED            EXPLORING -> EVALUATING -> CONSOLIDATING
BRANCH_TERMINATED            NO_PROGRESS x3
CYCLE_COMPLETED              wave 3
COVERAGE_GAP                 c2:UNSUPPORTED
SYNTHESIS_GATE_EVALUATED     EXHAUSTED: CRITERION_UNSUPPORTED: c2
REPAIR_WORK_CREATED          refused c2 CYCLE_LIMIT
RUN_EXHAUSTED                REQUIRED_CRITERION_UNRESOLVED: CRITERION_UNSUPPORTED: c2
RUN_STATE_CHANGED            CONSOLIDATING -> EXHAUSTED

EXHAUSTED  requests=22 tools=8 cycles=3 repairs=1 revisions=0
report: knowledge=[finding:000005, finding:000006]
        gaps=['c2:UNSUPPORTED']
        branches=['ga: NO_PROGRESS', 'gb: NO_PROGRESS', 'gc: NO_PROGRESS']
```

No `Result` was ever created, `run.result_id` is `None`, and `repository.inspect(...).status`
is `EXHAUSTED`. Branch A's and branch C's validated totals are preserved in the report and
are explicitly not offered as an answer.

## 32. Verification

### Test suite

**458 tests, 0 failures**, in three environments:

| Environment | Result |
|---|---|
| CPython 3.13.5 | 458 tests, OK |
| CPython 3.11.9 (the declared `requires-python` floor) | 458 tests, OK |
| the built wheel `swarm_foundations-0.5.0-py3-none-any.whl`, imported with `src` off the path | 458 tests, OK |

Stage 7 added 159 tests across six modules and one fixture module:

```text
tests/stage7_support.py            the completing provider and run/result helpers
tests/test_stage7_gate.py          readiness, coverage, gaps, repair admissibility  (24)
tests/test_stage7_synthesis.py     context, provenance, admission, versions, staleness  (30)
tests/test_stage7_review.py        independence, contract, staleness, PASS re-check,
                                   classification, repair authority, verdict records  (33)
tests/test_stage7_workflow.py      transitions, guards, terminal outcomes, reservation  (37)
tests/test_stage7_repair.py        revision and repair limits, loop bounds, exhaustion  (17)
tests/test_stage7_integration.py   the two end-to-end scenarios and determinism  (18)
```

The Stage-4/5/6 suites are unchanged in what they assert; they now instantiate `WorkEngine`
rather than `WorkController`, because they exercise the work engine and a run that reaches a
terminal state legitimately refuses to be re-entered.

### Guards checked by mutation, not assumed

A single-guard mutation battery replaces one check at a time with its no-op and runs the
whole suite against the mutant. **60/60 mutations were caught; 0 survived.**

```text
completion.py   13    gate readiness, budget, repair admissibility, gap classification
finalreview.py  11    independence, contract, staleness, PASS blockers, classification
synthesis.py    10    citation checks, coverage, staleness, repeat suppression
invariants.py    6    result structure, COMPLETED/result pairing, singletons
workflow.py      6    phase guards, transition legality, configuration
admission.py     4    result pinning, proposal scope, role
policies.py      3    reviewer pool, completion reserve, reviewer holder
circulation.py   2    repair-wave charging and overlap
persistence.py   2    result immutability, stored run transitions
cycles.py        1    gap classification
knowledge.py     1    conflict-aware coverage
domain.py        1    run transition legality
```

The first battery left **11 survivors** — guards no test was exercising, including the
`REQUIRED_CRITERION_UNSUPPORTED` and `REQUIRED_CRITERION_NOT_IN_RESULT` PASS blockers, the
`RESULT_SUPPORT_NOT_VALIDATED` check behind the staleness check that usually fires first,
the `SUPPORT_REVISION_CHANGED` stale reason behind the status branch, both settle guards
(whose tests asserted a reason string that survived the mutation), the stored run-transition
guard, the single-accepted-result and COMPLETED/result invariants, the synthesis attempt
limit, `REQUIRED_WORK_UNSETTLED`, and the repair-wave overlap guard. Each was bound by a
test of its own — 18 tests in total — before the battery was re-run against the shipped
source, where every mutation was caught.

Two mutations in the first battery were reported `BAD_MUTATION (anchor missing)` rather than
run, which is the battery detecting its own stale anchors after a refactor; both were
repaired and are among the 60.

### Determinism

`DeterminismTests` runs the integration scenario three times and asserts a single distinct
terminal record: same accepted version, same citations, same per-criterion coverage, same
provider-request count, same wave count.

### Repository

```text
src/swarm/      7,289 lines across 27 modules   (largest: domain.py at 705)
tests/          6,475 lines across 19 modules
wheel           swarm_foundations-0.5.0-py3-none-any.whl (108 KB)
```

## 33. Deviations from the architecture review and the Stage-7 brief

| # | Deviation | Class |
|---|---|---|
| 1 | Record `schema_version` bumped to 4 and the SQLite `user_version` with it, so a stage-6 database is refused rather than silently reread with defaults for `Result`, `TerminalReport` and the new `Run`/`Task`/`Assignment` fields. Consistent with the Stage-5 and Stage-6 precedent; there is still no migration, because persistence offers inspection and not resumption. | IMPROVEMENT |
| 2 | `Result` became a first-class `RunRecord` instead of a value embedded on `Run`. The brief said "use or refine the existing Result supporting record"; an embedded value cannot be a version, cannot be reviewed by identity, and cannot be made immutable by storage. `Run.result` was replaced by `Run.result_id`, and `_check_run` makes COMPLETED and an accepted result one fact. | IMPROVEMENT |
| 3 | `TerminalReport` is a record rather than fields on `Run`. It carries structured `Gap` values, branch stops, final-review issues and unconsumed knowledge, which do not belong in a mutable run row and must be written once. | IMPROVEMENT |
| 4 | `Criterion.required` was added. §3 and §26 both distinguish required from optional criteria and the record had no way to say so. | NEUTRAL |
| 5 | `SYNTHESIZING → CONSOLIDATING` was added to the architecture's state set. A synthesis that produces no admissible candidate has to go somewhere; routing it back through CONSOLIDATING re-applies the gate rather than inventing a retry state. The semantic phases are unchanged. | NEUTRAL |
| 6 | The controller was split four ways (`ControllerCore` / `Circulation` / `WorkEngine` / `WorkController`) rather than the `controller.py` / `workflow.py` / `completion.py` the brief suggested. The extra seam is `WorkEngine`, and it exists because it makes the "coordinator, not replacement" claim checkable: the Stage-4/5/6 suites run the engine without the workflow. `orchestration.py` fell from 709 to 476 lines. | IMPROVEMENT |
| 7 | Stage-5/6 controller tests now target `WorkEngine`. Their fixtures run, extend and re-run one run, which a terminal-state workflow legitimately forbids; the behaviour they assert is the engine's, and it is unchanged. No Stage-5 or Stage-6 guarantee was weakened, and the Stage-7 suites exercise the full `WorkController`. | RISK |
| 8 | Stage-4 controller fixtures gained an acceptance criterion. A run with none is now FAILED at RECEIVED, which is what the architecture specifies; those tests exercise scheduling, so they declare one criterion and leave coverage to Stage 7. | NEUTRAL |
| 9 | Host-verified evidence became a *gate* condition (`SUPPORT_UNVERIFIED`), not only a promotion condition. Stricter than the brief asked; it carries the Stage-5 epistemic boundary into completion so a hand-built VALIDATED finding cannot reach an answer. | IMPROVEMENT |
| 10 | `NO_REPAIR_CAPACITY` was added to repair admissibility. Admitting work no registered role or free identity can execute would spend a wave to arrive back at the same gap. | IMPROVEMENT |
| 11 | `synthesis.repeated_attempt` refuses a synthesis over the same support after the same feedback. The brief bounded the loop by attempt count; this bounds it by *sameness*, so a deterministic failure is reported once instead of five times. | IMPROVEMENT |
| 12 | Propagation reuse for REVISE/REJECT feedback was evaluated and declined, with the shape reused on the repair task instead. See §15. The brief explicitly permitted this outcome provided it is documented. | NEUTRAL |
| 13 | The controller admits bounded reconsideration work *before* consulting the gate, following the architecture's CONSOLIDATING rule ("admit permitted follow-ups … otherwise apply the synthesis gate") rather than gating first. A branch that received a discovery answers it before the answer is written. Bounded by the unchanged wave limit. | NEUTRAL |
| 14 | `completion_cost` makes the completion reserve depend on the run state (2 before synthesis, 1 while synthesizing, 0 in final review). Charging the full reserve at the post-PASS re-check refused results the run had already paid for. | IMPROVEMENT |
| 15 | `RevisionKind.NONE` was added for a REVISE/REJECT that names nothing the record confirms. The brief's two revision kinds both assume a located defect; without a third case an unlocatable complaint would be silently treated as presentation. | IMPROVEMENT |
| 16 | `ReviewRecord` gained `criterion_ids` and `unsupported_claims`. §11 requires the reviewer to identify what is wrong in a form the controller can act on; free text is not actionable, and the controller authors work against a criterion. | NEUTRAL |
| 17 | `SYNTHESIS_STARTED` and `FINAL_REVIEW_STARTED` are emitted twice with a `phase` discriminator (`AUTHORIZED`, `DISPATCHED`). Authorization carries the support and the version; dispatch carries the agent and assignment. | NEUTRAL |
| 18 | `domain.py` is 705 lines — the largest module, under the 800-line ceiling but the obvious next split candidate. The result/report records could move to their own module when the next stage adds records. | RISK |
| 19 | Stage-4 design issues 1 (nothing adopts a `TaskRequest`) and 5 (NEEDS_INPUT ends in FAILED) are still untouched. Stage 7 opened a third controller-owned factory (repair work), which is deliberately not `TaskRequest` adoption. | RISK |

Nothing in the brief was skipped or narrowed. Items 7, 18 and 19 are the RISK entries; 19 is
carried forward from Stage 4.

## 34. What Stage 7 revealed that should influence Stage 8

1. **`TaskRequest` adoption is now the only unopened work path, and Stage 7 built its last
   missing piece.** A repair task already proves a model-independent shape: an explicit
   triggering record, a named criterion, a bounded scope, a round number, a duplicate key and
   a recorded refusal reason. Adopting a `TaskRequest` needs exactly that plus one check the
   gate can now perform — *does this proposal name a real gap?* `completion.gap_records` is
   that check. Stage 8's free-text runs are the first consumer with a reason to want it.

2. **Acceptance criteria are the system's only vocabulary for "what would count as done", and
   Stage 8 has to produce them from prose.** Everything downstream — coverage, gaps, repair
   targeting, the gate, the result's own structure — is keyed on `Criterion.id` and
   `verifier_kind`. A decomposition that invents criteria will quietly weaken the gate, so
   DECOMPOSING needs the same treatment criticism and validation got: a proposal that the
   controller validates against something, not a model's word.

3. **`verifier_kind` is the real limit on what a run can complete.** `ArithmeticVerification`
   is the only policy, and `VerificationRegistry` fails closed on anything else — so a
   criterion Stage 8 cannot verify is `SUPPORT_UNVERIFIED` forever and the run exhausts,
   correctly but uselessly. Stage 8 either ships more verifiers or accepts that free-text
   runs mostly end EXHAUSTED. That is a product decision, not a bug, and it should be made
   explicitly.

4. **The repair loop is bounded by *sameness*, and that exposed how little a failing branch
   varies.** In the exhausted trace, the repair task repeats the same unverifiable claim
   because nothing tells it what was already tried. The repair task's description names the
   gap; it does not name the rejected attempts. Stage 8 should decide whether a repair task
   should see the failed approaches — the projection already computes them.

5. **A run now ends, which changes the host contract.** `run_until_idle` used to be
   re-enterable indefinitely; it now drives to a terminal state, and re-entering a terminal
   run is a no-op. Any Stage-8 CLI must treat a run as single-shot, and the `WorkEngine`
   seam is the honest place for a host that wants to inspect a settled wave first.

6. **The terminal report is the natural CLI output, and it is already complete.** Answer,
   citations, coverage, limitations, gaps, branch stops, unconsumed knowledge and stop reason
   are all recorded. Stage 8's reporting surface is a rendering problem, not a data problem —
   which is the right place to be.

7. **Concurrency is still bounded by the identity pool, and completion made that sharper.**
   `reserved_for_review` now holds a final reviewer as well as a critic and a validator per
   due review. A run with three unbranched identities is close to its limit before any
   optional work is scheduled. Stage 8 should either size the pool from the task graph or
   make the reservation refusal visible in the CLI, because "nothing dispatched" is otherwise
   indistinguishable from "nothing to do".

8. **Determinism survived the workflow.** The integration scenario produces one distinct
   terminal record across repeated runs — same accepted version, same citations, same
   coverage, same provider-request count, same wave count. Stage 8 should keep that property
   as an explicit test when free-text input arrives, because it is the cheapest available
   signal that no hidden ordering has crept in.
