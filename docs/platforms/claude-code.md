# Claude Code

Verified against **Claude Code 2.1.269**, September 2026. Mechanisms change; if something
here disagrees with the official documentation, the official documentation is right and this
file is stale.

## What this repository provides

| Layer | Path | Mechanism |
|---|---|---|
| Roles | `.claude/agents/*.md` | subagent definitions — also serve as teammate types |
| Skills | `.claude/skills` → `../skills` | project skills, discovered through the symlink |
| Instructions | `CLAUDE.md` → imports `AGENTS.md` | project memory |

Nothing needs installing. Open the repository with Claude Code and all three are
discovered. On Windows, clone with `git clone -c core.symlinks=true`, or the skill
symlink is checked out as a text file and skills are not found.

### Skills are a symlink, not a copy

`.claude/skills` is a symlink to the canonical `skills/` directory. Claude Code follows it —
verified in this repository, where all six skills appear in the session's skill list. That is
why there is exactly one copy of each skill and no adapter layer for them.

`.agents/skills` is a second symlink to the same directory, for Codex and the other clients
that implement the Agent Skills convention.

## Subagents

`.claude/agents/<role>.md` is the currently supported project-level mechanism. Files are
discovered by walking up from the working directory, and project definitions take precedence
over `~/.claude/agents/` and over plugin-supplied agents.

Each adapter carries four things and nothing else:

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
those roles genuinely need to run tests and inspection commands. Claude Code has no read-only
Bash. If you need it enforced, run those roles under a permission mode that prompts on writes,
or use the Codex adapters, where `sandbox_mode = "read-only"` is actually enforced.

`model: inherit` means "use the lead's model". Pinning a specific model ID would rot; the
aliases and `inherit` will not.

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
  self-review as a review.

## Known volatility

| Feature | Status |
|---|---|
| `.claude/agents/` subagents | stable, officially documented |
| `.claude/skills/` project skills | stable |
| Agent Teams | **experimental**, flag-gated, documented limitations around resumption and shutdown |
| `.claude/commands/` | legacy — skills supersede it; this repository ships none |

Nothing canonical in this repository depends on Agent Teams. If it changed tomorrow, the roles,
skills and workflows would be unaffected and only this file would need editing.
