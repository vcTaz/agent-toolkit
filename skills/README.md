# Canonical skills

Reusable procedures, in the [Agent Skills](https://agentskills.io) format. These are the
**source of truth**: they are not copied into any adapter, because both supported harnesses
read this format directly. `.claude/skills` and `.agents/skills` are links to this directory.

A skill is a method, not an identity. Roles use skills; skills do not have roles. A Critic
uses `adversarial-review` — so may an Implementer checking its own reasoning before handing
work on, and so may a lead deciding whether a teammate's report holds up.

## The six skills

| Skill | Answers |
|---|---|
| [adversarial-review](adversarial-review/SKILL.md) | What is wrong with this? |
| [independent-validation](independent-validation/SKILL.md) | Does this actually hold? |
| [evidence-verification](evidence-verification/SKILL.md) | Does this evidence entail this claim — and what if no check exists? |
| [final-verification](final-verification/SKILL.md) | Is the finished deliverable acceptable? |
| [evidence-backed-synthesis](evidence-backed-synthesis/SKILL.md) | How do findings become an answer that claims no more than it can carry? |
| [bounded-context-handoff](bounded-context-handoff/SKILL.md) | What exactly should a delegated agent be given? |

## Why there are only six

Each encodes a procedure specific to **reliable multi-agent work** that is not already well
served by the host platform. Generic engineering procedures — writing tests, reviewing a
diff, debugging, planning — belong to your harness's own skill ecosystem, not here.

There is also a mechanical reason to stay small: Codex caps the skill list it shows the model
at 2% of the context window (or 8,000 characters), shortens descriptions first, and **silently
omits skills past that**. A large skill library loses its tail without saying so. Six is
comfortably clear.

**The bar for a seventh:** it encodes a reliability procedure this toolkit is actually about,
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
none of these six needs one.

## Where these are discovered

| Harness | Path | Mechanism |
|---|---|---|
| Claude Code | `.claude/skills/` | project skills |
| Codex | `.agents/skills/` | scanned from cwd up to the repository root |
| Others (Cursor, Zed, VS Code, Copilot, Gemini CLI, Goose, …) | `.agents/skills/` | the cross-client convention from the Agent Skills spec |

Both paths in this repository are links to this directory, so there is exactly one copy.
See [docs/platforms/](../docs/platforms/).

## Related

- [roles/](../roles/) — who uses these.
- [workflows/](../workflows/) — when.
- [docs/concepts/roles-skills-workflows.md](../docs/concepts/roles-skills-workflows.md) — how
  to tell a skill from a role from an orchestration principle.
