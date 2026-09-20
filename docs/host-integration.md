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
| The same holds at **fresh startup**, with the file present from spawn on the default branch | **measured — CONTRADICTED** | The clean-startup run below. This was the one cell the mid-session experiments could not reach, and it agrees with them |
| Cloud pre-installs `gh` | **measured — CONTRADICTED** | `command -v gh` and `command -v hub` both return nothing and nothing gh-shaped is on `PATH`, although the official installed-tools list names it. `manifest/binaries.json` now records `cloudPreinstalled: false` |
| Cloud pre-installs git, jq, yq, ripgrep, tmux, node, python3, uv | **measured — holds** | All present; Node 22 on `PATH` |
| `.claude/skills/` entry symlinks are followed in cloud | **measured — holds** | 33 skills loaded in the smoke test, when this repository still carried 33. Re-confirmed independently on 2026-09-20 in two fresh sessions against the pack repositories, with this repository absent: 13 of 13 discovered in each |
| An attached repository's skills are **loaded by the harness**, not merely readable on disk | **measured — holds** | In those same two sessions `wrangler` and `minimalist-ui` were invoked through the Skill tool, and the harness injected each body with its own `.claude/skills/<name>` base directory |

### The fresh-startup cell, closed 2026-09-20

Every observation above is of a session where the settings file appeared mid-life or was absent
throughout, so none of them excluded a spawn-time reconcile behaving differently. That was the
one open cell, and it has now been run.

A spawn always clones the default branch, so the test needed a repository whose *default branch*
carries the file: `vcTaz/agent-toolkit-cloud-validation`, default branch `main` at exactly
`132fb2774cfc0c755a96a660723ec9339910937a`, `.claude/settings.json` present from spawn, clean
working tree, and no mid-session checkout, fetch, install or repair.

| Observed | Value |
|---|---|
| `settings_load_completed` | `source_count: 4`, `error_count: 0` |
| `headless_marketplace_reconcile_completed` | `installed_count: 1`, `failed_count: 0`, `skipped_count: 0` |
| `ecc` marketplace | not registered |
| `ui-ux-pro-max-skill` marketplace | not registered |
| `ecc@ecc` | not installed |
| `ui-ux-pro-max@ui-ux-pro-max-skill` | not installed |
| `superpowers@claude-plugins-official` | **not installed**, although the official marketplace was present and contained it |
| `ListPlugins` | empty |
| `permissions.deny`, same file | loaded and enforced correctly |

The reconcile's own `installed_count: 1` is reported verbatim rather than interpreted. Whatever
it counts, no plugin became available: `ListPlugins` was empty. Do not cite it as evidence that
something installed.

### What that settles, and what it does not

Three claims of different strength come out of this, and collapsing them is the error this
section exists to prevent.

| Claim | Status |
|---|---|
| For the tested Anthropic-hosted cloud environment on 2026-09-20, project-scoped `enabledPlugins` and `extraKnownMarketplaces` **did not deliver the declared plugins at fresh startup** | **VERIFIED.** The mechanism runs — settings load without error, the reconcile completes — and delivers nothing |
| The cause is that the reconcile **ignores project-scoped plugin declarations** | **Best-supported explanation, NOT fully proven.** Only the reconcile's inputs, counters and outputs were read; nothing inside it was instrumented |
| Plugins do not work in cloud, generally | **NOT ESTABLISHED.** One environment, one date, one project shape. Do not generalise it |

The earlier hedge — that this was untested and the result should not be read as a settled
negative — is **withdrawn for the fresh-startup case**. It was correct when written and the test
has since been run. What remains open is the *cause*, not the *observation*.

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
| **Why** the reconcile delivers nothing — whether it ignores project-scoped plugin declarations | best-supported explanation, not proven | The observation is verified and does not depend on the cause being right. Do not state the mechanism as fact |
| Whether this holds across other Claude Code versions, cloud configurations or project shapes | not established | One environment on one date was tested. The `cloud` values in `profile/plugins.json` are scoped to it |

## Third-party skills, and why they are no longer here

Until 2026-09-20 this repository committed 27 third-party skills under a `vendor/` directory.
It did so because the alternatives genuinely do not work: a cloud session is not documented to
read `~/.claude/skills/`, a manifest entry is documentation rather than delivery, and the
repo-declared plugin route was measured that same day to deliver nothing. Committing the
content was the only route anyone had demonstrated.

What changed is that a *second* route was demonstrated. The content now lives in optional pack
repositories, built by `tools/vendor-sync.py --pack` from the specifications in `packs/`, and
each is attached only to the Projects that want it. Both were tested in fresh cloud sessions
with this repository absent, and both delivered — including a skill invoked through the Skill
tool with its body injected from the pack's own `.claude/skills` base directory. That is what
licensed the removal; without it, the committed copies would still be the only thing known to
work.

The bound is unchanged and now applies to the pack repositories: the builder is the only way
content gets into one. What it produces is reproducible from a named upstream commit,
verifiable offline against per-file hashes, and never hand-edited. Each pack carries its own
`LICENSE`, fetched from upstream rather than trusted from a metadata field, because GitHub's
own detection reports none for either source.

The gain is that this repository is now what it claims to be. It was 500 tracked files, of
which 398 were content nobody here wrote; it is now 78, and every skill in `.claude/skills/`
resolves into the canonical `skills/`.

## The sandbox boundary

The local machine may run Claude Code inside an OS-enforced sandbox built on Linux user
namespaces. Cloud sessions use per-session VM isolation. **These are separate and
non-equivalent boundaries.** Neither substitutes for the other, and nothing in the host
layer configures, references or weakens either. `.claude/settings.json` carries deny rules
only; it grants no allowlist and sets no default permission mode.
