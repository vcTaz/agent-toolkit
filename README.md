# Swarm

A locally runnable multi-agent research and problem-solving framework, in one async Python
process with no runtime dependencies.

Agents take on **functional roles** — exploration, criticism, validation, specialisation,
consolidation, cross-pollination, synthesis, final review — assigned and reassigned by a
deterministic controller. A model never decides that a claim is true or that a run is
finished. It proposes; the controller decides; the repository commits.

```text
model / executor proposes
controller decides
repository commits
```

## What this is

- **Dynamic functional roles.** A role is a capability a run assigns to an idle agent, not a
  job title an agent is born with. All nine roles are registered; not all of them cost a
  model call.
- **Deterministic controller authority.** One controller owns a run. It alone selects work,
  assigns agents and roles, transitions lifecycles, spends budget and commits. Executors
  hold no repository handle.
- **Independent criticism and validation.** Generation, criticism and validation are three
  different agent identities, chosen before a provider request is spent.
- **Explicit evidence verification.** A finding becomes validated knowledge only when a host
  verification policy reads the authoritative recorded tool arguments and result and decides
  that they entail *the exact claim*. Model agreement is review, never proof.
- **Selective cross-pollination.** A validated discovery is routed to at most three named
  target tasks by a deterministic relevance policy, as a bounded insight — never a
  transcript, never a broadcast. Delivery is idempotent and invalidation retracts.
- **Bounded cycles.** Exploration waves are counted and limited, branch progress is measured
  from what a branch *changed*, and a branch that stops contributing is closed with a reason.
- **Computed synthesis and independent final review.** Readiness is computed from validated,
  host-verified, dependency-valid, unconflicted support. A different identity reviews the
  exact result version, and its PASS is re-checked against current state before anything
  completes.
- **Terminal outcomes a run can defend.** `COMPLETED` carries a reviewed answer and its
  provenance. `EXHAUSTED` means the system worked and the evidence or the limits did not
  suffice, and it keeps the partial knowledge and the unresolved gaps rather than dressing
  them up as an answer. `FAILED` means the run could not work at all.

## What this is not

Be clear about the boundary before trusting anything this produces.

- **Not a simulated corporate org chart.** There are no managers, no seniority and no job
  titles. Roles are capabilities, and an agent holds one only while it is doing that work.
- **Not proof that multi-agent agreement equals truth.** Agreement between models is review.
  Only an explicit host verification policy over authoritative tool evidence promotes a
  claim to validated knowledge.
- **Not arbitrary autonomous web research.** There are no browsers, search APIs or scrapers.
  Adding them without a verification policy for what they return would produce confident,
  unverifiable answers.
- **Not distributed infrastructure.** One process, one event loop, one SQLite file. No
  queues, no workers, no embeddings, no vector database.
- **Not a production agent platform yet.** The shipped provider is a deterministic scripted
  fake, the shipped verifier handles arithmetic, and there is no crash resume and no UI.

## Core architecture

```text
Objective
   → Tasks            controller-authored, dependency-aware, bounded
   → Agents           idle identities assigned a role and a bounded context
   → Findings         atomic claims with provenance and evidence
   → Criticism        an adversarial pass by a different identity
   → Validation       an independent pass, plus host verification of the exact claim
   → Consolidation    deterministic duplicate detection and explicit conflicts
   → Cross-pollination  a bounded insight to at most three named target tasks
   → Synthesis        one candidate answer built only from selected validated support
   → Final review     an independent PASS / REVISE / REJECT on one exact version
   → Result           immutable, cited, coverage recomputed by the host
```

See [docs/mvp-architecture.md](docs/mvp-architecture.md) for the architecture as
implemented, and the stage reports for the detailed history.

## Quick start

```bash
python3 -m pip install .          # or: pip install dist/swarm_foundations-1.0.0-py3-none-any.whl
python3 -m swarm examples         # what is available to run
python3 -m swarm run --scenario arithmetic_success
```

`--scenario` accepts a packaged example name, a bare file name or a path, so
`--scenario examples/arithmetic_success.json` works from a checkout and `--scenario
arithmetic_success` works from an installed wheel. A `swarm` console script is installed
alongside `python -m swarm`.

