# Stage 8 checkpoint — the runnable MVP surface

Date: 2026-09-10. Status: implemented and verified. Completes the MVP. Extends
`docs/stage-7-report.md`; supersedes nothing.

Stages 1–7 built a system that could reach a terminal outcome it could defend. Stage 8 makes
that system something a person can actually run, watch, and interrogate afterwards:

```text
install package
   → run a complete swarm scenario
   → observe the run
   → receive a terminal result
   → inspect why it completed or exhausted
   → reconstruct the agent / task / finding / review / propagation flow
```

The demonstration executes **the architecture built in Stages 1–7**. There is no Stage-8
orchestration path: `runner.execute_scenario` seeds records and hands them to the same
`WorkController` the Stage-7 suite drives, and every terminal state below was written by
`workflow.advance` under the same guards.

---

## 1. The product decision this stage makes explicit

The MVP does **not** claim trustworthy arbitrary free-text research, and it does not pretend
to. `VerificationRegistry` implements one policy — arithmetic — and fails closed on every
other `verifier_kind`.

Stage 7 named the consequence: *a criterion Stage 8 cannot verify is `SUPPORT_UNVERIFIED`
forever, and the run exhausts, correctly but uselessly.* Stage 8 makes the decision
explicitly, in three places:

1. **Configuration is refused early.** A scenario declaring a verifier kind this host does
   not implement is rejected before any run record exists, with the supported kinds named.
   A run that could only ever exhaust is never started.
2. **No weak generic verification was added.** No "the reviewers agreed" path, no
   confidence threshold, no LLM-as-judge substitute. The epistemic boundary is the same one
   Stage 5 drew.
3. **The boundary is documented where a user meets it** — the README's *Validation
   boundary* section, `swarm run --scenario unsupported_verifier`, and the refusal message
   itself.

`unsupported_verifier.json` is a shipped example whose whole purpose is to be refused:

```text
$ python -m swarm run --scenario unsupported_verifier
status       REJECTED — the configuration was refused before any run existed
1 problem(s):
  UNSUPPORTED_VERIFIER_KIND
    at acceptance_criteria[0].verifier_kind
    'prose' has no verification policy; supported kinds: arithmetic
exit 4
```

## 2. The CLI

Six narrow commands, no framework.

```text
python -m swarm run       --scenario NAME [--run-id ID] [--trace] [--full] [--database PATH] [--json]
python -m swarm validate  --scenario NAME [--json]
python -m swarm inspect   RUN_ID [--section NAME ...] [--all] [--trace] [--full] [--database PATH] [--json]
python -m swarm list-runs [--database PATH] [--json]
python -m swarm examples  [--json]
python -m swarm evaluate  [--scenario NAME ...] [--database PATH] [--json]
```

`swarm` is also installed as a console script. `--scenario` accepts a packaged example name,
a bare file name or a path, so one documented command works from a checkout and from an
installed wheel.

### Exit codes

A terminal outcome is information, not a crash. The code says which outcome it was:

| Code | Meaning |
|---|---|
| 0 | `COMPLETED` — a reviewed answer the gate still held for |
| 1 | `EXHAUSTED` — the system worked; the evidence or the limits did not suffice |
| 2 | `FAILED` — the run could not work at all |
| 3 | `CANCELLED` |
| 4 | the request was refused: an invalid scenario, an unknown run, an unknown section |
| 5 | a storage error |

`FAILED` and `EXHAUSTED` have different codes *and* different explanations in the rendered
output, because conflating them is exactly the mistake the architecture spent seven stages
avoiding.

### What the CLI is not allowed to do

`cli.py` and `runner.py` contain no scheduling, no admission, no gate and no transition. The
only run-affecting call in the whole surface is `WorkController.run_until_idle`. This is
checked by a test, not asserted in a comment.

## 3. The scenario format

A scenario is *configuration*, not a second architecture in JSON. Every field carries the
name of the canonical record field it fills, so `Run`, `Criterion`, `AgentGroup`, `Agent`
and `Task` are described in one vocabulary whether in Python or in a file.

```json
{
  "schema_version": 1,
  "name": "arithmetic_minimal",
  "description": "...",
  "objective": "Establish the total of one integer list and report a reviewed answer.",
  "acceptance_criteria": [
    {"id": "c1", "description": "the total is correct",
     "verifier_kind": "arithmetic", "required": true}
  ],
  "permissions": ["arithmetic"],
  "limits": {"concurrency_limit": 2},
  "roles": {"allowed_tools": ["arithmetic"], "review_tools": ["arithmetic"]},
  "groups": [{"id": "ga", "tags": ["sums"]}],
  "agents": [{"id": "explorer-a", "group_id": "ga", "permissions": ["arithmetic"]},
             {"id": "critic-1"}, {"id": "validator-1"}],
  "tasks": [{"id": "ta", "numbers": [1, 2, 3], "group_id": "ga", "tags": ["sums"],
             "acceptance_criterion_ids": ["c1"], "required_tools": ["arithmetic"],
             "dependency_ids": [], "priority": 0, "required": true}],
  "provider": {"kind": "scripted", "final_reviews": [{"decision": "PASS"}]},
  "expect": {"terminal_state": "COMPLETED"}
}
```

