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

Two sources of different strength, kept apart on purpose.

- **Documented** (2026-09-19, Claude Code 2.1.278) means read in Anthropic's official
  documentation. It is not evidence about this repository; it is evidence about what the
  product is said to do.
- **Measured** (2026-09-20) means a cloud session ran and the result was read off the
  filesystem or the diagnostics log. Where the two disagree, the measurement wins, and the
  documented claim is recorded as contradicted rather than quietly deleted.

Cloud sessions have now executed parts of this toolkit. That was not true of any revision of
this file before 2026-09-20, and the first measurement contradicted two claims this file
called established.

### Measured in a cloud session

Method: a controlled pair of sessions, same Claude Code build and hour, differing only in
whether this repository's `.claude/settings.json` was in the working tree — so a rollout
landing between observations is ruled out.

| Claim | Status | Evidence |
|---|---|---|
| A repo `.claude/settings.json` **is read** in a cloud session, and its `permissions.deny` rules are enforced | **measured — holds** | The absent path `/root/.sqlsecrets/probe`, denied only by this file's bespoke rule, returns "File is in a directory that is denied by your permission settings" where the file is present, and byte-identical "File does not exist." where it is not. The deny check fires before the existence check |
| Project settings are **hot-reloaded** mid-session, not read only at startup | **measured — holds** | A synthetic rule written during a turn took effect within seconds and stopped on deletion |
| Plugins declared in a repo `.claude/settings.json` are installed at session start | **measured — CONTRADICTED** | The reconcile ran, registered only `anthropics/claude-plugins-official` (which Claude Code already knows), registered neither marketplace from `extraKnownMarketplaces`, and installed **zero** plugins, reporting `failed_count: 0, skipped_count: 0`. `superpowers` was in a registered marketplace's manifest and still did not install |
| Cloud pre-installs `gh` | **measured — CONTRADICTED** | `command -v gh` and `command -v hub` both return nothing and nothing gh-shaped is on `PATH`, although the official installed-tools list names it. `manifest/binaries.json` now records `cloudPreinstalled: false` |
| Cloud pre-installs git, jq, yq, ripgrep, tmux, node, python3, uv | **measured — holds** | All present; Node 22 on `PATH` |
| `.claude/skills/` entry symlinks are followed in cloud | **measured — holds** | 33 skills loaded in the smoke test |

One cell of the plugin question is **still untested**: every observation above is of a session
where the settings file appeared mid-life or was absent throughout. Whether a session that
**spawns** with the file already on the repository's default branch installs what a mid-session
reconcile did not has not been run. A spawn always clones the default branch, so testing it
needs a repository whose default branch carries the file. Until that test reports, read the
contradiction above as *what happened in the cases measured*, not as a settled negative.

Two readings of the measurement are wrong and should not be repeated:

- **"Repo settings do not reach cloud."** They do. The file is read and the security half of
  it is actively protecting the session. Only the plugin declarations came to nothing.
- **"The plugins were absent, therefore the declarations were ignored."** Absence of plugins
  is not evidence about the declarations. The discriminating artefacts are
  `~/.claude/plugins/known_marketplaces.json`, `installed_plugins.json` and the
  `headless_marketplace_reconcile` lines in `$CLAUDE_CODE_DIAGNOSTICS_FILE`.

### Documented, not yet measured

Read in the official documentation on 2026-09-19, against Claude Code 2.1.278. No cloud
session has exercised these, so they carry the weaker claim.

| Claim | Status |
|---|---|
| A project thread clones **every** project repository and loads `CLAUDE.md`, skills and plugins from all of them | documented |
| Repo `.claude/skills/`, `.claude/agents/`, `.claude/commands/` load in cloud | documented |
| A `<skill-name>` **entry** in a project skills directory may be a symlink; Claude Code reads `SKILL.md` from the target | documented, and measured to hold — see above |
| Repo `permissions`, `hooks` and `env` apply **only** in a single-repository session; a multi-repo project thread starts above the clones and reads none of them | documented |
| Repo `.mcp.json` loads only in a single-repository session | documented |
| `~/.claude/` — settings, skills, agents, commands — does not reach cloud at all | documented |
| Setup scripts run as root on Ubuntu 24.04 before Claude Code launches, must exit zero, ~5 min budget | documented |
| `github.com` is on the default Trusted network allowlist | documented |
| Threads get MCP exclusively from claude.ai account connectors (plus repo `.mcp.json` when single-repo) | documented |

### Conclusions this repository got wrong

Kept because the pattern matters more than any one entry: every one of these was asserted
confidently, and three of the five were corrected only because something outside the
reasoning was checked.

| Was claimed | Correction | Settled by |
|---|---|---|
| Repo `.claude/commands/` support is undocumented | It is documented and supported | documentation, 2026-09-19 |
| ripgrep and uv are absent from cloud environments | Both are pre-installed; `cloud/setup.sh` no longer installs them | documentation, 2026-09-19 |
| Plugin auto-install in cloud is unverified → *corrected to* repo-declared plugins install at session start | The **correction was itself wrong**. A live reconcile installed nothing and reported no failure | measurement, 2026-09-20 |
| `gh` is pre-installed in cloud sessions | It is not present at all | measurement, 2026-09-20 |
| `.claude/skills` is a symlink to `skills/` | It is a real directory of per-skill symlinks; only `.agents/skills` is a container symlink | inspection, 2026-09-20 |

Still **not** established, and therefore not depended on:

| Claim | Status | Consequence |
|---|---|---|
| A skills **container** directory may itself be a symlink | undocumented — only entries are | `.claude/skills/` is a real directory of per-skill symlinks. This is the documented form |
| A private marketplace authenticates in a cloud session | undocumented | Not used. Plugins come from public marketplaces; the toolkit arrives as a project repository |
| A user can publish their own plugin into the account-synced channel | no documented route | Not used. Enabling an existing plugin for the account is a different, supported thing |
| Whether a plain clone of a private repo succeeds through the GitHub proxy without a PAT | untested | `cloud/setup.sh` tries it first and degrades to a PAT, and never fails the session either way |
| Whether a session that **spawns** with `.claude/settings.json` present installs the declared plugins | untested — rig exists, run not reported | The `cloud` values in `manifest/plugins.json` are written as observations, not as a settled negative |

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
