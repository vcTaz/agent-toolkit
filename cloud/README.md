# Using this toolkit with Claude Projects and cloud Claude Code

Verified against Claude Code 2.1.278 and the official documentation on **2026-09-19**.
Where this file disagrees with the documentation, the documentation is right and this is
stale.

**Some of this has been measured in a cloud session and some has not, and the two are
marked apart throughout.** Until 2026-09-20 this line said no cloud session had executed
any of it, which stopped being true that day: `cloud/SMOKE-TEST.md` was run, the plugin
result below was measured, and both skill packs were tested in fresh sessions. Every
statement here that rests on a measurement says when it was taken; anything that does not
say so is still derived from the documentation and from local inspection, and is the part
[cloud/SMOKE-TEST.md](SMOKE-TEST.md) exists to close. What was measured was measured in
Anthropic's hosted cloud environment on those dates, which is not a claim about any other
environment or any later version. [docs/known-discrepancies.md](../docs/known-discrepancies.md)
records what has already been found wrong.

## The mechanism

A Claude **Project** is one conversation in which Claude coordinates **threads**, and each
thread is a cloud session. Per the documentation:

> Each thread clones every repository in the project and loads `CLAUDE.md`, skills, and
> plugins from all of them.

So the supported way to get this toolkit into cloud work is simply **add this repository to
the project**, alongside your application repository. No token, no clone script, no sync.

## What a thread actually gets, by project shape

| In each repository | Project with **one** repo | Project with **several** repos |
|---|---|---|
| `CLAUDE.md` | loaded | loaded from **every** repo |
| `.claude/skills/`, `.claude/agents/`, `.claude/commands/` | loaded | loaded from **every** repo |
| Plugins in `.claude/settings.json` | loaded | loaded from **every** repo |
| **Permission rules, hooks, `env`** in `.claude/settings.json` | apply | **do NOT apply** |
| `.mcp.json` | loaded | **not loaded** |

That fourth row matters and is easy to miss. In a multi-repo project the thread starts
*above* the clones, so no repository's `permissions`, `hooks` or `env` are read.

### Consequence for security

This repository's `.claude/settings.json` carries 17 `permissions.deny` rules protecting
`~/.ssh`, cloud credentials, keyrings and similar. **In a multi-repo project those rules do
not apply.** They are not silently lost — they were never read. If you want them in a
multi-repo project, set them in **Project settings**, which is the only scope that reaches
the thread. A single-repo project does apply them — **measured 2026-09-20**, not inferred: a
deny rule unique to this file was enforced in a live single-repo cloud session, and the same
probe in a session without the file returned the ordinary not-found answer.

Plugin-provided hooks were expected to run in both shapes, on the reasoning that plugins load
from every repository. **That reasoning is not established, and its premise failed when
measured.** In the same session the plugin reconcile ran and installed nothing, so there were
no plugin hooks to run either way. See "Plugins declared here did not arrive" below.

## What this repository actually carries

| Under `.claude/` | Count | Form | Reaches cloud |
|---|---|---|---|
| `agents/` | 8 | real files | yes |
| `skills/` → `skills/` | **6** | entry symlinks | yes |
| `commands/` | 0 | — | n/a |
| `settings.json` | 1 | real file | yes — but see the two rows below for what it then does |
| ├ `permissions.deny` | 17 rules | — | **measured:** enforced in a single-repo session; not read at all in a multi-repo project |
| `enabledPlugins` / `extraKnownMarketplaces` | **0** | — | removed 2026-09-20; they were read and delivered nothing. See below |

Six skills, and no third-party content. Until 2026-09-20 this repository also carried 27
third-party skills committed under a `vendor/` directory. They now live in **optional pack
repositories** — `vcTaz/claude-skills-cloudflare` (13, Apache-2.0) and
`vcTaz/claude-skills-frontend` (13, MIT) — attached to the Projects that want them and to no
others. `orca-cli` was dropped; see `manifest/external-skills.json`. The specifications are
in `packs/`, and `packs/README.md` explains the shape a pack must have to deliver anything.