`limits` accepts exactly the `Run` limit fields — `provider_request_limit`,
`tool_call_limit`, `concurrency_limit`, `task_limit`, `assignment_attempt_limit`,
`cycle_limit`, `no_progress_limit`, `repair_round_limit`, `presentation_revision_limit`,
`synthesis_attempt_limit`, `execution_timeout` — plus `deadline_seconds`, which is derived
into `deadline_at` at seeding time and is the only field that is not a `Run` attribute.

`numbers` is the one convenience: it fills a task's `description` with the operands the
arithmetic demonstration provider reads, and is refused alongside an explicit `description`.

`expect` is inert during a run and is read only by `swarm evaluate`.

### Validation refuses; it never repairs

Every problem is reported, not just the first, and no field is defaulted for something the
author got wrong.

| Refusal | Code |
|---|---|
| a field this schema does not define | `UNKNOWN_FIELD` |
| a schema version this host does not read | `UNSUPPORTED_SCHEMA_VERSION` |
| a required field that is absent | `MISSING_FIELD` |
| no criteria, duplicate ids, or none required | `NO_ACCEPTANCE_CRITERIA`, `DUPLICATE_CRITERION_ID`, `NO_REQUIRED_CRITERION` |
| a verifier kind with no registered policy | `UNSUPPORTED_VERIFIER_KIND` |
| a task naming a criterion the run does not declare | `UNKNOWN_CRITERION` |
| a task naming a group or dependency that does not exist | `UNKNOWN_GROUP`, `UNKNOWN_DEPENDENCY` |
| a self-dependency or a dependency cycle | `SELF_DEPENDENCY`, `DEPENDENCY_CYCLE` |
| a repeated task, agent or group identity | `DUPLICATE_TASK_ID`, `DUPLICATE_AGENT_ID`, `DUPLICATE_GROUP_ID` |
| a tool the host does not register | `UNKNOWN_TOOL` |
| permissions no identity could exercise | `IMPOSSIBLE_PERMISSIONS` |
| fewer than two unbranched identities where work exists | `NO_REVIEW_CAPACITY` |
| a limit below what the run machinery accepts | `INVALID_LIMIT` |
| a provider kind or provider field this host does not configure | `UNKNOWN_PROVIDER_KIND`, `UNKNOWN_FIELD` |
| a scripted verdict outside the admissible set | `INVALID_REVIEW_DECISION`, `INVALID_RECONSIDERATION_OUTCOME` |
| a task kind only the controller may author | `CONTROLLER_OWNED_TASK_KIND` |

Two of these deserve their own note.

**`CONTROLLER_OWNED_TASK_KIND`** carries the authority boundary into configuration. A
scenario may declare `exploration`, `specialization` and `collaboration` work. Criticism,
validation, reconsideration, follow-up, repair, synthesis and final review are authored by
the controller alone, and a configuration file is not a way around that.

**`NO_REVIEW_CAPACITY`** exists because criticism and validation of one finding need two
identities that are neither the author nor each other. A scenario with fewer can never
validate anything it discovers, which is a run that cannot work rather than a run that
failed to find evidence.

The version is checked *before* the shape: a document written against another schema would
otherwise be reported as a pile of unknown fields, which explains nothing.

## 4. The demonstration provider

`providers/scripted.ScenarioProvider` answers registered roles from the scenario's own
`provider` block. It is openly a fake and can promote nothing: a claim it makes reaches
validated knowledge only if the arithmetic tool, read by the host verifier, entails that
exact claim — which is why a scenario can script a *wrong* answer and watch the boundary
reject it.

Role dispatch is by exact match against the registered role instructions rather than by
guessing at a prefix, so a role whose instructions change is a hard failure here instead of
a silently mis-scripted run.

```json
"provider": {
  "kind": "scripted",
  "claims":    {"tb": 99},
  "critiques": [{"claim_contains": "[10, 20]", "decision": "CHALLENGE",
                 "blocking_issues": ["..."]}],
  "repairs":   {"c2": {"numbers": [10, 20], "total": 99}},
  "reconsideration": {"outcome": "NO_CHANGE", "reason": "..."},
  "synthesis": [{"omit_support_matching": "[4, 5]"}],
  "final_reviews": [{"decision": "REVISE", "criterion_ids": ["c1"]}, {"decision": "PASS"}]
}
```

`UNREPORTED` cannot be scripted: it is host-recorded, and the configuration validator says so.

## 5. The shipped scenarios

| Scenario | Ends | Exercises |
|---|---|---|
| `arithmetic_minimal` | `COMPLETED` (0) | the smallest complete loop |
| `arithmetic_success` | `COMPLETED` (0) | three branches, blocking criticism, cross-pollination, reconsideration, a presentation revision |
| `arithmetic_exhausted` | `EXHAUSTED` (1) | an unverifiable required claim, bounded repair, preserved partial knowledge |
| `failed_no_decomposition` | `FAILED` (2) | a run that could not work at all |
| `unsupported_verifier` | refused (4) | the capability boundary before execution |

### The successful run

`arithmetic_success` runs three branches over two criteria. Branches A and C investigate
`c1` independently — which is what makes the run cross-pollinate, because A's validated
total is relevant to C's task and to nothing in branch B. Branch B's claim is challenged by
criticism with a blocking issue that validation has to resolve. The first synthesis is
scripted to omit one supported total, the first final review returns `REVISE` naming `c1`,
the controller classifies the defect as presentation from the record, and the second version
passes.

