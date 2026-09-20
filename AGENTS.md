# AGENTS.md

Persistent instructions for agents working in this repository.

This is a **map and a set of invariants**, not a specification and not a prompt. The
definitions live in `roles/`, `skills/` and `workflows/`. Do not duplicate them here.

## What this repository is

A platform-neutral toolkit for designing, composing and operating reliable AI agent teams. It
provides reusable agent roles, skills, workflows and reliability patterns, plus thin adapters
for Claude Code and Codex.

It contains **no runtime**: no framework, no orchestration engine, and no language
dependency for *using* it — open the repository with a supported harness and the roles,
skills and workflows are discovered as they are. Nothing needs installing to use it that
way, which is the point.

That is not the same as "nothing to install", which this sentence used to say while the
same file listed `local/` as "install this toolkit into a local Claude Code config" and
pointed at `local/README.md` under "install it on a machine". The `HOST` layer is
genuinely installable and genuinely optional; see `docs/host-integration.md`. Everything here is Markdown, apart from one TOML adapter per role and `tools/`,
which holds stdlib-only Python maintenance scripts — structural checks, adapter sync, vendor
sync. Nothing reads them at use time; you run them by hand when you change something.

## Repository map

```text
roles/            CANONICAL  seven agent roles, platform-neutral
agents/           CANONICAL  free-form agents; where a new agent is added
skills/           CANONICAL  six reusable procedures, Agent Skills format
workflows/        CANONICAL  four ways roles and skills cooperate
docs/concepts/               why the canonical layer is shaped this way
docs/platforms/              how to use it on one harness
docs/authority.md            which file wins when two disagree
docs/lineage.md              where these ideas came from
.claude/agents/   ADAPTER    Claude Code subagent + teammate definitions
.codex/agents/    ADAPTER    Codex project-scoped subagents
.claude/skills/   LINKS      real directory; each entry links to skills/ or vendor/
.agents/skills    LINK    →  skills/
.claude/settings.json  HOST  repo-scoped settings; the only channel that reaches cloud
manifest/         HOST       what is composed from elsewhere — data, never content
local/            HOST       install this toolkit into a local Claude Code config
cloud/            HOST       install it into a cloud Claude Code environment
tools/check.py               structural checks and adapter sync
```

The two skills paths are **not the same shape**, and `tools/check.py` enforces the
difference. `.agents/skills` is a single container symlink to `skills/`. `.claude/skills/` is
a real directory whose *entries* are symlinks, because only a `<skill-name>` entry is
documented as symlinkable — a symlinked container is not. Its entries currently resolve into
two places: the canonical `skills/`, and `vendor/` for third-party skills committed from
pinned upstreams. Whether the vendored set stays there is an open question, not a settled
part of this map.

`CANONICAL` and `PORTABLE` are **two different claims**, and conflating them is the mistake
this section exists to prevent.

| Term | Claim |
|---|---|
| `CANONICAL` | this repository holds the authoritative definition of the concept; everything else points at it or copies it mechanically |
| `PORTABLE` | that definition carries no harness mechanics, so it translates to another harness unchanged |

`roles/`, `skills/` and `workflows/` are both. `agents/` is canonical and deliberately **not**
portable: a host agent's definition names how it dispatches, which is exactly why the tier is
separate from `roles/`. It remains the source of truth for what that agent is, and an adapter
may not redefine it.

Portability is a **review** rule, not a check. `tools/check.py` enforces structure, adapter
coverage and drift; nothing in it scans canonical text for a harness, vendor or model name.
Treat portability as reviewed rather than verified, per the expectations below.

The `HOST` layer makes neither claim. It defines no concept at all: it exists to attach the
canonical layer to one particular harness and deliver it.

## The conceptual hierarchy

Four levels. Putting a concept at the wrong one is the most common failure this toolkit
prevents.

```text
ROLE            what responsibility is an agent assuming for this assignment?
SKILL           what reusable procedure can an agent perform?
WORKFLOW        how do roles and skills cooperate toward a larger objective?
ORCHESTRATION   what rule governs the run, belonging to no single agent?
```

Not everything is an agent. Routing findings, deduplicating them and measuring progress are
**decisions, not judgements** — they need no model call and get no role. See
`docs/concepts/roles-skills-workflows.md`.

## Invariants

Standing constraints, not suggestions.

- **One conceptual definition; multiple platform adapters.** An adapter carries platform
  mechanics only. If an adapter and a canonical role disagree, the role wins and the adapter
  is defective. See `docs/authority.md`.
