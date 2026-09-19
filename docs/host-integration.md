# The host layer

`AGENTS.md` forbids adding a runtime, a plugin framework or an installer "without a concrete
need". This document records the need, the bounds, and the evidence the design rests on.

## The need

The canonical layer is discovered natively when a harness opens this repository. That covers
one case well and two badly:

1. **This repository is the working directory.** Native discovery. Nothing else required.
2. **A different repository is the working directory, locally.** The canonical layer is not
   discovered. Without something, every project would need its own copy — which is the
   duplication this repository exists to avoid.
3. **A cloud Claude Code session.** Verified 2026-09-19 against Claude Code 2.1.278:
   **no part of `~/.claude/` reaches a cloud session.** Not settings, agents, skills or
   hooks. A machine-side convention therefore cannot reach cloud by any route.

Case 2 is solved by `local/` — symlinks from a single checkout into the user-level config,
so there is exactly one copy of every definition on the machine. Case 3 is solved by
`cloud/`, because the only channel that reaches a cloud session is a git checkout.

## The bounds

The host layer is deliberately the least powerful thing that solves those cases.

- **Shell and JSON only.** No new language dependency. `tools/check.py` remains the one
  Python file, stdlib-only.
- **No runtime the canonical layer can observe.** Nothing in `roles/`, `agents/`, `skills/`
  or `workflows/` may reference `local/`, `cloud/`, `manifest/` or `.claude/settings.json`.
  Remove the host layer and the canonical layer is unchanged and still correct.
- **Data, not content.** `manifest/` records *what is composed from elsewhere* — upstream
  repositories, versions, commit SHAs, checksums. It vendors nothing. Four separate
  upstreams are referenced this way rather than copied, because copying an actively
  maintained upstream guarantees drift.
- **Additive and reversible.** `local/bootstrap.sh` never deletes, backs up anything it
  would replace, and `--uninstall` removes only links resolving inside this repository.

## What was verified, and what was not

Established against Claude Code 2.1.278 on 2026-09-19:

| Claim | Status |
|---|---|
| Repo `.claude/agents/`, `.claude/skills/`, `CLAUDE.md`, `AGENTS.md` load in cloud | established |
| Repo `.claude/settings.json` is read in cloud, including plugins and marketplaces | established |
| `~/.claude/settings.json` does not reach cloud at all | established |
| Repo `.mcp.json` works in cloud for remote HTTP/SSE transports only | established |
| claude.ai Connectors are available inside cloud Code sessions | established |
| Git stores this repository's `.claude/skills` as a mode-`120000` symlink | established here, directly |

Explicitly **not** established, and therefore not depended on:

| Claim | Status | Consequence |
|---|---|---|
| Repo `.claude/commands/*.md` load in cloud | undocumented | Commands are provided but nothing requires them |
| Symlinks inside `.claude/` are followed by cloud sessions | undocumented | `cloud/setup.sh` installs **copies**, not links. Fallback if it ever fails: move `skills/` to `.claude/skills/` and re-point the Codex adapter |
| A private plugin marketplace authenticates in cloud | undocumented | The cloud path uses a plain git clone instead, never a marketplace |
| A user can publish their own skill or plugin into the account-synced channel | no documented route | Not used. `~/.claude/{plugins,skills}/synced/` is one-way, Anthropic-curated |

## The sandbox boundary

The local machine may run Claude Code inside an OS-enforced sandbox built on Linux user
namespaces. Cloud sessions use per-session VM isolation. **These are separate and
non-equivalent boundaries.** Neither substitutes for the other, and nothing in the host
layer configures, references or weakens either. `.claude/settings.json` carries deny rules
only; it grants no allowlist and sets no default permission mode.
