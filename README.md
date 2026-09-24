# Agent roles, skills and workflows

A portable library of agent roles, skills, workflows and reliability patterns for building
effective AI agent teams across Claude Code, Codex and other agentic systems.

**There is no runtime here.** Nothing to install, no framework, no language dependency. Clone
it and the roles and skills are discovered natively by both supported harnesses; read it and
the ideas transfer to any other.

> On Windows, clone with `git clone -c core.symlinks=true` — the skill directories are
> symlinks, and without that flag git writes them as plain text files and skill discovery
> fails silently. `python3 tools/check.py` detects it. See
> [skills/README.md](skills/README.md).

The thing this toolkit is actually about:

> Multi-agent systems fail by producing confident, well-cited, internally consistent answers
> that are wrong. Adding more agents does not fix that — agreement between agents is not
> evidence. What fixes it is **independence**, **verification** and **honest termination**.

---

## The five layers

```text
1  roles/            WHAT responsibility an agent assumes        canonical
   agents/           anything useful that is not a role          canonical, host-specific
2  skills/           WHAT procedure it performs                  canonical
3  workflows/        HOW roles and skills cooperate              canonical
4  docs/concepts/    WHY it is shaped this way                   reliability principles
5  .claude/ .codex/  platform adapters, and the guides to them   mechanics only
   manifest/ packs/ profile/ local/ cloud/   host integration    mechanics only
```

**Canonical** means this repository holds the authoritative definition. **Portable** means
that definition carries no harness mechanics. They are separate claims. `roles/`, `skills/`,
`workflows/` and `docs/concepts/` are both; `agents/` is canonical and deliberately
host-specific, because a host agent cannot be defined without saying how it dispatches. Layer
5 defines nothing and only attaches the rest to one harness. Portability is a review rule
rather than a check — see [docs/authority.md](docs/authority.md) and
[docs/host-integration.md](docs/host-integration.md).

### 1 · Roles

Seven, each with a distinct epistemic posture, output contract and independence requirement.

| Role | One line |
|---|---|
| [Explorer](roles/explorer.md) | Map unfamiliar territory and report what is there. |
| [Specialist](roles/specialist.md) | Apply one domain's expertise to a bounded question. |
| [Implementer](roles/implementer.md) | Change the artifact. The only role that may. |
| [Critic](roles/critic.md) | Attack the work and report what is wrong with it. |
| [Validator](roles/validator.md) | Independently determine whether a claim holds. |
| [Synthesizer](roles/synthesizer.md) | Build one answer from established support only. |
| [Final Reviewer](roles/final-reviewer.md) | Accept, revise or reject the finished deliverable. |

Critic, Validator and Final Reviewer are **not** one generic "reviewer". They ask different
questions, accept different answers, and fail in different directions — see
[independence](docs/concepts/independence.md).

### 2 · Skills

