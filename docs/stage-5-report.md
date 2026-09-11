# Stage 5 checkpoint — criticism, independent validation, verification, knowledge

Implemented only the Stage-5 authorization: the swarm's epistemic boundary.

```text
candidate claim → independent criticism → independent verification → validated finding
                                                                   → shared validated knowledge
```

A fluent model response, and agreement between models, cannot cross that boundary. Crossing it
requires a host verification policy to establish that authoritative recorded tool evidence entails
the exact claim.

Cross-pollination, relevance routing of newly validated findings, cross-branch retraction delivery,
synthesis, final review, the full run state machine, real providers, embeddings, distributed
execution, UI and crash resume remain unimplemented.

## Locked decisions as implemented

### One logical SwarmState per Run

`domain.validate_records` now refuses any snapshot holding two `SwarmState` records for one run, so
an ambiguous set is impossible to persist rather than merely impossible to read. The controller
creates the projection once, at `_open_run`, and every later change keeps that identity and
increments its revision. Assignments still pin `state_id`/`state_revision`, and assignment
admissibility still does not compare them: a projection revision alone never stales a result.
Admissibility remains dependency-aware exactly as Stage 4 established.

`context.ContextBuilder` keeps its `AMBIGUOUS_SWARM_STATE` refusal as defence in depth.

### `Assignment.context_revision` removed

The field carried no information: `context_hash` is content-addressed over the exact payload, and the
finding, message, criterion, tool, task and dependency pins carry the rest of the provenance. It was
removed rather than given an invented meaning.

That is a serialization shape change, so it was made explicitly: **record `schema_version` is now 2**
(`domain.SCHEMA_VERSION`), `serialization.loads` refuses a version-1 payload, and the SQLite
`user_version` moved to 2 so a stage-4 database is rejected as unsupported instead of being partially
reread. Event envelopes keep `schema_version: 1`; their shape did not change. There is no migration,
consistent with the standing decision that persistence offers inspection and not resumption.

### Review target semantics

A review Task targets a Finding *identity* through `target_finding_id`. At assignment preparation the
controller resolves that identity and pins the exact current revision through the ordinary
`input_finding_ids`/`input_finding_revisions` snapshot. The returned review must name that exact
revision, and `admission` compares it with the pin, not with the model's claim about it.

Every recorded review moves the target's revision — a promotion, a rejection, a critique and even an
inconclusive review all append to `review_ids` — so any other assignment pinned to the older revision
becomes stale by the existing Stage-4 rule.

A review task is only created for a finding whose current state is the one that review kind expects,
and `admission` re-checks eligibility at admission time (`REVIEW_TARGET_INELIGIBLE`), so a review
never silently applies to a REJECTED, SUPERSEDED or already-VALIDATED claim.

## 1. Review workflow

```text
PROPOSED → CRITIC → CRITIQUED → VALIDATOR → VALIDATED | REJECTED
```

`review.plan_reviews` is the scheduling policy and `WorkController._plan_reviews` is its only caller.
The controller creates review Tasks; a worker cannot request review of its own finding, because
`TaskDraft` has no finding fields and no admitted `TaskRequest` becomes a Task.

Review work then flows through the ordinary Stage-4 machinery: `ready_decision`, `role_for`, agent
selection, `BudgetPolicy`, `ContextBuilder`, `execute`, `check_assignment_admissibility`, one
commit. There is no second execution path.

Scheduling rules, all deterministic:

- A finding that is PROPOSED or INVALIDATED is due for criticism; CRITIQUED is due for validation.
- A review kind whose role is not registered for the run is not scheduled at all. That is a host
  configuration decision, deliberately distinct from having no *independent* agent.
- Attempts are bounded per `(finding, kind)` by `ReviewPolicy.attempts_per_kind` (default 1), so a
  finding that cannot be reviewed leaves one recorded gap instead of an endless queue.
- Validation waits while any transitive dependency finding is not VALIDATED, and criticism waits
  while any is REJECTED, INVALIDATED or SUPERSEDED.
- Review tasks carry `group_id=None`: review work belongs to no exploration branch.

## 2. Critic independence