```text
seq  event                      ids                 detail
 26  CYCLE_STARTED                                  number=1 trigger=INITIAL
 28  RUN_STATE_CHANGED                              RECEIVED -> DECOMPOSING
 29  RUN_STATE_CHANGED                              DECOMPOSING -> EXPLORING
 34  TASK_ASSIGNED              ta   explorer-a
 40  TASK_ASSIGNED              tc   explorer-c
 59  FINDING_CREATED            ta   explorer-a     f5  PROPOSED  c1
 64  FINDING_CREATED            tc   explorer-c     f6  PROPOSED  c1
 93  REVIEW_COMPLETED           t7   critic-1       criticism PASS on f5@1
 99  REVIEW_COMPLETED           t8   judge-1        criticism PASS on f6@1
137  REVIEW_COMPLETED           t13  judge-1        validation PASS; PASS: c1:TOOL_RESULT_ENTAILS_CLAIM
138  FINDING_VALIDATED          f5
139  KNOWLEDGE_PROMOTED         f5
144  REVIEW_COMPLETED           t14  critic-1       validation PASS; PASS: c1:TOOL_RESULT_ENTAILS_CLAIM
145  FINDING_VALIDATED          f6
152  CROSS_POLLINATION          -> tc               score=3  CRITERION:c1, TAG:sums
154  CROSS_POLLINATION          -> ta               score=3  CRITERION:c1, TAG:sums
158  TASK_ASSIGNED              tb   explorer-b
169  FINDING_CREATED            tb   explorer-b     f22 PROPOSED  c2
186  REVIEW_COMPLETED           t23  critic-1       criticism CHALLENGE; 1 blocking issue
206  REVIEW_COMPLETED           t26  judge-1        validation PASS; resolved 1 blocking key
207  FINDING_VALIDATED          f22
213  RUN_STATE_CHANGED                              EXPLORING -> EVALUATING
214  RUN_STATE_CHANGED                              EVALUATING -> CONSOLIDATING
220  CYCLE_STARTED                                  number=2 trigger=NEW_KNOWLEDGE
227  RUN_STATE_CHANGED                              CONSOLIDATING -> EXPLORING (follow-up work)
228  PROPAGATION_DELIVERED      -> tc
229  PROPAGATION_DELIVERED      -> ta
252  RECONSIDERATION_COMPLETED  -> tc               NO_CHANGE: the branch rechecked its own evidence
257  RECONSIDERATION_COMPLETED  -> ta               NO_CHANGE
262  RUN_STATE_CHANGED                              EXPLORING -> EVALUATING
263  RUN_STATE_CHANGED                              EVALUATING -> CONSOLIDATING
269  SYNTHESIS_GATE_EVALUATED                       READY  support=[f5, f6, f22]
271  SYNTHESIS_STARTED          t34                 AUTHORIZED attempt=1
272  RUN_STATE_CHANGED                              CONSOLIDATING -> SYNTHESIZING
284  RESULT_CREATED             r36  critic-1       version=1  cites 2 of 3
290  RUN_STATE_CHANGED                              SYNTHESIZING -> FINAL_REVIEW
302  FINAL_REVIEW_COMPLETED     rv39 judge-1        REVISE on version 1; criterion c1
306  SYNTHESIS_GATE_EVALUATED                       READY
307  RESULT_REVISION_REQUESTED                      revision_kind=PRESENTATION  PRESENTATION_ONLY
309  RUN_STATE_CHANGED                              FINAL_REVIEW -> SYNTHESIZING
311  SYNTHESIS_STARTED          t40                 AUTHORIZED attempt=2  + bounded feedback
323  RESULT_CREATED             r42  critic-1       version=2  cites 3 of 3, supersedes r36
329  RUN_STATE_CHANGED                              SYNTHESIZING -> FINAL_REVIEW
340  FINAL_REVIEW_COMPLETED     rv45 judge-1        PASS on version 2
344  SYNTHESIS_GATE_EVALUATED                       READY  (re-checked before COMPLETED)
346  RUN_COMPLETED                                  result=r42  stop_reason=FINAL_REVIEW_PASS
347  RUN_STATE_CHANGED                              FINAL_REVIEW -> COMPLETED
```

```text
COMPLETED   requests=21/80 tools=6/120 tasks=15 findings=3v/0r reviews=8
            propagations=2 cycles=2/3 results=2 repairs=0 revisions=1
answer      sum([1, 2, 3]) = 6; sum([4, 5]) = 9; sum([10, 20]) = 30
coverage    c1 required <- f5, f6      c2 required <- f22
```

The synthesizer identity (`critic-1`, holding the SYNTHESIZER role for that assignment) and
the final reviewer (`judge-1`) are different identities, chosen before any provider request
was spent. Both roles were taken by agents that had earlier held CRITIC and VALIDATOR roles
on unrelated work — which is the point of separating identity from role.

### The exhausted run

`arithmetic_exhausted` is the same graph with branch B scripted to assert
`sum([10, 20]) = 99`, and with a repair strategy that repeats it.