Running from the repository needs no installation at all:

```bash
PYTHONPATH=src python3 -m swarm run --scenario arithmetic_success
```

The shipped scenarios:

| Scenario | Ends | Shows |
|---|---|---|
| `arithmetic_minimal` | `COMPLETED` (exit 0) | the smallest complete loop |
| `arithmetic_success` | `COMPLETED` (exit 0) | three branches, blocking criticism, cross-pollination, a presentation revision |
| `arithmetic_exhausted` | `EXHAUSTED` (exit 1) | an unverifiable claim, bounded repair, preserved partial knowledge |
| `failed_no_decomposition` | `FAILED` (exit 2) | a run that could not work at all |
| `unsupported_verifier` | refused (exit 4) | the capability boundary, enforced before execution |

Exit codes: `0` COMPLETED, `1` EXHAUSTED, `2` FAILED, `3` CANCELLED, `4` the request was
refused, `5` a storage error. A nonzero code is an outcome, not a crash.

Every run is committed to `swarm-runs.db` in the working directory unless `--database`
names another file, so it stays inspectable after the command exits.

## Inspection

Every run is committed to SQLite and is inspectable afterwards without reading storage by
hand.

```bash
python3 -m swarm list-runs
python3 -m swarm inspect <run-id>                      # summary, coverage, provenance, metrics
python3 -m swarm inspect <run-id> --trace              # the causal timeline
python3 -m swarm inspect <run-id> --all --json         # every section, structured
python3 -m swarm inspect <run-id> --section findings   # one section at a time
```

Sections cover the run, criteria and their gate readings, tasks, agents, assignments,
groups, findings and their lifecycles, reviews, host-verified evidence, conflicts,
propagations, cycles, messages, task requests, shared state, result versions, the terminal
report, provenance, metrics, the timeline and the raw event index.

The inspection surface answers questions from **records**, not from generated prose:

- *Why was this finding validated?* — the validating review, its decision, and the host
  verification trail that authorised the promotion.
- *What evidence verified it?* — the tool, the arguments the host actually executed, and the
  result the verifier read.
- *Why did this branch receive this discovery?* — the propagation's stored relevance score
  and the exact features that produced it.
- *Why did the run become EXHAUSTED?* — the last gate evaluation with its reasons, every
  repair decision with its refusal reason, the unresolved gaps and the branch stops.
- *Which findings support the final result?* — the coverage recomputed from the citations.

Provider transcripts never leave the execution seam, and the trace prints from an allowlist
of event fields, so no context snapshot or record image is dumped into the terminal.

## Scenarios

A scenario is configuration, not a second architecture: every field is named after the
canonical record field it fills.

```json
{
  "schema_version": 1,
  "name": "arithmetic_minimal",
  "objective": "Establish the total of one integer list and report a reviewed answer.",
  "acceptance_criteria": [
    {"id": "c1", "description": "the total is correct", "verifier_kind": "arithmetic"}
  ],
  "permissions": ["arithmetic"],
  "limits": {"concurrency_limit": 2},
  "groups": [{"id": "ga", "tags": ["sums"]}],
  "agents": [{"id": "explorer-a", "group_id": "ga"}, {"id": "critic-1"}, {"id": "validator-1"}],
  "tasks": [{"id": "ta", "numbers": [1, 2, 3], "group_id": "ga",
             "acceptance_criterion_ids": ["c1"], "required_tools": ["arithmetic"]}],
  "provider": {"kind": "scripted", "final_reviews": [{"decision": "PASS"}]}
}
```

Validation refuses; it never repairs:

```bash
python3 -m swarm validate --scenario my-scenario.json
```

A scenario is rejected before any run record exists for an unknown field, an unsupported
schema version, an unsupported verifier kind, an unknown criterion, group or dependency, a
dependency cycle, a duplicate identity, an impossible permission, an invalid limit, an
unknown provider, or a task kind only the controller may author.

## Validation boundary

**Read this before believing a result.**