Pack delivery is **verified**, not assumed: on 2026-09-20 both packs were tested in separate
fresh cloud sessions with this repository absent, each discovering 13 of 13 skills, and a
representative skill invoked through the Skill tool with its body injected from the pack's own
`.claude/skills` base directory.

### Plugins declared here did not arrive

Measured 2026-09-20, against this repository's own `.claude/settings.json`. The file **was**
read — the plugin reconcile fires only when it is present, and the deny rules in the same file
were enforced. What the reconcile then did:

- registered exactly one marketplace, `anthropics/claude-plugins-official`, which Claude Code
  already knows;
- registered **neither** marketplace declared in `extraKnownMarketplaces`;
- installed **zero** plugins — `installed_plugins.json` stayed `{"version":2,"plugins":{}}`;
- reported `failed_count: 0, skipped_count: 0`. No error, no warning, no skip, no log line.

`superpowers` is the sharpest case: its marketplace *was* registered and it is in that
marketplace's manifest, and it still did not install. So marketplace reachability does not
entail plugin delivery.

**Confirmed at fresh startup, 2026-09-20.** The result above was first seen in sessions where
the settings file appeared mid-life, which left one objection open: perhaps a spawn-time
reconcile behaves differently. It does not. A clean run against a repository whose *default
branch* carried the file — present from spawn, clean working tree, no mid-session checkout,
fetch, install or repair — reported `settings_load_completed` with `source_count: 4` and
`error_count: 0`, a completed reconcile with `failed_count: 0` and `skipped_count: 0`, neither
declared marketplace registered, none of the three plugins installed, and an empty
`ListPlugins`. The same file's `permissions.deny` rules loaded and enforced correctly in that
very session.

So: **verified** that project-scoped `enabledPlugins` and `extraKnownMarketplaces` did not
deliver the declared plugins in the tested environment on that date. That the reconcile
*ignores* project-scoped declarations is the best-supported explanation and is **not proven** —
only its inputs, counters and outputs were read. And it is **not established** that this holds
for every Claude Code version or cloud configuration; one environment on one date was tested.

Do not read any of it as "repository settings are ignored in cloud" — that reading is wrong and
was made once already, and the deny rules in the same file demonstrably work. Plan on the skills
and agents in this repository, which are measured to arrive, rather than on the plugins.

## What is already true without any setup

Cloud sessions pre-install: `git`, `jq`, `yq`, `ripgrep`, `tmux`, `vim`, Python
(with `pip`, `uv`, `ruff`, `pytest`), Node 20/21/22, Ruby, PHP, Java, Go, Rust, C/C++,
Docker, PostgreSQL 16, Redis 7. **Nothing this toolkit needs has to be installed.**

> **`gh` is not there**, despite appearing on the official installed-tools list. Measured
> 2026-09-20: `command -v gh` and `command -v hub` both return nothing and nothing gh-shaped
> is on `PATH`. Use the GitHub MCP tools or plain `git` — a plan written around `gh` fails at
> the first command. See `manifest/binaries.json`.

`github.com` is on the default **Trusted** network allowlist. Plain HTTPS to github.com may
still be denied by the agent proxy while `git` succeeds, because git authenticates through
credential injection; that is not a network fault.

## `cloud/setup.sh` — usually unnecessary

Only for a single-repository cloud session started on some *other* repository, where you
still want the toolkit. It is best-effort and always exits zero, because a non-zero exit
from a setup script makes the session fail to start.

Prefer leaving `TOOLKIT_TOKEN` unset: cloud sessions authenticate GitHub through a proxy, so
a plain clone often succeeds for a repository the Claude GitHub App is installed on, with no
credential in the environment. If you must set a token, use a **fine-grained, read-only
`Contents` PAT scoped to this one repository** — the documentation warns that anyone who can
use the environment can read its variables.

---