```text
seq  event                      detail
206  REVIEW_COMPLETED           validation: model PASS, host FAIL
                                FAIL: c2:TOOL_RESULT_CONTRADICTS_CLAIM
207  FINDING_REJECTED           f22 — the reviewer agreed; the evidence did not
212  RUN_STATE_CHANGED          EXPLORING -> EVALUATING
213  RUN_STATE_CHANGED          EVALUATING -> CONSOLIDATING
219  COVERAGE_GAP               cycle 1: c2 UNSUPPORTED
227  RUN_STATE_CHANGED          CONSOLIDATING -> EXPLORING (reconsideration work)
262  RUN_STATE_CHANGED          EXPLORING -> EVALUATING
269  COVERAGE_GAP               cycle 2: c2 UNSUPPORTED
270  SYNTHESIS_GATE_EVALUATED   NOT_READY — the gap is still repairable
274  REPAIR_WORK_CREATED        admitted  c2 (UNSUPPORTED)  round 1
                                repair_key=GATE#c2#UNSUPPORTED
276  RUN_STATE_CHANGED          CONSOLIDATING -> EXPLORING (repair admitted by the gate)
317  TASK_ASSIGNED              the repair task -> validator-1 as a SPECIALIST
329  REVIEW_COMPLETED           validation: model PASS, host FAIL — again
330  FINDING_REJECTED           f41 — the repair repeated the same unverifiable claim
335  RUN_STATE_CHANGED          EXPLORING -> EVALUATING
336  RUN_STATE_CHANGED          EVALUATING -> CONSOLIDATING
341  BRANCH_TERMINATED          ga NO_PROGRESS (keeps its validated finding)
343  BRANCH_TERMINATED          gb NO_PROGRESS
345  BRANCH_TERMINATED          gc NO_PROGRESS (keeps its validated finding)
348  COVERAGE_GAP               cycle 3: c2 UNSUPPORTED
349  SYNTHESIS_GATE_EVALUATED   EXHAUSTED  CRITERION_UNSUPPORTED: c2
350  REPAIR_WORK_CREATED        refused   c2 (UNSUPPORTED)  CYCLE_LIMIT
351  RUN_EXHAUSTED              REQUIRED_CRITERION_UNRESOLVED: CRITERION_UNSUPPORTED: c2
352  RUN_STATE_CHANGED          CONSOLIDATING -> EXHAUSTED
```

Two things in that trace are the whole point of the stage. At 206 and 329 the *model*
returned PASS and the host refused it, because the recorded tool result contradicted the
claim's own asserted total — model agreement did not survive contact with evidence. And at
270 the gate says NOT_READY rather than EXHAUSTED, because repair was still admissible; it
says EXHAUSTED at 349 only once the cycle limit makes further repair impossible.

```text
EXHAUSTED   requests=22/80 tools=8/120 tasks=14 findings=2v/2r reviews=8
            propagations=2 cycles=3/3 results=0 repairs=1 revisions=0
stop reason REQUIRED_CRITERION_UNRESOLVED: CRITERION_UNSUPPORTED: c2
validated partial knowledge   sum([1, 2, 3]) = 6 ; sum([4, 5]) = 9
unresolved criteria           c2  UNSUPPORTED  required
branches stopped              ga: NO_PROGRESS, gb: NO_PROGRESS, gc: NO_PROGRESS
```

No `Result` was ever created, `run.result_id` is `None`, and the rendered output says in
plain words that the knowledge shown is partial and is not an answer. Exit code 1.

### The failed run

`failed_no_decomposition` declares a required criterion and an empty task graph. The MVP has
no decomposer, so `DECOMPOSING → EXPLORING` is refused by the `decomposed` guard and the run
is `FAILED` at configuration, having spent zero provider requests.

```text
RUN_STATE_CHANGED   RECEIVED -> DECOMPOSING     configuration validated
RUN_FAILED          NO_ADMITTED_WORK: NO_TASKS
RUN_STATE_CHANGED   DECOMPOSING -> FAILED
```

```text
FAILED  requests=0/80 tools=0/120

FAILED means the run could not work at all — a configuration, storage or provider-contract
problem. This is not EXHAUSTED, which means the system worked and the evidence or the limits
did not suffice.
```

An empty task graph is legal *configuration* on purpose. Refusing it in the validator would
have hidden the distinction the architecture cares about: a malformed document and a run
that cannot work are different failures, and only the second one is a run at all.

## 6. Inspection

`swarm inspect` projects persisted state; it never composes an explanation. Twenty-two
sections are available:

```text
run          criteria     result       results      outcome      metrics
tasks        agents       assignments  groups       findings     reviews
evidence     conflicts    propagations cycles       messages     task_requests
state        provenance   timeline     events
```

The default view is summarised — `run`, `criteria`, `result`, `outcome`, `metrics`,
`provenance` — because §8 of the brief is right that a terminal report is not a record dump.
`--section` selects, `--all` shows everything, `--json` emits the same structure.

Two things are deliberately withheld. Provider transcripts never leave the execution seam,
so there is nothing to print. A context snapshot is represented by its hash and its
selected/omitted identities rather than reproduced, because an inspection surface is not a
dump of a run's inputs.

### The five provenance questions

