# Why `.claude/settings.json` contains what it contains

This file is **repository-scoped settings**. It is the *only* configuration channel that
reaches a cloud Claude Code session: verified 2026-09-19 against Claude Code 2.1.278,
nothing from `~/.claude/settings.json` is synced to cloud.

## What is here, and why

| Key | Reason |
|---|---|
| `permissions.deny` | Mirrors the 17 machine-local deny rules. Deny rules are additive, so this can only ever *tighten* a session. Today a cloud session has none of these; adding them is a net security gain. |
| `enabledPlugins` | Only the three **portable** plugins. |
| `extraKnownMarketplaces` | Only the two public marketplaces the portable plugins need. `claude-plugins-official` is built in and needs no entry. |

## What is deliberately NOT here

| Omitted | Reason |
|---|---|
| `hooks` | Every hook on this machine invokes an absolute `$HOME/.claude/scripts/...` path that does not exist in a cloud session. Machine hooks live in `local/settings.fragment.json`. |
| `statusLine` | Requires the GitKraken/orca desktop install. |
| `gitkraken`, `clangd-lsp`, `claude-mem` plugins | Machine-local: they need `~/.orca/`, a local language server, and a local SQLite store respectively. See `manifest/plugins.json`. |
| stdio MCP servers | Cloud supports remote HTTP/SSE MCP only. See `.mcp.json`. |
| Any `permissions.allow` or `defaultMode` | This setup intentionally runs default-ask. Nothing here weakens that. |

## Sandbox boundary

This file does **not** configure, reference, or weaken the local `claude-safe` / `srt` /
`bwrap` sandbox. That boundary is machine-local by construction. Cloud sessions use
Anthropic's per-session VM isolation, which is a **separate and non-equivalent** boundary —
do not reason about one as though it were the other.
