# Codex

Verified against OpenAI Codex documentation and codex-cli 0.153.4, September 2026.
Mechanisms change; if something here disagrees with the official documentation, the official
documentation is right and this file is stale.

## What this repository provides

| Layer | Path | Mechanism |
|---|---|---|
| Instructions | `AGENTS.md` | natively read, no configuration needed |
| Skills | `.agents/skills` → `../skills` | repo-scoped skill discovery |
| Roles | `.codex/agents/*.toml` | project-scoped custom subagents |

Nothing needs installing. Open the repository with Codex and all three are discovered.
On Windows, clone with `git clone -c core.symlinks=true`, or the skill symlink is checked
out as a text file and skills are not found.

## AGENTS.md

Codex builds an instruction chain at startup: the global file in the Codex home directory
first, then every `AGENTS.md` from the project root down to the working directory,
**concatenated root-down**, with later files overriding earlier guidance by position.

Two consequences shape how this repository's `AGENTS.md` is written:

- **32 KiB hard cap across the whole chain** (`project_doc_max_bytes`). Codex stops adding
  files once the combined size reaches it — silently, from the reader's perspective. This
  repository's `AGENTS.md` is deliberately a map and a set of invariants, not a prompt, and
  stays well inside that budget so it does not crowd out a consuming project's own files.
- **Additive layering, not nearest-file-wins.** A nested `AGENTS.md` adds to what came before
  rather than replacing it. Write guidance that layers.

`AGENTS.md` is stewarded by the Agentic AI Foundation under the Linux Foundation, not by any
vendor, which is why it is this toolkit's primary instruction substrate rather than a
Codex-specific adapter.

## Skills

Codex scans **`.agents/skills`** in every directory from the working directory up to the
repository root, alongside user-level and system locations. `.agents/skills` here is a symlink
to the canonical `skills/` directory; Codex follows symlinked skill folders.

This is not a path invented for Codex. The Agent Skills specification names `.agents/skills/`
as the cross-client interop directory, and roughly forty clients implement it — which is why
the skills in this repository need no adapter for any of them.

Each skill's `SKILL.md` carries `name` (matching its directory) and `description`.
`tools/check.py` enforces both, plus the specification's length and slug constraints.

### One thing worth knowing about scale

Codex bounds the skill list it shows the model, shortens descriptions to fit, and **omits
skills past the bound**. Read from `codex-rs/ext/skills/src/render.rs` in `openai/codex` at
tag `rust-v0.153.4` (commit `3d2ee51c`, 2026-09-04), which is the release this file is
verified against:

| Constant | Value | Effect |
|---|---|---|
| `SKILL_METADATA_CONTEXT_WINDOW_PERCENT` | `2` | the budget is 2% of the context window, **in tokens**, when the window is known |
| `DEFAULT_SKILL_METADATA_CHAR_BUDGET` | `8_000` | the fallback budget, **in characters**, used only when the window is *not* known |
| `MAX_CONFIGURED_SKILL_METADATA_TOKEN_BUDGET` | `10_000` | ceiling on an explicitly configured token budget |
| `MAX_CATALOG_SKILL_DESCRIPTION_CHARS` | `1_024` | each description is truncated to this before budgeting |

The two figures are **not two ways of saying the same limit**: 2% is a token budget, 8,000
characters is the fallback when there is no context window to take a percentage of, and
`skill_metadata_budget()` chooses between them in that order.

Omission is **not silent**. `omission_marker()` emits `- N additional skills omitted from
this bounded skills list.` into the rendered list, and the render report emits *"Exceeded
skills context budget. All skill descriptions were removed and N additional skills were not
included in the model-visible skills list."* A large library still loses its tail; it says
so, in a line the model can read and a human may not.

**Status: this is a primary artifact, read, not run.** The constants and the branch order are
what the source says at that tag. Nothing here was measured by executing Codex.

Seven skills is comfortably clear of the bound — and that constraint is part of why this
toolkit ships few skills with front-loaded descriptions rather than many.

## Subagents

Custom agents are standalone TOML files under `.codex/agents/` for project scope (or
`~/.codex/agents/` for personal). Subagent workflows are enabled by default in current
releases.

```toml
name = "critic"                       # required — this, not the filename, is the identifier
description = "..."                   # required — guidance for when to use it
model_reasoning_effort = "high"
sandbox_mode = "read-only"
developer_instructions = '''...'''    # required — the canonical role body, synced
```

**`sandbox_mode` is a real enforcement**, and it is where Codex is stronger than Claude Code
for this toolkit: the six read-only roles genuinely cannot write. Only `implementer` is
`workspace-write`.

`model` is deliberately unset. Pinning a model ID would rot; reasoning effort will not.

### This format is explicitly unsettled

OpenAI's own documentation says these files are loaded as configuration layers for spawned
sessions, that this "can feel heavier than a dedicated agent manifest", and that **the format
may evolve as authoring and sharing mature**.

That is why `.codex/agents/` is a generated adapter here and not a canonical format. If it
changes, `tools/check.py --sync` regenerates seven small files and nothing else in the
repository is affected.

Two further constraints worth knowing: subagents inherit the parent's sandbox and approval
policy — a role file cannot durably raise its own privileges — and delegation is
prompt-driven. There is no declarative always-route-X-to-Y table.

## What this repository deliberately does not ship

| Not shipped | Why |
|---|---|
| `.codex/config.toml` | Project config is **trust-gated**: it is inert until the user marks the repository trusted, and it silently ignores provider, profile and telemetry keys. A committed file that may or may not apply is worse than none. |
| `~/.codex/prompts/` entries | Custom prompts are **officially deprecated** in favour of skills, have no project-scoped form, and have been dropped from the current slash-command reference. |
| `.codex/rules/*.rules` | Self-labelled experimental. |
| MCP server definitions | This toolkit has no MCP dependency. A consuming project should define its own. |

## Team composition

Codex delegation is prompt-driven, so team composition is a matter of how you ask. The
[`workflows/`](../../workflows/) files describe the shapes; name the agent types in your
request:

```text
Use the explorer agent to map src/parser/ and the specialist agent for the
encoding question. When both report, use the critic agent — it must not be
either of them — to attack the findings.
```

Since `name` rather than the filename identifies a custom agent, a file here named
`explorer.toml` **overrides Codex's built-in `explorer`** within this project. That is
intentional: the canonical Explorer role is more specific than the built-in, and it is scoped
to this repository.

## Known volatility

| Feature | Status |
|---|---|
| `AGENTS.md` | stable, multi-vendor, LF-stewarded |
| `.agents/skills` | stable, published specification, ~40 clients |
| `.codex/agents/*.toml` | generally available, but **OpenAI states the format may evolve** |
| `~/.codex/prompts/` | deprecated — not used here |

Only the third is volatile, and nothing canonical depends on it.