Seven reusable procedures, in the [Agent Skills](https://agentskills.io) format that both
harnesses read directly.

[`checkable-findings`](skills/checkable-findings/SKILL.md) ·
[`adversarial-review`](skills/adversarial-review/SKILL.md) ·
[`independent-validation`](skills/independent-validation/SKILL.md) ·
[`evidence-verification`](skills/evidence-verification/SKILL.md) ·
[`final-verification`](skills/final-verification/SKILL.md) ·
[`evidence-backed-synthesis`](skills/evidence-backed-synthesis/SKILL.md) ·
[`bounded-context-handoff`](skills/bounded-context-handoff/SKILL.md)

Deliberately few. Generic engineering procedures belong to your harness's own ecosystem.

### 3 · Workflows

[software-engineering](workflows/software-engineering.md) ·
[research](workflows/research.md) ·
[debugging](workflows/debugging.md) ·
[architecture](workflows/architecture.md)

Each names its roles, marks which segments are genuinely parallel and why, bounds its loops,
and states how it terminates **without** success. Each has a *scaling it down* section,
because most real tasks should use a reduced form.

### 4 · Reliability principles

[roles vs skills vs workflows](docs/concepts/roles-skills-workflows.md) ·
[independence](docs/concepts/independence.md) ·
[verification](docs/concepts/verification.md) ·
[orchestration](docs/concepts/orchestration.md) ·
[autonomy](docs/concepts/autonomy.md)

Thirty-four numbered orchestration principles, each with what it is, why it exists, and what
breaks when you ignore it.

### 5 · Platform adapters

The adapters live in `.claude/agents/` and `.codex/agents/`; these are the guides to using
them. `docs/authority.md` explains why they are separate layers.

[Claude Code](docs/platforms/claude-code.md) ·
[Codex](docs/platforms/codex.md) ·
[any other harness](docs/platforms/generic-harness.md)

---

## Using it

### With Claude Code

Open the repository. Eight subagents — the seven roles and the orchestrator — and seven
skills are discovered with no setup.

To use them in **every** project on a machine rather than only in this one, link them into
the user-level configuration once — one checkout, one copy of each definition, no project
polluted with duplicates:

```bash
./local/bootstrap.sh          # idempotent; --dry-run first if you prefer
./local/doctor.sh             # verify
```

To use them in **Claude Projects or a cloud** Claude Code session, see
[cloud/README.md](cloud/README.md). The short version: nothing in `~/.claude/` reaches
cloud, so a repository is the only route — add this one to the project and every thread
loads its agents and skills.

> Cloud behaviour here is **part measured and part not**, and the two are marked apart
> rather than averaged. Measured in Anthropic's hosted cloud environment on 2026-09-19 and
> 2026-09-20: that a project repository's `.claude/skills/` entry symlinks are followed,
> that its `permissions.deny` rules are enforced, that plugins declared in repository
> settings are **not** delivered, and that both skill packs deliver in a fresh session.
> Everything else is derived from Anthropic's documentation and from local inspection.
> Those measurements are scoped to that environment and those dates and say nothing about
> another. [cloud/SMOKE-TEST.md](cloud/SMOKE-TEST.md) is how you close the rest of the gap,
> and [docs/known-discrepancies.md](docs/known-discrepancies.md) records what has already
> been found wrong.

```text
Use the critic agent to attack the change in src/auth/.
Give it the diff and the requirement, not my reasoning about the fix.
```

The same definitions work as Agent Teams teammate types — the officially supported way to
define reusable teammate roles, since Claude Code does not read a project-level team config
file. Agent Teams is experimental and off by default; nothing here depends on it.
Compositions per workflow are in
[docs/platforms/claude-code.md](docs/platforms/claude-code.md).

### With Codex

Open the repository. `AGENTS.md` is read natively, skills are found at `.agents/skills`, and
seven project-scoped subagents are defined in `.codex/agents/`.

```text
Use the explorer agent to map src/parser/, then the critic agent — which must
not be the explorer — to attack what it found.
```

Codex enforces `sandbox_mode = "read-only"` for the six non-writing roles, which Claude Code
cannot currently do. See [docs/platforms/codex.md](docs/platforms/codex.md).

### With any other harness

Take the body of `roles/critic.md` and use it as a system prompt. That is the whole
integration — the role files are written in second person and directive precisely so this
works untransformed. See
[docs/platforms/generic-harness.md](docs/platforms/generic-harness.md).

### Using a role conceptually

You do not need any harness. The role files are readable as a specification:

> **Critic** — attacks one claim. Decides `PASS`, `CHALLENGE` or `INCONCLUSIVE`. May not be
> the author. May not fix anything, produce findings, create work, or decide the claim is
> true. Every blocking issue it raises gets a stable identifier, and is resolved only when a
> later reviewer names that exact identifier.

### Forming a team

Three to five agents. More is usually worse — coordination overhead and token cost both scale.

```text
                 Explorer   Explorer          parallel, disjoint regions,
                     │          │             no cross-talk until reports are in
                     └────┬─────┘
                          ▼
                       Critic                 attacks the findings
                          ▼
                      Validator               runs the checks itself
                          ▼
                     Synthesizer              composes from what survived
                          ▼
                   Final Reviewer
               PASS │ REVISE │ REJECT
```

The rule that carries most of the value, whatever your harness:

> **The agent that produced an artifact must not be its only reviewer.**

---

## Four terminal states, not two

```text
reached by the run's own execution and evaluation
COMPLETED    reviewed, checked, and it holds
EXHAUSTED    the work happened and the evidence or the limits did not suffice
FAILED       it could not proceed at all

imposed from outside the run
CANCELLED    stopped by something other than the run's own evaluation
```

The first three are what a run reaches by its own execution and evaluation; `CANCELLED` is
imposed from outside it. See [O22](docs/concepts/orchestration.md).

`EXHAUSTED` is the outcome most systems lack, and its absence is why they answer questions
they could not settle. It is not failure: it carries the partial result, the unresolved gaps,
and what would close them.

## Checking it

```bash
python3 tools/check.py           # structure, conformance, adapter drift, links
python3 tools/check.py --sync    # regenerate adapter bodies from roles/
```

One standard-library file, Python 3.9+, no dependencies. It verifies that every adapter
body still matches its canonical role by SHA-256, so the one duplication in the repository
cannot silently diverge. Both drift directions are proven to fail, not assumed to.

## What this is not

- **Not a runtime, framework or SDK.** No orchestration engine, no DAG executor, no workflow
  DSL, no plugin system. Specifications and small checks instead.
- **Not a guarantee.** These patterns make failures visible earlier. They do not make agents
  correct.
- **Not a claim that more agents are better.** Several workflows here tell you to use fewer.
- **Not universal.** Adapters exist for two harnesses, verified against their current
  documentation on a stated date. Everything else is a mapping you make yourself.

## Contributing

Read [`AGENTS.md`](AGENTS.md) for the invariants and [`docs/authority.md`](docs/authority.md)
for which file wins when two disagree. Run `python3 tools/check.py` before finishing.

The bar for adding a role, a skill or a workflow is deliberately high and is stated in
`AGENTS.md`. This repository is meant to get smaller and clearer, not larger.

## Lineage

These patterns were extracted from a working multi-agent runtime — a Python implementation
with an independent review pipeline, host-controlled evidence verification, deterministic
knowledge routing and a computed completion gate. The runtime was removed; the reliability
mechanisms it proved out are what remains. See [docs/lineage.md](docs/lineage.md).
