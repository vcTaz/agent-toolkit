# Agents

**This is where a new agent goes.** One file here, then `python3 tools/check.py --sync`.

Currently one agent lives here: `agents/orchestrator.md`, the host agent that holds a run.
Every principle in `docs/concepts/orchestration.md` is addressed to it, and five of the seven
roles defer to it, so it was referenced throughout the canonical layer long before it was
defined.

Beside it is its registry, `agents/registry.json`: what each canonical definition — every
role, skill, workflow and this agent — **may do** in this organisation. It is **not a
definition** and is not loaded as one: `tools/check.py` reads only `*.md` here as agents. It
holds values from closed vocabularies and nothing a definition already says, and its ceilings
are written in `tools/check.py` rather than in the file, so that no edit to the registry alone
can widen what anything may do. The reasoning is in `docs/concepts/autonomy.md`.

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
coverage and drift, and nothing in it scans for a harness or vendor name. The host-layer
invariant is the one canonical-text rule it does compute. See `docs/authority.md`.

## Roles versus agents

This repository has two agent tiers, and putting a definition in the wrong one is the
mistake this README exists to prevent.

| | `roles/` | `agents/` (here) |
|---|---|---|
| What it is | A canonical **role**: a distinct epistemic posture | A canonical **host agent**: an identity the harness runs |
| Contract | All thirteen `REQUIRED_ROLE_SECTIONS`, in order | Frontmatter plus a body |
| Bar to add one | A distinct epistemic posture **and** a distinct output contract **and** a distinct independence requirement — all three | The four-part admission test below — all four |
| Adapters generated | Claude Code **and** Codex | Claude Code only |
| Canonical | yes — the authoritative definition | yes — the authoritative definition |
| Portable | yes — no harness mechanics | no — may name its harness, by design |

If a definition satisfies the three-part role bar, it belongs in `roles/` and gains the
reliability guarantees described in `docs/concepts/independence.md`. Two of the three means
you have a *brief* for an existing role, not a new role. See `AGENTS.md`.

Failing the role bar is **not** by itself a qualification for this tier. Most things that
fail it are briefs, deterministic mechanisms or adapter concerns, and each of those has a
home already.

## The admission test

This is an exceptional tier, not a drawer for custom agents. A definition is admitted only
when **all four** of these hold. Any one of them failing sends it somewhere else, and that
somewhere else already exists.

**A · It needs a host-side identity with its own lifecycle.** Something has to *be* this
agent for a stretch of the run — spawned, held, ended. An existing role pointed at a
different subject is a brief, and a brief travels in the dispatch, not in a file here.

**B · Nothing else in the repository can carry it.** Work the classification in
`docs/concepts/roles-skills-workflows.md` before reaching for this tier. If it is a rule about
the run as a whole, or decidable without a model, it is an orchestration principle. If several
roles would each want to perform it, it is a skill. If it is a shape of cooperation, it is a
workflow. If it is identifiers, tool limits or operating notes, it is an adapter. Only what
survives all of those arrives here.

**C · Its semantics must be defined once, and it cannot be described without harness
mechanics.** This is the pairing the tier exists for, and it is why an entry is canonical but
not portable. Define it once so no adapter can redefine it; accept that part of what it does
can only be said in one harness's terms. If the definition turns out to need no harness
mechanics at all, it was a role.

**D · It creates a system responsibility that nobody currently holds.** Not a new name for
work already owned. Ask what the system can no longer do if this file is deleted; if the
answer is "nothing, the work just moves", it is a persona.

### The orchestrator against the test

| | |
|---|---|
| **A** | The run is held by one identity for its whole duration. That is a lifecycle, not a brief. |
| **B** | The principles it enforces are orchestration; the identity that enforces them is not a rule and cannot be one. No role, skill or workflow owns dispatch. |
| **C** | `O1` to `O34` must mean the same thing on every harness, while dispatching can only be described in one harness's terms — subagent or teammate, team size, tool surface. |
| **D** | Before it existed, the orchestration principles were addressed to an identity this repository never defined. Delete the file and that hole returns. |

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
