# Agents

**This is where a new agent goes.** One file here, then `python3 tools/check.py --sync`.

Currently one lives here: `agents/orchestrator.md`, the host agent that holds a run. Every
principle in `docs/concepts/orchestration.md` is addressed to it, and five of the seven roles
defer to it, so it was referenced throughout the canonical layer long before it was defined.

## Canonical is not the same claim as portable

These two words describe different things, and the tier only makes sense once they are apart.

| Term | Claim |
|---|---|
| **Canonical** | this repository holds the authoritative definition. An adapter may add mechanics; it may never redefine. |
| **Portable** | that definition carries no harness mechanics, so it translates to another harness unchanged. |

A definition here is **canonical but not portable**. That is not a weaker status, it is a
different one: `agents/orchestrator.md` is the single source of truth for what the
orchestrator is, and a Claude Code adapter that described it differently would be defective,
exactly as a defective role adapter would be. What it does not claim is that it would survive
a move to another harness unchanged, because a host agent's definition has to say how it
dispatches.

Portability is a review rule rather than a check: `tools/check.py` enforces structure, adapter
coverage and drift, and nothing in it scans for a harness or vendor name. See
`docs/authority.md`.

## Roles versus agents

This repository has two agent tiers, and putting a definition in the wrong one is the
mistake this README exists to prevent.

| | `roles/` | `agents/` (here) |
|---|---|---|
| What it is | A canonical **role**: a distinct epistemic posture | Any other useful agent |
| Contract | All thirteen `REQUIRED_ROLE_SECTIONS`, in order | Frontmatter plus a body |
| Bar to add one | A distinct epistemic posture **and** a distinct output contract **and** a distinct independence requirement — all three | It is useful and nothing here already does it |
| Adapters generated | Claude Code **and** Codex | Claude Code only |
| Canonical | yes — the authoritative definition | yes — the authoritative definition |
| Portable | yes — no harness mechanics | no — may name its harness, by design |

If a definition satisfies the three-part role bar, it belongs in `roles/` and gains the
reliability guarantees described in `docs/concepts/independence.md`. If it does not, it
belongs here — and that is not a lesser thing, it is an honest one. Two of the three means
you have a *brief* for an existing role, not a new role. See `AGENTS.md`.

## Why Codex adapters are not generated here

The role layer is deliberately portable. A free-form agent may legitimately depend on Claude
Code mechanics — a tool name, a permission, a subagent convention — and the orchestrator does.
Emitting a Codex adapter for one would assert a portability nobody has established, and would
carry another harness's mechanics into a file written against this one. If an agent here *is*
genuinely free of harness mechanics, that is the signal it may belong in `roles/` instead.

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
