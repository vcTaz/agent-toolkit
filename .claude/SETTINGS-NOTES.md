# Why `.claude/settings.json` contains what it contains

This file is **repository-scoped settings**. Nothing from `~/.claude/settings.json` reaches
a cloud session — verified 2026-09-19 against Claude Code 2.1.278 — so this file is the only
settings channel a repository has. How much of it is honoured depends on the project shape:
all of it in a single-repository session, and only `enabledPlugins` and
`extraKnownMarketplaces` in a multi-repository project thread.

Measured 2026-09-20, because the two halves of this file fared very differently in cloud: the
`permissions.deny` half **is read and enforced** in a single-repo session, and the plugin half
**delivered nothing** and reported no failure. The file reaching the session and the file
having its stated effect are two claims, and only the first is established for both halves.

Both halves were re-checked in the same clean fresh-startup run, with the file present from
spawn and nothing changed mid-session: the deny rules enforced, the plugins did not arrive. So
the split is not an artefact of when the file appeared.

## What is here, and why

| Key | Reason |
|---|---|
| `permissions.deny` | Mirrors the 17 machine-local deny rules. Deny rules are additive, so this can only ever *tighten* a session. **Important:** a cloud session reads these only when the project has **one** repository. In a multi-repository project the thread starts above the clones and reads no repository's `permissions`, `hooks` or `env` — so these rules do **not** apply there and must be set in **Project settings** instead. See `cloud/README.md`. |
| `enabledPlugins` | Only the three **portable** plugins. **Verified 2026-09-20: in a cloud session these install nothing — at fresh startup as well as mid-session.** The reconcile runs and reports no failure. Kept because they are correct locally; do not plan a cloud session around them. See `manifest/plugins.json`. |
| `extraKnownMarketplaces` | Only the two public marketplaces the portable plugins need. `claude-plugins-official` is built in and needs no entry. **Measured 2026-09-20: neither was registered in a cloud session**, silently. |

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
