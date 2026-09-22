# Claude Code

Verified against **Claude Code 2.1.278**, measured with `claude --version` in a cloud
session on 2026-09-20. This header read 2.1.269 until then, with a month and no date and no
record of how it was obtained, while five other files said 2.1.278; the number here is now a
measured one rather than the more popular one. That standard does not extend to every claim
below: **What was checked, and how** at the foot of the file gives each one its own method
and date, because running a mechanism and reading about it are not the same evidence.
Mechanisms change; if something here disagrees with the official documentation, the official
documentation is right and this file is stale.

## What this repository provides

| Layer | Path | Mechanism |
|---|---|---|
| Roles | `.claude/agents/*.md` | subagent definitions — also serve as teammate types |
| Skills | `.claude/skills/` | real directory; each entry is a symlink to the skill |
| Instructions | `CLAUDE.md` → imports `AGENTS.md` | project memory |

Nothing needs installing. Open the repository with Claude Code and all three are
discovered. On Windows, clone with `git clone -c core.symlinks=true`, or those symlinks are
checked out as text files and skills are not found.

### The skills directory is a real directory of symlinks, not a symlink

This is the single most-misdescribed thing in the repository, so it is stated exactly.

`.claude/skills/` is a **real directory**. Each `<skill-name>` entry inside it is a symlink to
the skill's own directory. Nothing is copied, so there is still exactly one copy of each skill
and no adapter layer for them — but the link is one level lower than a casual reading suggests.

The shape is not cosmetic. Anthropic documents that a *`<skill-name>` entry* in a project
skills directory may be a symlink and that Claude Code reads `SKILL.md` from the target. It
does **not** document a symlinked skills *container*. So the container stays real and the
entries do the linking, and `tools/check.py` fails if either drifts:

```text
.claude/skills/              real directory
.claude/skills/<name>   →    ../../skills/<name>      the seven canonical skills
.agents/skills          →    ../skills                container symlink (see below)
```

Measured 2026-09-20 in a cloud session: the entry symlinks are followed, and every skill this
repository carries appeared in the session's skill list. The same shape was confirmed twice
more that day against the optional pack repositories, in fresh sessions with this repository
absent — see `packs/README.md`. Third-party skills are no longer in this directory; they are
attached per Project instead, which is what that open question resolved to.

`.agents/skills` **is** a container symlink to `skills/`, for Codex and the other clients that
implement the Agent Skills convention. That asymmetry is deliberate: the Agent Skills
convention is generic about the container, and Claude Code's documentation is specific about
the entry. Do not "tidy" the two into the same shape.

## Subagents

`.claude/agents/<role>.md` is the currently supported project-level mechanism. Files are
discovered by walking up from the working directory — every `.claude/agents/` between there
and the repository root is scanned, and where more than one of them defines the same `name`,
the definition closest to the working directory wins.

Project definitions outrank `~/.claude/agents/` and plugin-supplied agents, and are themselves
outranked. The order, highest first:

```text
1  managed settings          organisation-wide
2  --agents CLI flag         that session only
3  .claude/agents/           this repository        ← where the adapters live
4  ~/.claude/agents/         that machine's user
5  a plugin's agents/        where the plugin is enabled
```

So a session launched with `--agents`, or a machine under managed settings, can supply a
different `critic` under this repository's own name, and nothing here prevents it.

The frontmatter supports eighteen fields: `name`, `description`, `tools`, `disallowedTools`,
`model`, `permissionMode`, `maxTurns`, `skills`, `mcpServers`, `hooks`, `memory`,
`background`, `omitClaudeMd`, `effort`, `isolation`, `color`, `initialPrompt` and
`experimental`. They are listed rather than counted because a bare number rots without
anyone noticing.

An adapter here carries four of them and nothing else. Only the first two are required, and
omitting either of the others is a meaningful choice rather than an oversight — see the
asymmetry below:

```yaml
name: critic              # required
description: ...          # required — this is what Claude matches when deciding to delegate
tools: Read, Grep, Glob, Bash
model: opus
```

followed by a short block of Claude-specific operating notes, then the canonical role body,
synchronised verbatim between `<!-- canonical:begin -->` markers.

### Why the bodies are copied rather than referenced