| Question | Answered from |
|---|---|
| Why was this finding validated? | the validating `ReviewRecord`, its decision, and its recorded host verification trail |
| What evidence verified it? | the `Evidence` the host wrote: tool name, the arguments actually executed, the result the verifier read |
| Why did this agent receive this finding? | the `Assignment`'s pinned `propagation_ids`, and the `Propagation` decision itself |
| Why was this propagation sent to this branch? | the stored `score` and `matched_features` on the decision |
| Why did the run become EXHAUSTED? | the last `SYNTHESIS_GATE_EVALUATED` with its reasons, every `REPAIR_WORK_CREATED` refusal with its reason, the `TerminalReport` gaps and the branch stops |
| Which findings support the final result? | `Result.coverage`, recomputed by the host from the citations |

```text
findings:
  ...:finding:000005  VALIDATED
    claim: sum([1, 2, 3]) = 6
    task ta by explorer-a  criteria c1
    why: validated by ...:review:000017 (PASS: c1:TOOL_RESULT_ENTAILS_CLAIM)
    verified: arithmetic({"expected":6,"numbers":[1,2,3]}) -> {"actual": 6, "matches": true}

propagations:
  ...:propagation:000019  INSIGHT  CONSUMED
    ...:finding:000005@1 -> tc  (score 3 from CRITERION:c1; TAG:sums)
    answered NO_CHANGE: the branch rechecked its own evidence
```

### The trace

`--trace` renders the durable event log in causal order — the per-run monotonic `sequence`
*is* the causal order — showing sequence, event type, the identifiers needed for deeper
inspection, and a one-line summary.

The summary is built from an **allowlist** of detail keys. Every other key is reported by
shape (`gaps[2]=…`) or not at all, and `RECORD_CHANGED` is excluded from both the core
narrative and the `--full` detail set, because its payload carries whole before/after record
images. `--full` adds execution-seam bookkeeping (context selection, provider requests, tool
calls); it still prints no transcript.

## 7. Metrics

`metrics.py` recomputes everything from committed records and the run's own durable
counters, so a metric cannot disagree with the state it describes. Nothing is incremented as
a side effect of doing work.

```text
terminal_state stop_reason duration_seconds
provider_requests/limit    tool_calls/limit    cycles_charged/limit
repair_rounds  presentation_revisions  synthesis_attempts
tasks{total, by_kind, PENDING…CANCELLED}      task_requests
assignments{total, CREATED…CANCELLED}         agents{total}
groups{total, active, closed}
findings{total, candidates, PROPOSED…SUPERSEDED}
reviews{total, criticism, validation, final, verified_evidence}
propagations{total, SELECTED…RETRACTED, insights, retractions}
reconsiderations{APPLIED, NO_CHANGE, FOLLOW_UP_REQUESTED, UNREPORTED}
conflicts{total, open, resolved}   cycles{total, open, closed}
results{versions, CANDIDATE…SUPERSEDED}   messages   records   events
```

## 8. Evaluation

`swarm evaluate` runs the packaged scenarios and checks *architectural properties*, not
phrasing. Expectations live in each scenario's `expect` block, beside the configuration they
describe.

| Check | What a regression would look like |
|---|---|
| `terminal_state`, `exit_code` | a run that stops somewhere else, or reports it wrongly |
| `answer_contains` | the answer stops presenting what it validated |
| `criteria_covered` | a criterion stops being cleanly covered |
| `validated_claims` | a claim that should promote stops promoting |
| `rejected_claims`, `no_rejected_findings` | a bad candidate stops being rejected by evidence |
| `propagated_to`, `not_propagated_to` | routing becomes broadcast, or stops routing |
| `reconsiderations_reported` | a delivery stops being answered by its branch |
| `blocking_criticism` | criticism stops blocking, or validation stops resolving |
| `final_review_decisions` | the review sequence changes |
| `result_versions`, `no_result` | a revision stops creating a new version |
| `gaps`, `stop_reason_contains`, `repair_attempted` | an exhaustion stops explaining itself |
| `invariants` | any snapshot invariant breaks |
| `provenance_reconstructible` | a validated claim stops naming host-verified evidence |
| `determinism` (with `--repeat`) | hidden ordering creeps in |

Two harness properties matter as much as the checks:

- **An unknown expectation fails closed.** A silently ignored expectation would quietly
  reduce coverage every time a scenario is edited.
- **A scenario with no expectations is reported**, not passed.

Scenarios that are invalid *by design* cannot carry their own expectations, because
validation refuses them before `expect` is ever read. Those few are listed in
`evaluation.REJECTIONS` with the problem codes their refusal must produce.

## 9. Reproducibility

`evaluation.normalise` strips the values that legitimately differ between two runs of the
same scenario — wall-clock moments, and the digests computed over per-execution tool-result
identifiers (`context_hash`, `progress_signature`, evidence `reference`) — and substitutes
the run identity, so two runs can be compared as documents.

Record identities are already deterministic (`{run_id}:{kind}:{serial}`), so they compare
equal after substitution rather than being erased. A test asserts that normalisation is not
so aggressive that two *different* terminal states compare equal.

`ReproducibilityTests` runs the completing and the exhausting scenarios twice each and
asserts identical normalised reports across run, criteria, results, findings, reviews,
propagations, cycles, outcome and provenance. `swarm evaluate --repeat N` adds the same
check to the suite.

## 10. Packaging

```text
swarm_foundations-1.0.0-py3-none-any.whl
```

