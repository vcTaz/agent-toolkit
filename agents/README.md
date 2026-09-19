# Agents

**This is where a new agent goes.** One file here, then `python3 tools/check.py --sync`.

## Roles versus agents

This repository has two agent tiers, and putting a definition in the wrong one is the
mistake this README exists to prevent.

| | `roles/` | `agents/` (here) |
|---|---|---|
| What it is | A canonical **role**: a distinct epistemic posture | Any other useful agent |
| Contract | All thirteen `REQUIRED_ROLE_SECTIONS`, in order | Frontmatter plus a body |
| Bar to add one | A distinct epistemic posture **and** a distinct output contract **and** a distinct independence requirement — all three | It is useful and nothing here already does it |
| Adapters generated | Claude Code **and** Codex | Claude Code only |
| Portability claim | Platform-neutral, enforced | None asserted |

If a definition satisfies the three-part role bar, it belongs in `roles/` and gains the
reliability guarantees described in `docs/concepts/independence.md`. If it does not, it
belongs here — and that is not a lesser thing, it is an honest one. Two of the three means
you have a *brief* for an existing role, not a new role. See `AGENTS.md`.

## Why Codex adapters are not generated here

The role layer is deliberately platform-neutral and that neutrality is checked. A free-form
agent may legitimately depend on Claude Code mechanics — a tool name, a permission, a
subagent convention. Emitting a Codex adapter for one would assert a portability nobody has
established. If an agent here *is* genuinely platform-neutral, that is the signal it may
belong in `roles/` instead.

## File format

```markdown
---
id: my-agent          # must equal the filename stem
summary: One line describing what this agent is for.
---

# My Agent

Body. This is copied verbatim into the adapter's canonical block.
```

Constraints, all enforced by `tools/check.py`:

- `id` must equal the filename stem, and must not collide with any id in `roles/`.
- `summary` is required.
- The body must not contain `'''` (it is embedded in a TOML literal string for other targets).
- **No relative Markdown links.** The body is copied into `.claude/agents/`, where a
  relative link either breaks or silently resolves to a different file. Reference other
  documents by repository-root path in backticks instead.

## Adding one

```bash
$EDITOR agents/my-agent.md
python3 tools/check.py --sync     # generates .claude/agents/my-agent.md
python3 tools/check.py            # structure, conformance, drift, links
```

The generated adapter carries its own Claude-specific frontmatter — `name`, `description`,
`tools`, `model` — which is **yours to edit by hand**. Only the region between
`<!-- canonical:begin -->` and `<!-- canonical:end -->` is regenerated. Editing inside that
block is caught as drift and overwritten by the next `--sync`.