`policies.excluded_review_agents` excludes the generating agent — resolved through the finding's
generating assignment — and `policies.compatible_review_agents` removes those identities from the
ordinary compatibility set. `policies.eligible_agents` is the single selection entry point the
controller calls, so a review task can never be filled by `compatible_agents` alone.

The selector considers the generating agent and assignment, the target finding's revision and state
(through readiness and the pinned snapshot), role compatibility, provider and tool permissions,
group scope, and agent availability.

Independence is decided **before dispatch**. When no independent reviewer exists,
`WorkController._review_gap` fails the task with `NO_INDEPENDENT_REVIEWER` and emits
`REVIEW_REJECTED`; no provider request is spent, and the bounded attempt count prevents the gap from
being recreated. There is no fallback to self-review.

`domain.validate_records` repeats the check at commit time as defence in depth, not as the primary
control.

## 3. Validator independence

For validation, `excluded_review_agents` additionally excludes every agent that has already reviewed
that finding, so generator, critic and validator are three distinct identities. When fewer than
three independent agents exist, validation simply does not proceed and the gap is recorded; the
requirement is never weakened to complete the workflow.

`domain.validate_records` refuses to commit a validation review whose reviewer also produced a
criticism review of the same target.

## 4. Critic contract

A critique is a `ReviewRecord` with `kind=CRITICISM`, targeting `(finding_id, finding_revision)`
exactly, carrying `decision`, `blocking_issues`, `nonblocking_issues`, `checks`, `evidence` and
`summary`. Decisions are a closed enum: `PASS`, `CHALLENGE`, `INCONCLUSIVE`.

The critic does not decide truth. `PASS` and `CHALLENGE` both move the finding to CRITIQUED; the
difference is the blocking issues recorded. `INCONCLUSIVE` records the review, moves the revision and
leaves the finding where it was, so nothing is promoted on an inconclusive examination.

Each blocking issue gets a stable key, `<review_id>#<index>` (`domain.blocking_keys`). The keys are
delivered to the validator in its context, and a blocking issue is resolved only when a passing
validation review names its exact key. `domain.validate_records` refuses any VALIDATED finding with
an unaddressed blocking key, and `review.admit_review` drops invented keys before the record is
built, so naming a made-up issue resolves nothing.

## 5. Validator contract

A validation is a `ReviewRecord` with `kind=VALIDATION` and the closed decision set `PASS`, `FAIL`,
`INCONCLUSIVE`. Its recorded decision is a combination, never the model's alone:

| model | host verification | recorded |
|---|---|---|
| any | FAIL | FAIL |
| FAIL | any | FAIL |
| PASS | PASS, all blocking keys resolved, dependencies validated | PASS |
| anything else | | INCONCLUSIVE |

The host can only lower the outcome. `INCONCLUSIVE` never promotes. The full trail — the host verdict,
the criterion it came from, and the reason a PASS was refused — is recorded on
`ReviewRecord.verification`.

## 6. Evidence verification policy

`swarm.verification` is the host-controlled verifier abstraction:

```python
VerificationPolicy.verify(finding, evidence, criterion, tool_results, snapshot) -> VerificationDecision
```

`VerificationRegistry` dispatches by the acceptance criterion's `verifier_kind`. A criterion whose
kind has no registered policy returns INCONCLUSIVE (`UNSUPPORTED_VERIFIER_KIND`); a finding with no
criteria, or with a criterion the run does not define, is INCONCLUSIVE. Every criterion must pass;
any FAIL is FAIL. There is no universal truth verifier.

`ArithmeticVerification` is the first policy. Its input is not "did a tool succeed" but the
authoritative record of what the tool computed. `ToolResult` and `Evidence` now carry
`tool_name` and host-canonicalized `arguments_json`, written by `execution.execute` from the
schema-validated arguments it actually dispatched. The policy admits a result only when its recorded
operands are the claim's own operands, its recorded `expected` is the claim's asserted total, and its
recorded output states `actual == expected` and `matches == true`. A recorded result over other
numbers is ignored; one that contradicts the claim makes the whole verification FAIL.