`pyproject.toml` gained `[project.scripts] swarm = "swarm.cli:main"` and
`[tool.setuptools.package-data] "swarm.examples" = ["*.json"]`, so the scenarios ship inside
the wheel and `swarm run --scenario arithmetic_success` works from a clean install with no
repository checkout. `swarm.examples.resolve` accepts a name, a bare file name or a path, so
one documented command works in both places.

No runtime dependency was added; `setuptools` remains build-only. `requires-python` is
unchanged at `>=3.11`.

## 11. Verification

### Test suite

**675 tests, 0 failures**, in three environments:

| Environment | Result |
|---|---|
| CPython 3.13.5 | 675 tests, OK |
| CPython 3.11.9 (the declared `requires-python` floor) | 675 tests, OK |
| the built wheel `swarm_foundations-1.0.0-py3-none-any.whl`, imported with `src` off the path | 675 tests, OK |

Stage 8 added 217 tests across five modules and one fixture module:

```text
tests/stage8_support.py            scenario documents, CLI capture, a per-process run cache
tests/test_stage8_scenario.py      acceptance, every refusal category, provider contract  (70)
tests/test_stage8_inspection.py    sections, provenance, timeline, metrics, rendering  (39)
tests/test_stage8_cli.py           commands, exit codes, refusals, output safety  (38)
tests/test_stage8_integration.py   the shipped scenarios, end to end  (38)
tests/test_stage8_evaluation.py    the harness fed wrong observations  (32)
```

The Stages 1–7 suites are unchanged and still pass unmodified.

### Guards checked by mutation, not assumed

A single-guard mutation battery replaces one check at a time with its no-op and runs the
Stage-8 suite against the mutant. **37/37 meaningful mutations were caught; 0 survived.**

```text
scenario.py             20  verifier kind, controller-owned task kinds, schema version,
                            unknown fields, duplicate criteria/tasks/agents/groups, the
                            required-criterion rule, self dependencies, unknown
                            dependencies, dependency cycles, unknown criterion references,
                            unknown tools, run/agent/task permissions, branch worker and
                            reviewer capacity, limit minimums, provider kind, conflicting
                            task fields
providers/scripted.py    4  provider config validation, the reconsideration outcome set,
                            the final-review decision set, answering only consumable
                            deliveries
inspection.py            3  the finding lifecycle reason, verified-evidence filtering,
                            criterion readiness
evaluation.py            4  unknown expectations, invariant checking, normalisation,
                            missing expectation blocks
timeline.py              2  the detail-key allowlist, record images in the trace
render.py                2  the FAILED/EXHAUSTED distinction, the partial-knowledge label
cli.py                   1  unknown inspection sections
runner.py                1  distinct terminal exit codes
```

A 38th entry is a **control**: a comment-only edit to `runner.py`, which SURVIVED as
intended. Without it a battery reporting 37/37 would be indistinguishable from one that
cannot detect a survivor at all.

The battery found **two real coverage gaps**, and both were bound by a test before being
re-mutated:

1. `scenario.py:task-tool-permission-unchecked` survived because the test asserted that
   `IMPOSSIBLE_PERMISSIONS` appeared *somewhere*, and the later capacity analysis raises the
   same code for the same task from a different path. Removing the task-level check
   therefore changed nothing the test could see. The three permission tests now assert the
   exact `(code, path)` list, which distinguishes *which* check is doing the refusing.
2. `providers/scripted.py:consumable-delivery-unchecked` survived because no test covered
   the provider's obligation to answer only the deliveries an assignment was asked to
   consume. That is not fixture politeness: the host refuses such an envelope outright
   (`RECONSIDERATION_TARGET_INELIGIBLE` in `admission._check_reconsiderations`), so a
   provider that answered everything in its context would fail the assignment. Four
   `ProviderBehaviourTests` now pin that contract, including the exact-match role dispatch.

Mutations that touch modules other than `scenario.py` were re-run after each test addition,
so every verdict above was produced against the shipped source *and* the shipped suite.

### Evaluation

```text
5 scenarios, 47 checks, 0 failures

arithmetic_exhausted      EXHAUSTED         12 checks   PASS
arithmetic_minimal        COMPLETED         11 checks   PASS
arithmetic_success        COMPLETED         15 checks   PASS
failed_no_decomposition   FAILED             8 checks   PASS
unsupported_verifier      CONFIG_REJECTED    1 check    PASS
```

Run three times each, the completing, revising and exhausting scenarios all produce a single
distinct normalised report.

### Determinism

### Packaging verification

```text
wheel built              swarm_foundations-1.0.0-py3-none-any.whl
installed into a clean venv, src off the path
package import smoke     swarm, swarm.cli, swarm.scenario, swarm.runner,
                         swarm.inspection, swarm.evaluation, swarm.orchestration
packaged examples found  5, under site-packages/swarm/examples
module invocation        python -m swarm examples  ✓
console script           swarm examples            ✓
CLI success scenario     swarm run --scenario arithmetic_success     exit 0
CLI exhausted scenario   swarm run --scenario arithmetic_exhausted   exit 1
CLI failed scenario      swarm run --scenario failed_no_decomposition exit 2
CLI refused scenario     swarm run --scenario unsupported_verifier   exit 4
evaluation suite         swarm evaluate    5 scenarios, 47 checks, exit 0
full test suite          675 tests, OK, with PYTHONPATH=tests only
```

