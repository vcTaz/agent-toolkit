# Local installation

```bash
git clone <this repo> ~/agents && cd ~/agents
./local/bootstrap.sh            # link agents + skills into ~/.claude
./local/doctor.sh               # verify
```

On a fresh machine, do all of it at once:

```bash
./local/bootstrap.sh --with-vendored --with-plugins
```

| Flag | Adds |
|---|---|
| *(none)* | 7 agents + 6 toolkit skills |
| `--with-vendored` | the 27 third-party skills committed under `vendor/` |
| `--with-plugins` | marketplaces and plugins from `manifest/plugins.json` |

**`--with-vendored` is opt-in on purpose.** On a machine where those skills were installed
by their own CLI, they already exist, and linking would replace working installs — backed
up first, but replaced. A dry run on such a machine reports exactly that: 13 directories it
would back up and 14 symlinks pointing outside the toolkit that it refuses to touch. On a
fresh machine it is simply what you want.

## Guarantees

- **Idempotent.** A second run reports `already correct` and changes nothing.
- **Additive.** It never deletes. A real file where a link should go is moved to
  `~/.claude/backups/toolkit-bootstrap-<timestamp>/` first, and the path is printed.
- **Reversible.** `--uninstall` removes only links that resolve inside this toolkit.
  A symlink pointing anywhere else is reported and left alone.
- **No hard-coded paths.** The toolkit root comes from the script's own location; the
  config directory from `CLAUDE_CONFIG_DIR`, falling back to `~/.claude` — the same
  variable Claude Code honours. Nothing assumes a username or a home directory.
- **Dry-runnable.** `--dry-run` prints every action and performs none.

## `settings.fragment.json`

A portable template of this machine's Claude Code settings: preferences, the 17
`permissions.deny` rules, and 33 hook entries with every absolute `/home/<user>` path
rewritten to `$HOME`, which the shell expands when a hook runs.

**`bootstrap.sh` does not apply it.** Merging into a live `settings.json` is the one
operation here that could break a working setup, so it stays a deliberate manual act:

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak-$(date +%F)
# then merge the keys you want; review each hook before adopting it
```

Two things are deliberately absent from the fragment:

- **GitKraken hooks and `statusLine`** (12 entries) — re-added by the GitKraken desktop app
  itself. Copying them to a machine without that app produces hooks that cannot run.
- **Anything secret.** No tokens, credentials, account identifiers or machine IDs.

## What this does not manage

`~/.claude/scripts/` and `~/.claude/hooks/` are installed by the ECC plugin's own installer
and are **required by the hooks above** — the ECC plugin itself declares no hooks, so those
directories are the only thing making them run. This toolkit does not own, copy or remove
them.
