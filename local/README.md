# Local installation

```bash
git clone <this repo> ~/agents && cd ~/agents
./local/bootstrap.sh            # link agents + skills into ~/.claude
./local/doctor.sh               # verify
```

On a fresh machine, do all of it at once:

```bash
PACK_CLOUDFLARE_DIR=~/src/claude-skills-cloudflare \
  ./local/bootstrap.sh --with-packs --with-plugins
```

| Flag | Adds |
|---|---|
| *(none)* | 8 agents + 6 toolkit skills |
| `--with-packs` | skills from any checked-out pack named by `PACK_<NAME>_DIR` |
| `--with-plugins` | marketplaces and plugins from `profile/plugins.json` |

**`--with-packs` is opt-in, and so is every individual pack.** A pack lives in its own
repository — see `packs/README.md` — so this script links one only when you point
`PACK_<NAME>_DIR` at a checkout of it, upper-cased with dashes as underscores. A pack with no
directory set is reported and skipped rather than failed on, because not having one checked
out is the normal case. That is the point of the tier: nothing third-party arrives unless you
ask for it by name.

On a machine where those skills were installed by their own CLI they already exist, and
linking would replace working installs — backed up first, but replaced. A dry run says so
before anything moves.

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

## `profile/settings.fragment.json`

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