Only `VerificationDecision.evidence` carries `verified=True`, and `review.admit_review` attaches it
only on a PASS. Model-proposed evidence is always recorded `verified=False`, and the output envelope
has no field through which a model could assert otherwise. `domain.transition` still refuses
VALIDATED without an independent, revision-exact, tool-backed review carrying verified evidence.

## 7. Narrow claim verification

The one supported arithmetic claim form is `sum([a, b, c]) = t`, parsed by
`verification.parse_sum_claim` with a deterministic regular expression over whitespace-insensitive
text. Any other wording — including `sum([1,2,3]) is 6` and free prose — returns `None`, and the
policy reports `UNSUPPORTED_CLAIM_FORM` as INCONCLUSIVE. Nothing guesses, and no second model is
asked whether evidence sounds supportive.

## 8. Finding transitions

All Stage-5 transitions run through `domain.transition` against exact revisions, and review history
is append-only (`persistence._validate_update`).

| transition | driver |
|---|---|
| PROPOSED → CRITIQUED | critic PASS or CHALLENGE |
| PROPOSED → REJECTED | host/controller decision; also reached from a stale target |
| CRITIQUED → VALIDATED | validator PASS **and** host verification PASS **and** blocking keys resolved **and** dependencies validated |
| CRITIQUED → REJECTED | validator FAIL or host verification FAIL |
| VALIDATED → INVALIDATED | `WorkController.invalidate_finding`, transitively |
| VALIDATED → SUPERSEDED | domain-level; no Stage-5 scheduler produces a revised claim |
| INVALIDATED → CRITIQUED | re-criticism, when the host allows another attempt |
| INVALIDATED → REJECTED | host/controller decision |

Substantive claim or evidence change still requires a new identity (`domain.revise_finding`); the
claim is never edited in place, and `persistence._validate_update` enforces that.

## 9. Promotion to validated knowledge

`review.admit_review` produces the review and the finding transition; `WorkController._settle`
extends the same transaction with conflict maintenance and the recomputed projection. One
`SQLiteRepository.commit` therefore carries:

```text
ReviewRecord + Finding → VALIDATED + SwarmState (validated += id, candidates -= id)
+ any Conflict opened or resolved + the review, lifecycle and knowledge events
```

The intermediate state is not merely avoided but unreachable: `validate_records` refuses a snapshot
whose `SwarmState` classification disagrees with a finding's status, in either direction.

## 10. Invalidation

`WorkController.invalidate_finding` wires the existing `domain.invalidate` closure into an
authoritative operation. It invalidates the named validated finding and, transitively, every
validated dependent; `_settle` removes them from `SwarmState.validated_findings`, reclassifies them
as invalidated, resolves any conflict that had them as a participant, and refreshes failed
approaches — all in one commit, so a failure leaves both the findings and the projection untouched.

Future contexts cannot select invalidated knowledge: `select_validated` draws only from the
projection, and `required_closure` refuses an unavailable required finding.

In-flight assignments pinned to a now-invalid finding are rejected exactly as Stage 4 established
(`INPUT_FINDING_CHANGED`); that behaviour is unchanged and covered by test.

**Policy for unvalidated dependents.** A PROPOSED or CRITIQUED dependent is *not* automatically
rejected, and it is explicitly not treated as fine either. It is named in the `KNOWLEDGE_REMOVED`
event as an unvalidated dependent; `plan_reviews` will not schedule its review while a dependency is
unavailable; and it cannot be promoted, because both `_settle` and `validate_records` refuse a
validated finding resting on an unvalidated one.

## 11. Retraction structure for Stage 6

No retraction is broadcast. Each `FINDING_INVALIDATED` event records the finding id and its new and
previous revision, the root that caused it, the reason, `delivered_to` (every recipient of a message
that referenced it) and `consumed_by` (assignment, agent and task of every assignment that pinned
it). `KNOWLEDGE_REMOVED` adds the full removed set and the unvalidated dependents. Stage 6 can build
targeted retraction from that record without re-deriving it.

## 12. Deterministic consolidation

No model participates. `knowledge.duplicate_groups` keys a finding by
`(normalized claim, evidence signature)`, where normalization is whitespace and case only and the
signature is a digest of each evidence entry's kind, tool name, canonical arguments and value —
deliberately excluding the per-execution tool result id, so the same computation from two branches
matches while similar prose does not.