A split-pane teammate uses the definition's body **in place of** its default system prompt
(an in-process teammate has it appended). An adapter whose body said only *"read
`roles/critic.md`"* would leave a split-pane teammate with a file path as its entire
instruction set. Self-contained bodies are the correct trade, and `tools/check.py` makes the
copy verifiable rather than trusted.

### Tool and model choices, and what they do not enforce

| Role | tools | model | Why |
|---|---|---|---|
| explorer | Read, Grep, Glob, Bash | `sonnet` | breadth over many files; cost matters |
| specialist | Read, Grep, Glob, Bash | `opus` | domain reasoning is the point |
| implementer | + Edit, Write, NotebookEdit | `inherit` | the only writer; right model depends on the task |
| critic | Read, Grep, Glob, Bash | `opus` | adversarial reasoning benefits most from capability |
| validator | Read, Grep, Glob, Bash | `inherit` | largely mechanical — it runs checks |
| synthesizer | Read, Grep, Glob | `inherit` | no Bash by design: it composes, it does not investigate |
| final-reviewer | Read, Grep, Glob, Bash | `opus` | judgement against requirements |

**Honest limitation:** `Bash` can write. The read-only constraint on Explorer, Specialist,
Critic, Validator and Final Reviewer is enforced by instruction, not by the tool list, because
those roles genuinely need to run tests and inspection commands. There is no read-only `Bash`
to ask for, and `tools` cannot narrow the one there is.

Three routes enforce it rather than instruct it, and this repository takes none of them by
default:

- A **`PreToolUse` hook** on `Bash`, declared in the `hooks` frontmatter field. This is the
  mechanism built for the job — the official documentation presents it as how to allow some
  operations of a tool while blocking others, and its worked example is a read-only agent
  whose hook script exits 2 to block a write.
- A **permission mode** that prompts on writes.
- The **Codex adapters**, where `sandbox_mode = "read-only"` is enforced by the harness.

The hook is left out on purpose. It has to be an executable script that runs before every
`Bash` call a role makes, which makes it a runtime the canonical layer can observe — exactly
what the host-layer bound in `AGENTS.md` excludes, on top of that file's standing rule against
adding a runtime without a concrete need. Instruction is the weaker constraint and it is the
one this repository can honestly claim. Adopt the hook in your own project if instruction is
not enough for you.

`model: inherit` means "use the lead's model". Pinning a specific model ID would rot; the
aliases and `inherit` will not.

**Omitting `model` is not the same as `inherit`.** Established from the official subagent
documentation on 2026-09-19, a page that carries no version number of its own: the model is
resolved as the per-invocation parameter, then the definition's frontmatter, then
`CLAUDE_CODE_SUBAGENT_MODEL`, then the main conversation's model. An omitted `model`
therefore resolves to that environment variable wherever it is set. Omitting `tools` is
unambiguous by comparison — the documentation states that a definition with no `tools`
inherits every tool available to subagents.

That asymmetry decides the orchestrator's frontmatter, in `.claude/agents/orchestrator.md`.
It sets **`model: inherit`** and omits **`tools`**. `inherit` is not a pin — it names no model
and only directs the agent to the main conversation's — and it is load-bearing rather than
decorative, because under omission `CLAUDE_CODE_SUBAGENT_MODEL` would outrank the host, and an
orchestrator running on a different model from the run it holds contradicts what that agent
is. `tools` needs no such handling, because omission is documented to inherit the available
subagent tool pool. The adapter records the same reasoning beside the frontmatter it governs.

## Agent Teams

**Experimental and off by default.** Enable with:

```json
{ "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" } }
```

in `settings.json`. Teams also require an interactive session — they do not form under `-p`.

### There is no team definition file, and this repository does not ship one

Claude Code's team config is generated at runtime under `~/.claude/teams/{session}/` and holds
live state. A project-level file such as `.claude/teams/teams.json` **is not recognised as
configuration**; it would be an ordinary file that nothing reads.

The official answer is to define reusable teammate roles as **subagent definitions** — which
is exactly what `.claude/agents/` already is. One adapter serves both purposes. Team
compositions therefore live in this document as spawn prompts, not as config.

### Spawning a teammate from a role

```text
Spawn a teammate using the critic agent type to attack the change in src/auth/.
Give it the diff and the requirement, not my reasoning about the fix.
```