- **The portable layer carries no harness mechanics.** Nothing in `roles/`, `skills/` or
  `workflows/` may require Claude Code, Codex, Anthropic, OpenAI, Python, a particular model
  or any runtime. Platform specifics belong in adapters, in `docs/platforms/`, or — for a
  host agent, which cannot be defined without them — in `agents/`. Canonical and portable are
  separate claims; see the repository map above and `docs/authority.md`.
- **The agent that produced an artifact is not its only reviewer.** Critic, Validator and
  Final Reviewer are three distinct roles with distinct questions, vocabularies and exclusions.
  Do not collapse them.
- **`model agreement != verification`.** Agreement between agents is review. A claim is
  established only when evidence outside the models is checked against it — and an unknown
  claim kind fails closed rather than being guessed.
- **Readiness is computed, never asserted.** No agent decides that work is finished.
- **`EXHAUSTED` is not `FAILED`.** The first means the work happened and the evidence or the
  limits did not suffice; the second means it could not proceed at all. A process that cannot
  produce the first will report success on everything.
- **Propagate discoveries, not transcripts.** Delivery is targeted and bounded; there is no
  broadcast.
- **Progress is measured from what changed, not from what was claimed.**
- **Prefer a deterministic decision to a model call.**
- **One artifact, one owner.** Parallelise only genuinely independent work.

Full catalogue: `docs/concepts/orchestration.md`.

## Verification expectations

Before treating any claim in this repository as established — including a claim about a
platform mechanism:

1. Is there evidence outside the models, or only agreement between them?
2. Were the evidence's inputs this claim's own subject?
3. Does the output entail the claim *as stated*, not a weaker neighbour?
4. If no check exists for this kind of claim, is it labelled **reviewed** rather than verified?

Platform documentation in `docs/platforms/` states the date and version it was verified
against. Anything not verified against official documentation must say so.

## Contribution guidance

**Run `python3 tools/check.py` before finishing.** It requires Python 3.9+ and no
dependencies, and checks role structure, Agent Skills conformance, adapter coverage and
drift, symlink targets and link resolution. It fails closed on anything it cannot classify.

- **Editing a role:** edit `roles/<id>.md`, then `python3 tools/check.py --sync`, then
  `python3 tools/check.py`. Never edit inside a `canonical:begin` block or a TOML
  `developer_instructions` string.
- **Adding a role** requires a distinct epistemic posture, a distinct output contract **and**
  a distinct independence requirement. Two out of three means you have a *brief* for an
  existing role, not a new role.
- **Adding an agent** requires all four parts of the admission test in `agents/README.md`.
  That tier is exceptional: failing the role bar is not by itself a qualification for it, and
  most things that fail it are briefs, orchestration principles or adapter concerns.
- **Adding a skill** requires that it encode a reliability procedure this toolkit is about and
  that no existing skill covers it. Generic engineering procedures belong to the host
  platform's own ecosystem. Skill lists are context-budgeted and silently truncated on some
  harnesses, so every addition costs the others.
- **Adding a workflow** requires a genuinely different *shape* of cooperation, not a different
  subject. A workflow that adds a role without giving it something the other roles cannot do
  is theatre.
- **Do not add** a runtime, an orchestration engine, a plugin framework, a workflow DSL, a
  prompt compiler, a dependency, or CI configuration, without a concrete need.
  The `HOST` layer is the one recorded exception, and its concrete need is stated in
  `docs/host-integration.md`. It remains bounded: shell and JSON only, no new language
  dependency, no runtime the canonical layer can observe, and nothing in `roles/`,
  `agents/`, `skills/` or `workflows/` may reference it.
- **Do not add legacy instruction files** — `.cursorrules`, `.windsurfrules`, `AGENT.md`,
  `.rules` and similar. Some harnesses resolve project instructions by first match and would
  never reach this file.

## Where to start

| You want to | Read |
|---|---|
| understand the model | `docs/concepts/roles-skills-workflows.md` |
| use a role | `roles/README.md`, then the role |
| run a team | `workflows/README.md` |
| use this with Claude Code | `docs/platforms/claude-code.md` |
| use this with Codex | `docs/platforms/codex.md` |
| use this with anything else | `docs/platforms/generic-harness.md` |
| add an agent | `agents/README.md` |
| install it on a machine | `local/README.md` |
| use it with cloud Claude Code | `cloud/README.md` |
| understand the host layer | `docs/host-integration.md` |
| change something safely | `docs/authority.md` |