The canonical representative is the highest-status member, then the lowest id. Every original
identity stays in the group's `member_ids` and in the repository; only the projection is
deduplicated, so shared knowledge offers one representative while all provenance remains queryable.
`consolidate()` emits `CONSOLIDATION_COMPLETED` carrying the full grouping. Results are independent
of insertion order and of `PYTHONHASHSEED`.

## 13. Conflicts

A `Conflict` is a first-class immutable record: id, sorted participant ids with pinned revisions,
kind, deterministic signature, reason, criterion ids, status and, once resolved, resolution and
timestamp. Finding claims are never mutated.

Only conflicts the system can establish are opened, and only between individually VALIDATED findings:

- `CONTRADICTORY_VALUE` — incompatible structured values for the same known property, extracted by an
  injectable policy (`verification.structured_sum_value` by default).
- `DECLARED_CONTRADICTION` — a finding tagged `contradiction` naming the other in
  `related_finding_ids`. Neither field is model-reachable, so this is a host/fixture declaration.

`OPEN → RESOLVED` is a guarded transition; a conflict resolves automatically when a participant stops
being validated. `knowledge.criterion_coverage` reports a criterion as covered but **not clean** while
an open conflict touches one of its supporting findings, so unresolved contradictions cannot be
mistaken for clean coverage by later synthesis. Synthesis itself remains out of scope.

## 14. Context behaviour with conflicts

The policy is: **a validated finding is never presented without every open conflict it participates
in.** The conflict id, kind, reason and the other participants' ids are embedded inside the finding's
own context entry, so no selection or truncation path can separate them.

For optionally selected knowledge the conflicted set is admitted atomically: the finding and its
disclosable validated peers go in together or the whole group is dropped with `GROUP_DROPPED`. One
side of an open conflict is therefore never offered alone when the other could have been shown. When
a peer is not disclosable to the reading task, the metadata still marks the finding as contested
without revealing the other branch's claim.

## 15. Review cross-scope authority

`Task.required_finding_ids` and `Task.target_finding_id` remain host authority that bypasses group
visibility, and `review.review_task` is now the only code that writes them. It is called only from
`WorkController._plan_reviews`, from a plan derived from a finding the controller can see, and it
pins the target plus its transitive dependency closure explicitly rather than inheriting fields from
a template task.

A worker cannot reach that authority: `TaskDraft` has no finding fields, `parse_output` rejects the
field names outright, and an admitted `TaskRequest` stays an inert proposal that nothing converts
into a Task. Both halves are pinned by test.

## 16. Review scheduling roles

The three Stage-4 restrictions were opened together rather than loosening the admission check alone:

- `policies.WORK_ROLES` now admits CRITIC and VALIDATOR; `role_for` maps `criticism` and `validation`.
- `policies.eligible_agents` routes review tasks through the independence policy.
- `admission` replaced `LATER_STAGE_PROPOSAL_FORBIDDEN` for reviews with a role-and-task-aware check:
  `REVIEW_PROPOSAL_FORBIDDEN`, `REVIEW_ROLE_MISMATCH`, `REVIEW_MISSING`, `REVIEW_SCOPE_VIOLATION`,
  `REVIEW_TARGET_MISSING`, `REVIEW_TARGET_REVISION_CHANGED`, `REVIEW_TARGET_MISMATCH`,
  `REVIEW_TARGET_INELIGIBLE`. `result` envelopes are still refused as a later stage.
- `roles.py` gives review roles `output_fields=('review', 'messages')`, so an EXPLORER's envelope
  cannot even be parsed with a `review` field, and a reviewer's cannot carry findings or task
  requests.
- `review.admit_review` builds the ReviewRecord and the lifecycle it authorizes; `context` supplies
  the review history; `events` records the outcome.

## 17. Events

Added: `TASK_CREATED`, `FINDING_CREATED`, `FINDING_CRITIQUED`, `FINDING_VALIDATED`,
`FINDING_REJECTED`, `FINDING_SUPERSEDED`, `REVIEW_STARTED`, `REVIEW_COMPLETED`, `REVIEW_REJECTED`,
`KNOWLEDGE_PROMOTED`, `KNOWLEDGE_REMOVED`, `CONSOLIDATION_COMPLETED`, `CONFLICT_OPENED`,
`CONFLICT_RESOLVED`, alongside the existing `FINDING_INVALIDATED`.