The wheel was rebuilt from the final source, installed into an empty virtual environment,
and every check above was run from that environment with the repository's `src/` off
`sys.path` — asserted, not assumed.

### Repository

```text
src/swarm/      9,846 lines across 43 modules   (largest: domain.py at 705,
                                                then scenario.py at 612)
tests/          8,185 lines across 28 modules
examples/       5 packaged scenarios
wheel           swarm_foundations-1.0.0-py3-none-any.whl (148 KB)
```

## 12. Repository tree

```text
AGENTS.md
CLAUDE.md
README.md
pyproject.toml
INSTRUCTIONS/
  kickoff-prompt-for-swarm-implementation.md
  implementation-prompt-stages-1-3.md
docs/
  architecture-review.md          the full-system design
  mvp-architecture.md             the architecture as implemented
  stages-1-3-report.md            domain, persistence, execution seam
  stage-4-report.md               scheduling, groups, messaging, context
  stage-5-report.md               criticism, validation, verification, consolidation
  stage-6-report.md               propagation, reconsideration, cycles, branches
  stage-7-report.md               gate, synthesis, final review, terminal outcomes
  stage-8-report.md               this checkpoint
  superpowers/plans/              two early planning notes, kept as history
src/swarm/
  __init__.py  __main__.py
  domain.py invariants.py schema.py serialization.py validation.py
  persistence.py audit.py events.py contracts.py
  execution.py output.py
  controller.py circulation.py engine.py orchestration.py
  workflow.py completion.py synthesis.py finalreview.py
  policies.py admission.py outcomes.py context.py messaging.py scope.py roles.py
  review.py verification.py knowledge.py propagation.py cycles.py
  scenario.py runner.py cli.py
  inspection.py timeline.py metrics.py render.py evaluation.py
  providers/__init__.py  providers/fake.py  providers/scripted.py
  tools/__init__.py      tools/arithmetic.py
  examples/__init__.py
  examples/arithmetic_minimal.json
  examples/arithmetic_success.json
  examples/arithmetic_exhausted.json
  examples/failed_no_decomposition.json
  examples/unsupported_verifier.json
tests/
  stage5_support.py stage6_support.py stage7_support.py stage8_support.py
  test_domain.py test_persistence.py test_execution.py test_audit_integration.py
  test_stage4_controller.py test_stage4_services.py
  test_stage5_controller.py test_stage5_review.py test_stage5_verification.py
  test_stage6_controller.py test_stage6_guards.py test_stage6_propagation.py
  test_stage6_reconsideration.py
  test_stage7_gate.py test_stage7_synthesis.py test_stage7_review.py
  test_stage7_workflow.py test_stage7_repair.py test_stage7_integration.py
  test_stage8_scenario.py test_stage8_cli.py test_stage8_inspection.py
  test_stage8_evaluation.py test_stage8_integration.py
```

## 13. Deviations from the Stage-8 brief

| # | Deviation | Class |
|---|---|---|
| 1 | `SQLiteRepository.runs()` was added. `inspect <run-id>` needs an index; a host cannot be asked to remember an identity the CLI generated. It is a read over stored `Run` records and writes nothing. | NEUTRAL |
| 2 | The scenario validator refuses `verifier_kind` values with no registered policy, which the brief made optional ("reject configuration … or terminate with the explicit non-success status"). Early rejection was chosen, as the brief preferred. | IMPROVEMENT |
| 3 | `CONTROLLER_OWNED_TASK_KIND` was added beyond the brief's list. The brief asked for fail-closed validation of unknown roles; a scenario hand-authoring a `synthesis` or `final_review` task would have been a configuration route around controller authority. | IMPROVEMENT |
| 4 | `NO_REVIEW_CAPACITY` was added. A scenario with fewer than two unbranched identities can never validate anything it discovers; refusing it is the difference between "cannot work" and "found no evidence". | IMPROVEMENT |
| 5 | An **empty task graph is accepted** by the validator, and the run then FAILS at `DECOMPOSING → EXPLORING`. This is how the `FAILED` demonstration is expressible without adding any new architecture, and it keeps the malformed-document and cannot-work failures distinct. | NEUTRAL |
| 6 | Six CLI commands rather than the two or three sketched. `validate`, `examples` and `evaluate` are each a few lines over shared machinery, and `validate` is what makes the fail-closed boundary usable rather than only testable. | NEUTRAL |
| 7 | Six exit codes rather than "nonzero on failure". `EXHAUSTED`, `FAILED`, `CANCELLED`, a refused request and a storage error are different facts, and collapsing them would undo the distinction Stage 7 built. | IMPROVEMENT |
| 8 | The scenario carries an optional `expect` block. The brief put evaluation expectations in the harness; keeping them beside the configuration they describe makes a fixture one file, and the harness fails closed on an expectation it does not know. | NEUTRAL |
| 9 | `providers/scripted.ScenarioProvider` is a second fake provider rather than an extension of `providers/fake.ScriptedProvider`. The existing one is an ordered response script used by unit tests; the new one is role-dispatched and data-driven. Merging them would have made both worse. | NEUTRAL |
| 10 | The trace prints from an allowlist of event detail keys rather than rendering payloads. Event details legitimately contain proposals, context snapshots and record images; an inspection surface that dumps them is a leak, not a feature. | IMPROVEMENT |
| 11 | Version bumped to 1.0.0 and `__init__` rewritten, since the MVP is complete. The record `schema_version` is unchanged at 4: Stage 8 added no record type and no record field. | NEUTRAL |
| 12 | No module was split. `domain.py` (705) remains the largest and is still the obvious next split candidate; Stage 8 added no lines to it. Stage-8 modules are 39–609 lines. Splitting was not needed to keep this stage's work clean, and the brief asked for behaviour preservation over cosmetic refactoring. | RISK |
| 13 | A presentation revision's review feedback reaches the next result version's `limitations`, because the controller supplies feedback through `Task.limitations` and `admit_result` falls back to those when the synthesizer proposes none. The rendered output therefore shows a repaired complaint as a limitation of the accepted answer. Stage-7 behaviour, preserved rather than redesigned; see §15. | RISK |

