# Canonical skills

Reusable procedures, in the [Agent Skills](https://agentskills.io) format. These are the
**source of truth**: they are not copied into any adapter, because both supported harnesses
read this format directly.

The two harness paths are **not the same shape**, and `tools/check.py` enforces the
difference. `.claude/skills/` is a **real directory whose entries are symlinks**, one per
skill, each resolving into this directory — because only a `<skill-name>` entry is documented
as symlinkable, and a symlinked container is not. `.agents/skills` **is** a container symlink,
to `../skills`. Either shape drifting is a check failure.

A skill is a method, not an identity. Roles use skills; skills do not have roles. A Critic
uses `adversarial-review` — so may an Implementer checking its own reasoning before handing
work on, and so may a lead deciding whether a teammate's report holds up.

## The seven skills

| Skill | Answers |
|---|---|
| [checkable-findings](checkable-findings/SKILL.md) | How do I report what I found so someone else can check it? |
| [adversarial-review](adversarial-review/SKILL.md) | What is wrong with this — and how is it repaired? |
| [independent-validation](independent-validation/SKILL.md) | Does this actually hold? |
| [evidence-verification](evidence-verification/SKILL.md) | Does this evidence entail this claim — and what if no check exists? |
| [final-verification](final-verification/SKILL.md) | Is the finished deliverable acceptable? |
| [evidence-backed-synthesis](evidence-backed-synthesis/SKILL.md) | How do findings become an answer that claims no more than it can carry? |
| [bounded-context-handoff](bounded-context-handoff/SKILL.md) | What should a delegated agent be given — and what do I owe what I am handed? |

The first serves the **producing** posture; the rest serve reviewing, composing and
delegating. That asymmetry was the gap the seventh closed.

## Why there are only seven

Each encodes a procedure specific to **reliable multi-agent work** that is not already well
served by the host platform. Generic engineering procedures — writing tests, reviewing a
diff, debugging, planning — belong to your harness's own skill ecosystem, not here.

There is also a mechanical reason to stay small: Codex bounds the skill list it shows the
model, shortens descriptions to fit, and omits the skills that do not fit. The bound is 2% of
the context window in tokens where the window is known, and 8,000 **characters** as a fallback
where it is not — two different quantities, not one limit stated two ways. Omission is
announced rather than silent, in a line a model can read and a human may not. Figures,
provenance and the exact constants are in
[docs/platforms/codex.md](../docs/platforms/codex.md). Seven is comfortably clear.

**The bar for an eighth:** it encodes a reliability procedure this toolkit is actually about,
and no existing skill covers it. A skill added to round out the set costs context on every
session that loads it and teaches nothing.

## Format

Each skill is a directory whose name matches its `name` frontmatter field, containing
`SKILL.md`:

```yaml
---
name: adversarial-review      # required · ≤64 chars · [a-z0-9-] · must equal the directory name
description: ...              # required · ≤1024 chars · front-load the trigger words
---
```

Descriptions are written to be matched, not admired: they lead with what the skill does, then
enumerate the situations that should trigger it. That is what makes a skill fire when it is
needed.

Optional `scripts/`, `references/` and `assets/` subdirectories are part of the specification;
none of these seven needs one.

## Where these are discovered

| Harness | Path | Mechanism |
|---|---|---|
| Claude Code | `.claude/skills/` | project skills; a real directory of per-skill entry symlinks |
| Codex | `.agents/skills/` | scanned from cwd up to the repository root; a container symlink |
| Others (Cursor, Zed, VS Code, Copilot, Gemini CLI, Goose, …) | `.agents/skills/` | the cross-client convention from the Agent Skills spec |

Every entry on both paths resolves into this directory, so there is exactly one copy of each
skill. See [docs/platforms/](../docs/platforms/).

**On Windows**, git checks symlinks out as plain text files unless `core.symlinks` is enabled
(`git clone -c core.symlinks=true`, or Developer Mode). Without it, skill discovery fails
silently on both harnesses — the entry symlinks and the container symlink alike.
`python3 tools/check.py` detects this and reports *"expected a symlink to the canonical
skills/ directory"*; the fallback is to copy `skills/` to both paths, which reintroduces
duplication the checker can no longer verify.

## Related

- [roles/](../roles/) — who uses these.
- [workflows/](../workflows/) — when.
- [docs/concepts/roles-skills-workflows.md](../docs/concepts/roles-skills-workflows.md) — how
  to tell a skill from a role from an orchestration principle.