Review and conflict events carry exact finding revisions, the review kind, the model decision, the
recorded decision and the verification trail. Knowledge lifecycle changes no longer rely on the
generic `RECORD_CHANGED`, which remains only for record mutations that have no more specific type.

## Verification

191 unittest tests pass with 0 failures in three environments:

| Environment | Result |
|---|---|
| CPython 3.13.5, from source (`PYTHONPATH=src`) | 191 passed |
| CPython 3.11.9, from source — the declared `requires-python` floor | 191 passed |
| `swarm_foundations-0.3.0-py3-none-any.whl`, installed into a clean venv with `src` off the path | 191 passed |

Stage 4 also reported CPython 3.12.12; that interpreter is no longer present in this environment, so
3.11.9 was used instead. It is the stricter check, being the declared minimum.

| File | Tests | Area |
|---|---|---|
| `tests/test_domain.py` | 15 | records, transitions, cycles, provenance, deep graphs |
| `tests/test_persistence.py` | 12 | SQLite atomicity, revisions, update rules |
| `tests/test_execution.py` | 21 | bounded execution seam, hostile output, budgets |
| `tests/test_audit_integration.py` | 2 | durable counters across executions |
| `tests/test_stage4_services.py` | 27 | routing, context, readiness, admissibility, disclosure scope |
| `tests/test_stage4_controller.py` | 23 | controller scheduling, staleness, privacy, budgets, cancellation |
| `tests/test_stage5_verification.py` | 26 | claim entailment, consolidation, conflicts, supersession, invalidation |
| `tests/test_stage5_review.py` | 37 | review planning, independence, admissibility, review contracts, context, cross-scope |
| `tests/test_stage5_controller.py` | 28 | end-to-end review, promotion atomicity, invalidation, conflicts, cross-scope |

### Guards checked by mutation, not assumed

Fifty mutations were applied one at a time, each disabling a single Stage-5 guard; every one made at
least one test fail. Two of the fifty needed a second attempt: the first `bdist_wheel`-style attempt
at "review tasks belong to no branch" was a no-op mutation, and five guards initially survived
because a stronger check fired first. Those five were then bound by tests of their own before being
re-mutated and caught:

- the tool must have checked the *claim's* asserted total, not merely a total consistent with itself;
- the domain-level unresolved-blocking-critique refusal;
- the domain-level shared-state classification check (an earlier version of its test failed for the
  wrong reason — the forged review also violated critic/validator independence);
- the `REVIEW_TARGET_REVISION_CHANGED` backstop for a target that was never pinned;
- the breadth of the invalidated-target context exemption, which must cover the target and nothing else.

Mutated guards now caught by test include: reviewer exclusion and the validator's wider exclusion;
the host verdict lowering a model PASS; host FAIL rejecting; blocking-issue resolution; the
dependency-validated requirement; issue-key forgery; operand matching; asserted-total matching;
unsupported claim forms; unknown verifier kinds; the SwarmState singleton; validator-differs-from-critic;
reviewer-differs-from-generator; shared-state classification; review role/task matching; the
review-envelope gate; the pinned-revision comparison; the reviewer scope restriction; conflict
metadata travelling with its finding; atomic admission of a conflicted pair; review history reaching
the reviewer; the canonical-representative projection; the evidence signature; canonical stability;
transitive invalidation; conflict resolution and reopening; clean-coverage denial; bounded review
attempts; validation waiting for validated dependencies; inconclusive reviews promoting nothing; the
review gap; the independence-aware selector; review scheduling itself; finding dependencies; review
tasks being branch-free; recorded tool arguments; the transitive evidence pin; exact-revision
targeting; inconclusive reviews still moving the revision; and model evidence never being recorded
as verified.

### Determinism

Consolidation, conflict detection and the shared-state projection were run over a 40-finding fixture
under eight `PYTHONHASHSEED` values and three insertion orders: **one distinct result** across all
twenty-four runs — identical duplicate groups, canonical representatives, conflicts and projected
knowledge.

