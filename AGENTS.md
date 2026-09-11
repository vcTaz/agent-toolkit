# AGENTS.md

Persistent project instructions for agents working in this repository.

This file is a **map and a set of invariants**, not a specification. The architecture itself lives in
`docs/`. Do not duplicate it here.

## What this repository is

A reusable multi-agent **swarm framework**: a distributed computational system in which agents
dynamically take on *functional* roles — exploration, criticism, validation, specialization,
consolidation, cross-pollination, synthesis, final review.

It is deliberately **not** modelled as a simulated human company with rigid job titles.

Python 3.11+, `src` layout, single async process, standard-library runtime, `unittest`.
No runtime dependencies. `setuptools` is build-only.

## Read before architectural work

1. `docs/architecture-review.md` — the full-system design and the source of truth for intent.
2. `docs/stages-1-3-report.md` — domain, persistence and execution-seam checkpoint.
3. `docs/stage-4-report.md` — scheduling, groups, messaging, bounded context, admission, budgets.
4. `docs/stage-5-report.md` — criticism, independent validation, host claim-to-evidence
   verification, promotion, invalidation, consolidation and conflicts.
5. `docs/stage-6-report.md` — deterministic cross-pollination, targeted delivery and
   retraction, reconsideration, bounded exploration cycles, branch progress and branch stopping.
6. `docs/stage-7-report.md` — the guarded run state machine, the computed synthesis gate,
   result versions and provenance, independent final review, PASS/REVISE/REJECT semantics,
   the bounded repair loop, budget and reviewer reservation, and terminal outcomes.
7. `docs/stage-8-report.md` — **latest completed checkpoint**: the runnable MVP surface —
   the scenario format and its fail-closed validation, the CLI, inspection and provenance,
   the causal trace, run metrics, the evaluation harness, packaging and the shipped examples.
8. `docs/mvp-architecture.md` — the resulting architecture as implemented, in one document.
9. `INSTRUCTIONS/kickoff-prompt-for-swarm-implementation.md` — the original brief.
10. `README.md` — the project entry point, the capability boundary and the trust boundary.

The repository, not chat history, is the source of truth for implementation state.

## Core principles

The central invariant chain:

```text
model / executor proposes
controller decides
repository commits
```

The epistemic boundary:

```text
model agreement != verification
```

The circulation rule:

```text
propagate discoveries, not transcripts
```

The completion rule:

```text
readiness is computed, never asserted
```

Everything below is a standing constraint, not a suggestion:

- **Functional roles, not simulated human organizational hierarchy.** Roles are capabilities a run
  assigns, not job titles.
- **Agent identity is separated from Role.** An agent is never permanently bound to a role; roles are
  assigned and reassigned while idle.
- **Controller-owned authoritative state.** One controller owns a run. It alone determines readiness,
  selects work, assigns agents and roles, transitions lifecycles and commits. Executors hold no
  repository handle.
- **Bounded, deliberately selected context.** Context is constructed by an explicit service with
  count and size limits, recorded selections, recorded omissions and recorded reasons. Nothing is
  injected automatically.
- **No raw transcript as shared memory.** Provider transcripts stay inside the execution seam. There
  is no broadcast address and no global chatroom. Message delivery is targeted: `agent:<id>`,
  `group:<id>` or `orchestrator`. Cross-branch knowledge moves only as a bounded insight on a
  `Propagation` naming exactly one target task — discoveries, never transcripts.
- **Dependency-aware stale-output detection.** Assignments pin everything they relied on — records
  and revisions, criterion and tool hashes, the context hash. A late or superseded result is
  rejected, never merged.
- **Controller-authorized task creation.** Models may propose a `TaskRequest`; an admitted request
  stays an inert proposal, and **generic worker `TaskRequest` adoption remains closed**. Agents do
  not spawn schedulable work. The controller alone authors schedulable work, through narrow audited
  factories — review tasks, reconsideration/follow-up tasks, repair tasks, and the synthesis and
  final-review tasks — each bounded by admissibility, task limit, budget and a duplicate check.
- **Run-level authoritative budgets.** Budgets live durably on the `Run` record and are incremented
  before the work they pay for. In-process counters are mirrors of that ledger, never a second
  authority.
- **Independent validation.** Validation is a separate pass by a different agent, not the author's
  own confidence.
- **Evidence, not model agreement.** Agreement between models is review, not proof. Validated status
  requires evidence that proves the exact claim.
- **Deterministic policies before learned or LLM-driven policies.** Readiness, selection,
  consolidation, ranking, relevance routing and admission are deterministic and inspectable
  first. Cross-pollination costs no provider request.
- **Bounded cycling and measured progress.** Exploration waves are bounded and open only when
  the controller can admit real work. A wave is charged against the limit when it is opened
  *with* admitted executable work; a wave considered but not opened costs nothing. Branch
  progress is measured from what a branch changed, never from what it claimed, and a branch
  that stops contributing is closed with a reason.
- **No model decides that a run is finished.** The synthesis gate computes readiness from
  validated, host-verified, dependency-valid, unconflicted support. `COMPLETED` is reachable
  only from `FINAL_REVIEW`, only after an independent reviewer PASS *and* a re-check of the
  gate and the citations against current state, and only in the transaction that also writes
  the accepted `Result`. `EXHAUSTED` means the system worked and the evidence or the limits
  did not suffice; `FAILED` means it could not work at all. Terminal states are absorbing.
- **A reviewed result is never edited.** Result versions are immutable; a revision creates a
  new version naming the one it supersedes, so the version a reviewer judged keeps its
  answer, its citations and its verdict.
- **No premature distributed infrastructure, vector databases or embeddings.** No hidden retries, no
  plugin frameworks, no speculative abstraction.

## Repository map