Claude Code applies the definition's `tools`, its `model`, and its body. One field it does
**not** apply: `skills:`. Teammates load skills from project and user settings instead —
another reason `.claude/skills` must resolve, and it does.

## Team compositions

These mirror [`workflows/`](../../workflows/). Keep teams at three to five; coordination
overhead and token cost both scale, and three focused teammates usually beat five scattered
ones.

### Software engineering

```text
Spawn three teammates:
- an implementer working only on src/parser/ — no other files
- an implementer working only on src/writer/ — no other files
- a critic, which must not be either implementer

The implementers work in parallel because they own disjoint files. When both are
done, the critic attacks each change against its requirement. Then spawn a
validator — not the critic, not either implementer — to run the checks itself.
```

### Research

```text
Spawn three teammates to investigate <question>, one per area: <A>, <B>, <C>.
They must not discuss findings with each other until all three have reported —
comparing notes early makes them converge, and convergence looks like
corroboration. When all three are in, I will consolidate duplicates, then spawn
a critic and a synthesizer.
```

### Debugging with competing hypotheses

The strongest use of teams, and the reason is structural rather than about speed.

```text
<symptom>. Reproduce it first; do not proceed until you can.

Then spawn four teammates, each investigating a different hypothesis, each in its
own context. Each must state up front what would disprove its own theory. Once all
four have reported, have them attack each other's theories — the goal is
disproof, not defence. Report which hypotheses died and what killed them.
```

Sequential investigation anchors: once one theory is explored, everything after is framed by
it. Independent contexts do not share that anchor.

### Architecture

Mostly sequential — a design must exist before it can be attacked. Use subagents rather than a
team, unless several independent design questions are genuinely open at once.

## Subagents or teammates?

| | Subagents | Teammates |
|---|---|---|
| Communication | return a result to the caller | message each other directly |
| Coordination | the lead manages everything | shared task list, self-claiming |
| Cost | lower | each is a full session |
| Right for | focused work where only the result matters | work needing discussion and challenge |

For most of this toolkit's workflows, **subagents are sufficient**. Reach for a team when
teammates need to challenge each other — competing hypotheses, or a parallel review where the
reviewers should argue.

## Enforcing independence

Independence is a property of history (see `docs/concepts/independence.md`), and Claude Code
will not enforce it for you. In practice:

- **Name your agents.** A named subagent is addressable, and you can track what it touched.
- **Never delegate a review to the agent that did the work**, and never to a fork of its
  context. A fork carries the conclusion.
- **Control what the reviewer receives.** Fresh context is necessary and not sufficient — an
  agent told the conclusion is not independent of it. See
  [`bounded-context-handoff`](../../skills/bounded-context-handoff/SKILL.md).
- **Where you cannot achieve independence, say so in the output** rather than recording a
  self-review as a review. A fresh context of the same identity is a disclosed degraded
  self-check and satisfies no criterion that requires independence; where completion requires
  an independent review and no independent identity exists, the honest terminal state is
  `EXHAUSTED`. See [`independence.md`](../concepts/independence.md).

## Known volatility

| Feature | Status |
|---|---|
| `.claude/agents/` subagents | stable, officially documented |
| `.claude/skills/` project skills | stable |
| Agent Teams | **experimental**, flag-gated, documented limitations around resumption and shutdown |
| `.claude/commands/` | legacy — skills supersede it; this repository ships none |

Nothing canonical in this repository depends on Agent Teams. If it changed tomorrow, the roles,
skills and workflows would be unaffected and only this file would need editing.

## What was checked, and how

`AGENTS.md` asks whether there is evidence outside the models, and that a claim with no check
for its kind be labelled rather than asserted. Two labels appear below and they are not
interchangeable. **Verified** means the behaviour was run here and observed, at the version
and date given. **Documented** means the official documentation states it and was read on the
date given — a primary source, but not a run.