The recursive graph walk that Stage 4 flagged as a latent `RecursionError` in `validate_records` was
converted to an iterative one; a 3,000-deep finding chain now validates, and a cycle in the same
chain still returns `DomainError('dependency cycle')`.

## Stage-5 integration trace

Two exploration branches, one intentionally wrong candidate, one duplicate claim from a repeated
branch, and a seeded fixture pair that each verify independently while declaring a contradiction.
Four agents: `a` and `b` explore inside their own groups, `critic` and `validator` are an ungrouped
review pool. Sequence numbers are the per-run event sequence.

```text
  31  TASK_CREATED        criticism
  32  TASK_CREATED        criticism
  40  REVIEW_STARTED      criticism
  47  REVIEW_STARTED      criticism
  56  REVIEW_COMPLETED    PASS    sum([7, 1]) = 8
  57  FINDING_CRITIQUED   PASS    sum([7, 1]) = 8
  62  REVIEW_COMPLETED    PASS    sum([6, 2]) = 8
  63  FINDING_CRITIQUED   PASS    sum([6, 2]) = 8
  68  TASK_CREATED        validation
  69  TASK_CREATED        validation
 100  REVIEW_COMPLETED    PASS    sum([7, 1]) = 8
 101  FINDING_VALIDATED   PASS    sum([7, 1]) = 8
 102  KNOWLEDGE_PROMOTED  PASS    sum([7, 1]) = 8
 107  REVIEW_COMPLETED    PASS    sum([6, 2]) = 8
 108  FINDING_VALIDATED   PASS    sum([6, 2]) = 8
 109  KNOWLEDGE_PROMOTED  PASS    sum([6, 2]) = 8
 112  CONFLICT_OPENED     left declares a contradiction with right
 143  FINDING_CREATED             sum([1, 2, 3]) = 6
 148  FINDING_CREATED             sum([10, 20]) = 99      <- intentionally wrong
 153  TASK_CREATED        criticism
 154  TASK_CREATED        criticism
 177  REVIEW_COMPLETED    PASS    sum([1, 2, 3]) = 6
 178  FINDING_CRITIQUED   PASS    sum([1, 2, 3]) = 6
 183  REVIEW_COMPLETED    PASS    sum([10, 20]) = 99      <- the critic passed it
 184  FINDING_CRITIQUED   PASS    sum([10, 20]) = 99
 189  TASK_CREATED        validation
 190  TASK_CREATED        validation
 221  REVIEW_COMPLETED    PASS    sum([1, 2, 3]) = 6
 222  FINDING_VALIDATED   PASS    sum([1, 2, 3]) = 6
 223  KNOWLEDGE_PROMOTED  PASS    sum([1, 2, 3]) = 6
 228  REVIEW_COMPLETED    FAIL    sum([10, 20]) = 99      <- the model said PASS; the host did not
 229  FINDING_REJECTED    FAIL    sum([10, 20]) = 99
 247  FINDING_CREATED             sum([1, 2, 3]) = 6      <- duplicate from the repeated branch
 264  REVIEW_COMPLETED    PASS    sum([1, 2, 3]) = 6
 265  FINDING_CRITIQUED   PASS    sum([1, 2, 3]) = 6
 284  REVIEW_COMPLETED    PASS    sum([1, 2, 3]) = 6
 285  FINDING_VALIDATED   PASS    sum([1, 2, 3]) = 6
 286  KNOWLEDGE_PROMOTED  PASS    sum([1, 2, 3]) = 6
 291  CONSOLIDATION_COMPLETED
```

Findings, with author and reviewers:

```text
  left              rev 3  VALIDATED  sum([7, 1]) = 8     author=a  reviewers=[critic, validator]
  right             rev 3  VALIDATED  sum([6, 2]) = 8     author=a  reviewers=[validator, critic]
  r:finding:000017  rev 3  VALIDATED  sum([1, 2, 3]) = 6  author=a  reviewers=[critic, validator]
  r:finding:000018  rev 3  REJECTED   sum([10, 20]) = 99  author=b  reviewers=[validator, critic]
  r:finding:000032  rev 3  VALIDATED  sum([1, 2, 3]) = 6  author=a  reviewers=[critic, validator]
```