```text
INSTRUCTIONS/            original brief and stage authorization prompts
docs/                    architecture review and stage checkpoint reports
src/swarm/
  domain.py              frozen records, enums, guarded transitions
  invariants.py          snapshot invariants: references, classification, acyclicity
  schema.py              canonical field/type definitions
  serialization.py       versioned JSON round trips over a closed type registry
  persistence.py         SQLiteRepository: atomic record/event commits
  audit.py               RepositoryAudit: durable execution events and run counters
  events.py              typed event envelopes
  contracts.py           ModelProvider and Tool interfaces
  execution.py           the bounded execution seam; returns drafts only
  output.py              envelope parsing and bounded repair
  validation.py          structural validation of parsed output
  controller.py          ControllerCore: identity, transactions, execution seam, dispatch
  circulation.py         Circulation: cross-pollination, retraction, cycles, branch stopping
  engine.py              WorkEngine: admitted work driven to quiescence, no run opinion
  orchestration.py       WorkController: the run workflow over the engine
  workflow.py            the guarded run state machine and the terminal report
  completion.py          the synthesis gate: readiness, gaps, repair admissibility, reserves
  synthesis.py           controller-owned synthesis work and result admission
  finalreview.py         final-review independence, verdict semantics, repair factory
  policies.py            readiness, selection, role choice, compatibility, retry, budget
  admission.py           assignment admissibility, task-request admission
  outcomes.py            admission of permitted proposals into a transaction batch
  context.py             ContextBuilder: bounded, deterministic, auditable snapshots
  messaging.py           targeted routing and delivery snapshots
  scope.py               disclosure boundaries, fail-closed
  roles.py               data-driven role configuration and review output allowlists
  review.py              review scheduling, independence, review-envelope admission
  verification.py        host verification policies; the only writer of verified evidence
  knowledge.py           projection, consolidation, conflicts, transitive invalidation
  propagation.py         eligibility, relevance, targeted delivery, retraction, follow-up factory
  cycles.py              exploration waves, branch progress measurement, branch stopping
  scenario.py            the scenario schema, its fail-closed validation and its records
  runner.py              seeding one validated scenario and driving it to a terminal state
  cli.py                 the local command line, its exit codes and its refusals
  __main__.py            `python -m swarm`
  inspection.py          structured projections over persisted state, including provenance
  timeline.py            the causal trace, printed from an allowlist of event fields
  metrics.py             run metrics recomputed from records and durable counters
  render.py              human-readable rendering of results, inspections and traces
  evaluation.py          the deterministic evaluation harness over the packaged scenarios
  examples/*.json        the shipped demonstration scenarios
  providers/fake.py      ScriptedProvider
  providers/scripted.py  ScenarioProvider: the scenario-driven demonstration provider
  tools/arithmetic.py    tool-verifiable toy claim
tests/                   unittest suite, real SQLite, deterministic provider
```

Keep modules; split one when responsibility or size justifies it. Domain code never imports
providers, prompts or storage. Replaceable decisions stay outside the controller as plain functions
and frozen dataclasses.

## Working agreements

- Run the suite with `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
- Run a scenario with `PYTHONPATH=src python3 -m swarm run --scenario arithmetic_success`.
- Tests use real SQLite and a deterministic scripted provider. No credentials, no network.
- Do not add runtime dependencies.
- Implement only the authorized stage. Record deviations from `docs/architecture-review.md` in the
  stage report rather than silently diverging.
- Every stage leaves an importable package with a passing suite and a checkpoint report in `docs/`.

## Current status

**Stages 1–8 are complete and verified. The MVP is complete.**

**Latest completed checkpoint: `docs/stage-8-report.md`.** The architecture as implemented is
described in one place in `docs/mvp-architecture.md`; `README.md` is the project entry point.

Stage 8 passed **675 tests with 0 failures** in three environments:

- CPython 3.13.5
- CPython 3.11.9 (the declared `requires-python` floor)
- the built wheel (`swarm_foundations-1.0.0-py3-none-any.whl`), imported with `src` off the path

**37/37 meaningful single-guard mutations were caught** (0 survivors), plus one control
mutation that survived as designed. The battery found two real coverage gaps — a permission
test that asserted a problem code rather than which check produced it, and an untested
provider obligation — and both were bound by a test before being re-mutated.

Stage 8 added, on top of the Stage-7 run workflow:

- a validated, fail-closed scenario format over the canonical records
- a narrow local CLI: `run`, `validate`, `inspect`, `list-runs`, `examples`, `evaluate`
- distinct exit codes, so `COMPLETED` / `EXHAUSTED` / `FAILED` / refused are different facts
- structured inspection over persisted state, with provenance answered from records
- a causal trace printed from an allowlist of event fields, never from payloads
- run metrics recomputed from records and durable counters
- a deterministic evaluation harness that fails closed on an unknown expectation
- five shipped scenarios covering COMPLETED, EXHAUSTED, FAILED and configuration refusal
- packaging: examples inside the wheel, a `swarm` console script, no new runtime dependency

The capability boundary is now explicit and enforced at configuration time: `arithmetic` is
the only registered verification policy, and a scenario declaring a verifier kind this host
cannot implement is **refused before a run exists** rather than started and quietly
exhausted. No weak model-agreement verification was added, and generic worker `TaskRequest`
adoption remains closed.

**No post-MVP or V2 work is authorized.** A real provider adapter, general web research,
arbitrary free-text verification, semantic or embedding-based routing, vector databases,
distributed workers, durable queues, crash resume, dashboards or a UI, learned orchestration
and long-lived autonomy all stay out of scope until explicitly authorized. Candidates are
listed, in priority order, in `docs/stage-8-report.md` §16.

Do not begin V2 work without explicit authorization.
