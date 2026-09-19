# AGENTS.md

Persistent instructions for agents working in this repository.

This is a **map and a set of invariants**, not a specification and not a prompt. The
definitions live in `roles/`, `skills/` and `workflows/`. Do not duplicate them here.

## What this repository is

A platform-neutral toolkit for designing, composing and operating reliable AI agent teams. It
provides reusable agent roles, skills, workflows and reliability patterns, plus thin adapters
for Claude Code and Codex.

It contains **no runtime**. There is nothing to install, no framework, and no language
dependency. Everything here is Markdown, apart from seven TOML adapter files and one
standard-library Python script used to check structure.

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
.claude/skills    LINK    →  skills/
.agents/skills    LINK    →  skills/
.claude/settings.json  HOST  repo-scoped settings; the only channel that reaches cloud
manifest/         HOST       what is composed from elsewhere — data, never content
local/            HOST       install this toolkit into a local Claude Code config
cloud/            HOST       install it into a cloud Claude Code environment
tools/check.py               structural checks and adapter sync
```

The `CANONICAL` layer is platform-neutral and that neutrality is enforced. The `HOST` layer
is the opposite by construction: it exists to attach the canonical layer to one particular
harness, and it is excluded from every portability claim made below.

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
- **The canonical layer is portable.** Nothing in `roles/`, `skills/` or `workflows/` may
  require Claude Code, Codex, Anthropic, OpenAI, Python, a particular model or any runtime.
  Platform specifics belong in adapters or `docs/platforms/`.
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