Reviews, each targeting one exact revision, with the recorded host verdict:

```text
  criticism   PASS  target=left@1              agent=critic     verification=-
  criticism   PASS  target=right@1             agent=validator  verification=-
  validation  PASS  target=left@2              agent=validator  PASS: c1:TOOL_RESULT_ENTAILS_CLAIM
  validation  PASS  target=right@2             agent=critic     PASS: c1:TOOL_RESULT_ENTAILS_CLAIM
  criticism   PASS  target=r:finding:000017@1  agent=critic     verification=-
  criticism   PASS  target=r:finding:000018@1  agent=validator  verification=-
  validation  PASS  target=r:finding:000017@2  agent=validator  PASS: c1:TOOL_RESULT_ENTAILS_CLAIM
  validation  FAIL  target=r:finding:000018@2  agent=critic     FAIL: c1:TOOL_RESULT_CONTRADICTS_CLAIM
  criticism   PASS  target=r:finding:000032@1  agent=critic     verification=-
  validation  PASS  target=r:finding:000032@2  agent=validator  PASS: c1:TOOL_RESULT_ENTAILS_CLAIM
```

Author, critic and validator are three distinct identities for every finding, and no agent appears
twice on the same claim. The wrong candidate received a *PASS from its critic and a PASS from the
model acting as validator*; it was rejected because the recorded arithmetic result contradicted the
exact claim.

Resulting state, consolidation, conflict and coverage:

```text
shared state (r:state:000001 rev 14)
  validated   (left, r:finding:000017, right)      <- one representative per duplicate
  candidates  ()
  rejected    (r:finding:000018,)
  conflicts   (r:conflict:000014,)

consolidation
  r:finding:000017  members=(r:finding:000017, r:finding:000032)  'sum([1, 2, 3]) = 6'
  right             members=(right,)                              'sum([6, 2]) = 8'
  left              members=(left,)                               'sum([7, 1]) = 8'

conflicts
  r:conflict:000014  DECLARED_CONTRADICTION  (left, right)  OPEN

coverage
  c1: supporting=(left, r:finding:000017, r:finding:000032, right)
      conflicts=(r:conflict:000014,)  clean=False

budgets
  provider_requests=21  tool_calls=8
```

Both duplicates remain queryable as records; only one is offered as shared knowledge. Both sides of
the conflict are individually VALIDATED, and the criterion is nevertheless **not clean coverage**.

## Deviations from the architecture review and the Stage-5 brief

| # | Deviation | Class |
|---|---|---|
| 1 | Record `schema_version` bumped to 2 and stage-4 databases refused, rather than silently reinterpreting the old shape after `Assignment.context_revision` was removed. | IMPROVEMENT |
| 2 | Consolidation deduplicates the *projection* rather than transitioning duplicates. `PROPOSED → SUPERSEDED` is not a legal transition, and a duplicate is not a superseding revision. Every original identity keeps its status and stays queryable. | NEUTRAL |
| 3 | Review roles whose `Role` record is not registered for a run are not scheduled at all. Without this, every existing Stage-4 run would immediately manufacture review tasks it cannot staff. Distinct from `NO_INDEPENDENT_REVIEWER`, which is a recorded gap. | IMPROVEMENT |
| 4 | Default `ReviewPolicy.attempts_per_kind = 1`, so `INVALIDATED → CRITIQUED` revalidation needs an explicit host decision to allow a second pass. The path is implemented and tested; it is not driven automatically, because automatic re-review would silently undo a host invalidation. | NEUTRAL |
| 5 | `CONTRADICTORY_VALUE` cannot arise between two arithmetic-verified findings: the verifier refuses whichever claim its operands do not entail. It is covered deterministically at the service level, and the end-to-end conflict scenario uses the declared contradiction the brief names. This is a property of the arithmetic verifier, not a gap. | NEUTRAL |
| 6 | Conflict metadata is embedded in a finding's own context entry rather than added as a separate context section, so no truncation path can separate a claim from its contest. | IMPROVEMENT |
| 7 | A finding's `dependency_finding_ids` are set by the controller from the evidence the task *required*, not from everything its context happened to pin. Optional candidates are labelled unvalidated and are not dependencies. | NEUTRAL |
| 8 | Coverage counts every validated supporting finding, including duplicates the projection does not offer. Coverage is about the underlying knowledge, not the compact index. | NEUTRAL |
| 9 | `VALIDATED → SUPERSEDED` has no Stage-5 scheduler. Producing a revised claim belongs to the repair/cycling stage; the transition and its effect on shared knowledge are covered by test. | NEUTRAL |
| 10 | The wheel was built with an isolated build environment, which fetched a build-only `setuptools>=70.1`. The locally installed pair (setuptools 65.5.0 with wheel 0.46.1) can no longer run `bdist_wheel`. No runtime dependency was added; the package still has none. | NEUTRAL |
| 11 | `domain.py` is now 672 lines — the largest module, under the 800-line ceiling. `validate_records` was split from one 182-line function into ten focused per-type checks plus a `_Graph` helper. Splitting the record definitions from the invariants into a separate module was considered and deferred; every check needs every type. | NEUTRAL |
| 12 | Stage 4's design issues 1 (nothing adopts a `TaskRequest`), 2 (run workflow authority), 5 (NEEDS_INPUT ends in FAILED) and 6 (whole-workflow budget reservation) are untouched. They belong to later stages and Stage 5 was not authorized to open them. | RISK |