# HOW TO ENABLE THIS TOOLKIT IN A NEW CLAUDE PROJECT

Every step is manual and account-side unless marked otherwise. Start: **New Claude Project**.

### Prerequisites

1. **Check plan and rollout.** Projects are public beta on **Pro and Max**, not yet on Team
   or Enterprise. If **Projects** is absent from the sidebar at claude.ai/code, the rollout
   has not reached you; use a single-repo cloud session instead (`claude --cloud`).
2. **Install the Claude GitHub App on BOTH repositories** — your application repo *and*
   `agent-toolkit-private`. A project thread clones each repo and requires the App on each,
   plus push access from your GitHub account. `/web-setup` alone is **not** sufficient for
   project threads.

### Create and populate the project

3. **Create the project** at claude.ai/code → **Projects** → **New project**.
4. **Add your application repository.**
5. **Add `agent-toolkit-private`** in the same dialog, or later in
   **Project settings → Environment**. This is the step that delivers the toolkit.
   - Note: once a project has repositories, Claude can only add repos from a GitHub owner
     the project already uses. Add a different owner's repo yourself here.

### Configure what repos cannot carry

6. **Plugins** — **this repository declares none, and a repository cannot deliver them.**
   It used to declare `ecc`, `superpowers` and `ui-ux-pro-max` with their marketplaces in
   `.claude/settings.json`; measured on 2026-09-20 in a fresh session, the file was read
   and its deny rules enforced while **zero** of those plugins installed. The two keys
   were removed on 2026-09-20 and now live in `profile/plugins.json`, which
   `local/bootstrap.sh --with-plugins` applies on a machine, where they do work. See
   *Plugins declared here did not arrive* above for the measurement.
   **Project settings → Plugins** is the only route that reaches a cloud session, so add
   anything you want there.
7. **Permissions** — if this is a **multi-repo** project, re-declare the deny rules in
   **Project settings**, because repository `permissions` are not read. Copy them from
   `.claude/settings.json` in this repo.
8. **Connectors (this is how MCP works in threads)** — threads get MCP tools from the
   connectors on your claude.ai account, at
   [claude.ai/customize/connectors](https://claude.ai/customize/connectors) or via
   **Manage connectors** in **Project settings → Environment**. Connect what you need
   (Notion, Google Drive, Google Calendar, Claude Docs, …). The project conversation itself
   has no connectors — send connector work as a *task for a thread*.
9. **Environment** — **Project settings → Environment**. Set network access (default
   **Trusted** is enough). Add `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` here if you want
   Agent Teams. Add a setup script only if you need a tool outside the pre-installed set.
10. **Account-level skills (optional)** — skills you enable for your claude.ai account also
    load into every thread. Manage them in the skills settings on claude.ai or
    **Customize** in the Desktop app. Use this for skills you want everywhere without
    committing them to a repo.

### Verify

11. **Start a new thread** in the project.
12. **Run the smoke test** in `cloud/SMOKE-TEST.md`. Paste it as the thread's first message.

Done when the thread lists this toolkit's agents and skills and can invoke one of each.

---

## What can never transfer from local Claude Code

| Stays local | Why |
|---|---|
| `claude-safe`, `srt`, `bwrap` | An OS sandbox built on Linux user namespaces. Cloud uses per-session VM isolation — a **separate, non-equivalent** boundary. Neither substitutes for the other. |
| `--dangerously-skip-permissions` | Not applicable in cloud; use the session's permission-mode dropdown. |
| The 45 machine hooks | Every one invokes an absolute local path. In a multi-repo project, repository hooks are not read at all. |
| `rtk` | Wraps local commands for token reduction; no cloud equivalent. |
| `gitkraken-hooks`, `clangd-lsp`, `claude-mem` | Need a desktop app, a local language server, and a local database. |
| stdio MCP servers | Cloud supports remote transports; use Connectors instead. |
| `~/.claude/*` in general | Documented: cloud sessions do not read it. |