Nothing in the brief was skipped or narrowed. Items 12 and 13 are the RISK entries.

## 14. What was deliberately not done

The brief was explicit, and so is this list. None of the following exists in the shipped
code:

- **No real provider adapter.** The provider interface is unchanged and ready for one; no
  OpenAI or other API client was written.
- **No web research.** No browser, no search API, no scraping, no external fetch.
- **No weak generic verification.** No model-agreement path into validated knowledge.
- **No generic `TaskRequest` adoption.** An admitted request is still an inert proposal, and
  a test asserts that no run produced schedulable work outside the controller's factories.
- **No broad refactor.** Behaviour was preserved; no Stage 1–7 module was restructured.

## 15. Known limitations

These are MVP boundaries, stated rather than hidden.

1. **Arithmetic is the only trusted verification policy.** Everything the system can
   *validate* is an integer-sum claim in the form `sum([a, b, c]) = t`. Every other domain
   needs a verification policy before its findings can mean anything here.
2. **The demonstrated provider is a deterministic fake.** It proves control flow, not
   answer quality. Nothing in this repository has ever called a real model.
3. **No arbitrary free-text objectives.** Acceptance criteria must be supplied; there is no
   decomposer that turns prose into criteria, and inventing them would quietly weaken the
   gate.
4. **No crash resume.** `_open_run` refuses to adopt a run with unfinished assignments.
   Persistence offers inspection, not resumption.
5. **No distributed workers, durable queues, or multi-process execution.** One event loop,
   one SQLite file.
6. **No semantic routing, embeddings or vector database.** Relevance is a deterministic
   score over criteria, dependencies and controlled tags.
7. **No UI.** The surface is a CLI and a JSON projection.
8. **No untrusted tool sandbox.** Tools are pure, trusted, local functions. Async deadlines
   are cooperative and do not isolate arbitrary Python.
9. **Concurrency is bounded by the identity pool.** Independence needs distinct identities
   per finding, plus a held-back final reviewer once completion is near, so a small pool can
   make "nothing dispatched" look like "nothing to do". The scenario validator refuses the
   worst case; it does not size the pool from the task graph.
10. **A repaired complaint can survive as a recorded limitation.** See deviation 13: the
    controller's bounded feedback travels on `Task.limitations`, and a synthesizer that
    proposes no limitations of its own gets those recorded on the new version. The record is
    accurate about what happened; the *label* is misleading.
11. **A repair task does not see what was already tried.** Stage 7 observed this; Stage 8
    did not change it. The repair task names the gap, not the rejected attempts, so a
    deterministic branch repeats itself until the sameness check or a limit stops it.

## 16. Recommended V2 priorities

In the order that would make the next stage most useful, and with the reason each one is
next rather than merely desirable.

1. **One real provider adapter, then a second.** The whole architecture is provider-neutral
   by construction and has never been tested against a provider that is not deterministic.
   The second adapter is what proves the first did not leak.
2. **A second verification policy.** This is the real limit on what a run can do. A
   fixture-lookup or unit/dimension policy would show that the epistemic boundary generalises
   without weakening it.
3. **Criteria from prose, validated rather than trusted.** DECOMPOSING needs the treatment
   criticism and validation got: a proposal the controller checks against something. Stage 7
   built the check (`completion.gap_records`); Stage 8's free-text runs are the first
   consumer with a reason to want it.
4. **`TaskRequest` adoption, bounded the way repair is.** The last unopened work path. A
   repair task already proves the shape: a triggering record, a named criterion, a bounded
   scope, a round number, a duplicate key and a recorded refusal reason.
5. **Show a repair task the failed approaches.** The projection already computes them.
6. **Crash resume, or an explicit unfinished-run recovery command.** Persistence is
   complete enough; the missing piece is a decision about what an interrupted assignment
   means.
7. **Human input and approval pauses.** The workflow already has guarded states to pause in.
8. **Then, and only with measured need:** semantic relevance, richer consolidation,
   distributed workers, a timeline UI.

---

Stage 8 is complete, and with it the MVP. A package installs, a scenario validates, a swarm
runs, trusted evidence controls what may be believed, cross-pollination stays selective, the
synthesis gate stays deterministic, the final review stays independent, `COMPLETED` is
trustworthy under the configured verifier, `EXHAUSTED` is reported honestly, and every run
is inspectable and reconstructible from what it committed.