Nothing in the brief was skipped or narrowed. Item 12 is the only entry with a RISK class, and it is
a carried-forward Stage-4 risk rather than a Stage-5 decision.

## What Stage 5 revealed that should influence Stage 6

1. **The retraction payload already exists; the routing does not.** Every `FINDING_INVALIDATED` event
   carries the finding revision, the root cause, the reason, every recipient that received a message
   referencing it and every assignment that pinned it. Stage 6 should consume that record rather than
   re-derive consumers, and the delivery key `(finding_id, revision, target_task_id)` the review
   proposes maps directly onto it.

2. **The projection is the natural propagation trigger.** `KNOWLEDGE_PROMOTED` and
   `KNOWLEDGE_REMOVED` already fire exactly when the validated set changes, inside the transaction
   that changed it. Cross-pollination should hang off those two events, not off a scheduler poll.

3. **Deduplication changes what "newly promoted" means.** A duplicate claim from another branch is
   VALIDATED but is deliberately not in `SwarmState.validated_findings`. Stage 6 must decide whether
   propagation eligibility follows the finding status or the projection; propagating both members of
   a duplicate group to the same target would be a broadcast storm of one fact.

4. **Conflicts need a propagation rule of their own.** Context construction refuses to present one
   side of an open conflict as uncontested. A propagation message carries a compact insight rather
   than a context entry, so Stage 6 must decide how a conflicted claim propagates — most likely by
   propagating the conflict rather than either side.

5. **The independence pool is a real resource constraint.** Generation, criticism and validation
   consume three distinct identities per finding, and revalidation consumes a fourth. Cross-branch
   review already competes with exploration for the same agents. A run whose agent pool is sized for
   exploration alone will produce `NO_INDEPENDENT_REVIEWER` gaps rather than knowledge, and Stage 6's
   reconsideration work will add to that pressure. Budget reservation (Stage-4 issue 6) should
   probably become agent reservation as well.

6. **Cross-scope authority is now concentrated, and should stay that way.** `review.review_task` is
   the only writer of `target_finding_id` and `required_finding_ids`. Stage 6 will need to deliver
   validated findings across branches too; it should route that through an equally narrow, equally
   audited factory rather than adding a second privileged path.

7. **A review task is a Task, so `TaskRequest` adoption is now the conspicuous gap.** Stage 5 proved
   the controller can create schedulable work safely, with an explicit policy and bounded attempts.
   The same shape is what an admitted `TaskRequest` needs, and Stage 6's reconsideration cycles will
   want it.

8. **Inconclusive is a real outcome that currently just stops.** An inconclusive critique or
   validation records history, moves the revision and leaves the finding where it was. With bounded
   attempts that is a permanent stall by design. Stage 6's reconsideration loop is the natural place
   to decide whether new evidence reopens such a finding, and the attempt counter is where that
   decision has to be expressed.