| Claim | Status |
|---|---|
| `claude --version` reports 2.1.278 | **verified** — run 2026-09-21 |
| `.claude/agents/*.md` is discovered and all eight adapters are offered | **verified** — 2.1.278, 2026-09-21 |
| `tools:` is applied — Synthesizer is offered as `Read, Grep, Glob`, with no `Bash` | **verified** — 2.1.278, 2026-09-21 |
| The `.claude/skills/` entry symlinks are followed and all six skills **this repository carried at the time** are discovered | **verified** — cloud session 2026-09-20, re-run at 2.1.278 on 2026-09-21, when there were six |
| `checkable-findings` is discovered under its intended name and description, is invocable through the Skill tool, and invocation loads its body as active instructions | **verified** — cloud session at 2.1.278 on 2026-09-22, commit `713a61a`. `Skill(checkable-findings)` reported base directory `.claude/skills/checkable-findings` and returned the whole body; no file-reading tool touched the skill's path at any point in that session. The recorded invocation output is the evidence. The session's own recall of three body-only values is **not**, because the expected values were in the brief it was given — a defect in the gate's design, not in the run |
| The same seven are discovered **at session start**, from a clone of the branch | **not established** — that session started on `main` at `8b2b797`, which carried six skills, and the seventh entered the list only after a mid-session checkout of the branch, which the harness re-enumerated. Session-start enumeration is measured at six entries (2026-09-20, re-run 2026-09-21) and has never been measured at seven |
| Discovery scans every `.claude/agents/` between the working directory and the repository root | **verified** — 2.1.278, 2026-09-21, nested fixture |
| On a name clash the definition closest to the working directory wins | **verified** — 2.1.278, 2026-09-21, same fixture |
| `--agents` outranks a project definition of the same name | **verified** — 2.1.278, 2026-09-21, against an unflagged control run |
| The tools and model table above matches the eight adapters | **verified** — read off the adapter frontmatter, 2026-09-21 |
| The rest of the precedence order — managed settings above `--agents`, then the user directory, then plugin agents | **documented** — `sub-agents`, 2026-09-21 |
| The eighteen frontmatter fields | **documented** — `sub-agents` field table, counted 2026-09-21 |
| A `PreToolUse` hook in the `hooks` field is the route to a read-only `Bash` | **documented** — `sub-agents`, 2026-09-21 |
| A `<skill-name>` entry may be a symlink, with `SKILL.md` read from the target; a symlinked *container* is not documented | **documented** — `skills`, 2026-09-21 |
| `model` resolution order, and that omitting `model` is not `inherit` | **documented** — `sub-agents`, 2026-09-19 |
| A split-pane teammate replaces its system prompt; an in-process one has the body appended | **documented** — `agent-teams`, 2026-09-21 |
| `skills:` is not applied to teammates | **documented** — `agent-teams`, 2026-09-21 |
| Agent Teams is experimental, env-gated and interactive-only | **documented** — `agent-teams`, 2026-09-21 |
| No project-level team config file is read | **documented** — `agent-teams`, 2026-09-21 |
| The Windows `core.symlinks` caveat | **unchecked** — see below |

Three limits on this table. The **documented** rows describe intent; only the verified rows
establish that this repository's own layout is discovered. The Agent Teams page states its own
baseline — *"This page describes agent teams as of v2.1.178"* — so agreeing with it is not
evidence about 2.1.278 specifically. And exactly one step of the precedence order was run —
`--agents` over a project definition of the same name. Managed settings, `~/.claude/agents/`
and plugin agents were read rather than run; there is no managed installation, user directory
or plugin here to test the rest against.

The Windows row is unchecked in both senses. `core.symlinks` is a Git behaviour rather than a
Claude Code one, the Claude Code documentation does not address it, and no Windows checkout
has been made here. It is carried because a Windows clone that silently turns the skill
entries into text files is a real failure worth warning about, not because it was confirmed.

The verified rows were run in a cloud session with this repository as the only project
repository. Session shape can change what a repository's configuration reaches, so a result
established in one shape should not be assumed to hold in another.

### What was deliberately not carried over

The precedence order, the field set, the `PreToolUse` route and this section were recovered
from an abandoned branch, `claude/project-thread-lkr5gf`, whose copy of this file predates the
skills-layout correction. Two of its claims are superseded and were **not** reapplied: that
`.claude/skills` is a container symlink to `skills/` — see *The skills directory is a real
directory of symlinks* above, which `tools/check.py` enforces — and its header, which dated
the whole file to a documentation read, where the measured version pin at the top stands.
Anyone mining that branch again should reject the same two.