What can enter validated knowledge is decided entirely by the criterion's `verifier_kind`
and the verification policy registered for it. `swarm.verification.VerificationRegistry`
fails closed: a kind it does not implement is `INCONCLUSIVE`, never guessed.

The shipped trusted verifier is **arithmetic**. It reads the host-recorded tool arguments
and result, checks that the operands are the claim's own operands and that the recorded
output states they match, and only then writes `verified` evidence. A successful tool call
over other numbers proves nothing.

This is the MVP's capability boundary and it is deliberate. A scenario asking for a verifier
kind this host does not implement is **refused before it runs**, rather than started and
quietly exhausted — because a run that cannot verify its required criteria would exhaust
correctly and uselessly. Nothing here substitutes model judgement for verification in order
to make an arbitrary objective appear to work.

Adding a domain means adding a verification policy that can say what its evidence
establishes. Until then, this framework will not claim that domain's answers are validated.

## Evaluation

A small deterministic evaluation layer checks architectural properties, not phrasing:
correct terminal state, expected answer, required criteria covered, bad candidate rejected,
expected finding validated, expected propagation delivered, unrelated branch untouched,
expected final-review outcome, no invariant violations, and reproducibility across repeated
runs.

```bash
python3 -m swarm evaluate           # every packaged scenario
python3 -m swarm evaluate --json
```

Expectations live in each scenario's `expect` block. An expectation the harness does not
recognise fails closed rather than being ignored.

## Run the tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The suite uses real SQLite databases, a deterministic scripted provider and a pure
arithmetic tool. No credentials, no network.

## Entry points

- `swarm.cli` — the command line (`python -m swarm`), exit codes and refusals.
- `swarm.scenario` — the scenario schema, its fail-closed validation and its records.
- `swarm.runner` — seeding one validated scenario and driving it to a terminal state.
- `swarm.orchestration.WorkController` — the authoritative controller: the run workflow over
  the work engine.
- `swarm.engine.WorkEngine` — admitted work driven to quiescence, with no opinion about
  whether the run is finished.
- `swarm.controller.ControllerCore` — identity, transactions, the execution seam, dispatch.
- `swarm.circulation.Circulation` — cross-pollination, retraction, consolidation, cycles.
- `swarm.workflow` — the guarded run state machine and the terminal report.
- `swarm.completion` — the synthesis gate: readiness, gaps, repair admissibility, reserves.
- `swarm.synthesis` / `swarm.finalreview` — controller-owned synthesis and independent review.
- `swarm.verification` — host verification policies; the only writer of `verified` evidence.
- `swarm.knowledge` / `swarm.propagation` / `swarm.cycles` — consolidation, relevance routing
  and bounded waves.
- `swarm.persistence.SQLiteRepository` — atomic record/event commits and inspection.
- `swarm.inspection` / `swarm.timeline` / `swarm.metrics` / `swarm.render` — projections over
  persisted state and their rendering.
- `swarm.evaluation` — the deterministic evaluation harness.
- `swarm.providers.scripted.ScenarioProvider` — the scenario-driven demonstration provider.
- `swarm.tools.arithmetic.ArithmeticTool` — the tool-verifiable toy claim.

## Status

**This is the completed MVP, after Stages 1–8.** The architecture is implemented end to end
and is runnable, inspectable and evaluable from a clean install.

Documentation:

- [docs/mvp-architecture.md](docs/mvp-architecture.md) — the architecture as implemented.
- [docs/stage-8-report.md](docs/stage-8-report.md) — the MVP surface checkpoint.
- [docs/architecture-review.md](docs/architecture-review.md) — the full-system design; its
  later-stage features are deliberately not implemented.
- Stage reports: [1–3](docs/stages-1-3-report.md), [4](docs/stage-4-report.md),
  [5](docs/stage-5-report.md), [6](docs/stage-6-report.md), [7](docs/stage-7-report.md).

Deliberately out of scope for the MVP, and not implemented: a real model provider adapter,
general web research, arbitrary free-text verification, semantic or embedding-based routing,
vector databases, distributed workers, durable queues, crash resume, dashboards or a UI,
learned orchestration, and long-lived autonomy.
