# Using this toolkit with cloud Claude Code

Verified against **Claude Code 2.1.278, 2026-09-19**. Mechanisms change; where this file
disagrees with the official documentation, the documentation is right and this is stale.

## The one fact that determines everything

**Nothing in `~/.claude/` reaches a cloud session.** Not settings, not agents, not skills,
not hooks. Portability here means *committed to a git repository that Claude checks out* —
it does not mean *synced from your machine*.

| Surface | Local CLI | Cloud |
|---|---|---|
| repo `.claude/agents/*.md` | yes | **yes** |
| repo `.claude/skills/*/SKILL.md` | yes | **yes** |
| repo `CLAUDE.md` / `AGENTS.md` | yes | **yes** |
| repo `.claude/settings.json` | yes | **yes** — incl. `enabledPlugins`, `extraKnownMarketplaces`, `hooks` |
| repo `.mcp.json` | all servers | **remote HTTP/SSE only** |
| claude.ai Connectors | yes | **yes**, inside cloud Code sessions |
| `~/.claude/settings.json` | yes | **no — none of it** |
| `~/.claude/{agents,skills,commands}` | yes | **no** |
| stdio MCP (`npx`, `node`, `uvx`) | yes | **no** |
| repo `.claude/commands/*.md` | yes | **undocumented — do not depend on it** |

## Two ways in

### 1. The checked-out repo *is* this toolkit

Nothing to do. `.claude/agents/`, `.claude/skills` and `.claude/settings.json` load natively.

### 2. The checked-out repo is something else

Use `cloud/setup.sh` as the environment's setup script, with two environment variables set
in the cloud environment UI:

| Variable | Value |
|---|---|
| `TOOLKIT_REPO` | `<owner>/<repo>` of this private repository |
| `TOOLKIT_TOKEN` | a GitHub PAT — **fine-grained, read-only `Contents`, scoped to this one repository** |

The script never writes the token to disk, never puts it in a URL or an argument, and never
prints it; it reaches `git` only through `GIT_ASKPASS`. **Do not** use a classic PAT or a
broadly-scoped token: a cloud environment variable is readable by anything running in that
session.

If you would rather not place a token there at all, leave both unset. Route 1 still works,
and the script degrades to installing tools only.

## Manual, account-side steps

These cannot be automated from a repository and must be done by you:

1. **Create the environment** and paste `cloud/setup.sh` into its setup-script field.
2. **Set `TOOLKIT_REPO` / `TOOLKIT_TOKEN`** if you want route 2.
3. **Connectors** — Notion, Google Drive, Google Calendar, Claude Docs and similar are
   configured on your claude.ai account, not here. They *do* work inside cloud Code sessions
   and are the correct replacement for the local stdio MCP servers.
4. **Permission mode** — cloud sessions use the UI permission dropdown.
   `--dangerously-skip-permissions` does not apply there.

## What deliberately does not come to cloud

| Not ported | Why |
|---|---|
| `claude-safe`, `srt`, `bwrap` | An OS-level sandbox built on Linux user namespaces. Cloud uses per-session VM isolation — a **separate, non-equivalent** boundary. Neither substitutes for the other, and this toolkit does not pretend otherwise. |
| The 45 machine hooks | Every one invokes an absolute local path. See `local/settings.fragment.json`. |
| `rtk` | A local binary wrapping local commands for token reduction. |
| `gitkraken-hooks`, `clangd-lsp`, `claude-mem` | Need a desktop app, a local language server and a local database respectively. |
| stdio MCP servers | Cloud supports remote transports only. |

## Security note

`.claude/settings.json` carries the same 17 `permissions.deny` rules as the local machine.
Deny rules are additive and can only tighten a session, so this is a net gain: without it a
cloud session would have none of them. Nothing in this directory relaxes a permission,
grants an allowlist, or sets a default mode.
