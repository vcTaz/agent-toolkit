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

- **Shell and JSON only.** No new language dependency: `tools/` stays stdlib-only Python and
  is added to only when a maintenance task genuinely needs it.
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

Established from the official documentation on 2026-09-19, against Claude Code 2.1.278.
**All of it is static validation: no cloud session has executed any part of this toolkit.**

| Claim | Status |
|---|---|
| A project thread clones **every** project repository and loads `CLAUDE.md`, skills and plugins from all of them | established |
| Repo `.claude/skills/`, `.claude/agents/`, `.claude/commands/` load in cloud | established |
| Plugins declared in a repo `.claude/settings.json` are **installed at session start** from the declared marketplace | established |
| A `<skill-name>` **entry** in a project skills directory may be a symlink; Claude Code reads `SKILL.md` from the target | established |
| Repo `permissions`, `hooks` and `env` apply **only** in a single-repository session; a multi-repo project thread starts above the clones and reads none of them | established |
| Repo `.mcp.json` loads only in a single-repository session | established |
| `~/.claude/` — settings, skills, agents, commands — does not reach cloud at all | established |
| Cloud pre-installs git, gh, jq, yq, ripgrep, tmux, node, python3, uv | established |
| Setup scripts run as root on Ubuntu 24.04 before Claude Code launches, must exit zero, ~5 min budget | established |
| `github.com` is on the default Trusted network allowlist | established |
| Threads get MCP exclusively from claude.ai account connectors (plus repo `.mcp.json` when single-repo) | established |

Three earlier conclusions in this repository were **wrong** and have been corrected:

| Was claimed | Correction |
|---|---|
| Repo `.claude/commands/` support is undocumented | It is documented and supported |
| Plugin auto-install in cloud is unverified | Repo-declared plugins install at session start |
| ripgrep and uv are absent from cloud environments | Both are pre-installed; `cloud/setup.sh` no longer installs them |

Still **not** established, and therefore not depended on:

| Claim | Status | Consequence |
|---|---|---|
| A skills **container** directory may itself be a symlink | undocumented — only entries are | `.claude/skills/` is a real directory of per-skill symlinks. This is the documented form |
| A private marketplace authenticates in a cloud session | undocumented | Not used. Plugins come from public marketplaces; the toolkit arrives as a project repository |
| A user can publish their own plugin into the account-synced channel | no documented route | Not used. Enabling an existing plugin for the account is a different, supported thing |
| Whether a plain clone of a private repo succeeds through the GitHub proxy without a PAT | untested | `cloud/setup.sh` tries it first and degrades to a PAT, and never fails the session either way |

## Vendoring, and why it is not a contradiction

`AGENTS.md` says the canonical layer is ours and portable. `vendor/` is neither, and that is
why it is a separate top level with its own README, licences and provenance rather than
something mixed into `skills/`.

It exists because the alternatives do not work. A cloud session does not read
`~/.claude/skills/`; a manifest entry is documentation, not delivery; and the account-skill
upload route has no documented bulk mechanism. Committing the content is the only supported
path, and all three upstreams permit redistribution — verified by fetching each `LICENSE`,
since GitHub's own detection reports none for all three.

The bound is that `tools/vendor-sync.py` is the only way content gets there. What is
committed is always reproducible from a named upstream commit, verifiable offline against
per-file hashes, and never hand-edited. `tools/check.py` excludes `vendor/` from the link
checker for the same reason: three links are broken upstream in `cloudflare/skills` at the
current pin, and this repository has no authority to fix them.

## The sandbox boundary

The local machine may run Claude Code inside an OS-enforced sandbox built on Linux user
namespaces. Cloud sessions use per-session VM isolation. **These are separate and
non-equivalent boundaries.** Neither substitutes for the other, and nothing in the host
layer configures, references or weakens either. `.claude/settings.json` carries deny rules
only; it grants no allowlist and sets no default permission mode.
