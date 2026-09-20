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
- **Additive on install.** Installing never deletes. A real file where a link should go is moved to
  `~/.claude/backups/toolkit-bootstrap-<timestamp>/` first, and the path is printed.
- **Reversible, and it reports when it was not.** `--uninstall` works from the install
  record `~/.claude/.toolkit-install-state.tsv`, which `bootstrap.sh` writes with the exact
  destination and target of every link it created. A recorded path is removed only while it
  is still a symlink pointing at the recorded target; one you have replaced with a file, or
  repointed, is left alone. Where there is no usable record — an install made by an older
  copy of this script — a link is recognised instead by what sits at the *far end* of it:
  a toolkit checkout (`AGENTS.md` and `tools/check.py`) or a skill pack (`PACK.json` and
  `PROVENANCE.json`), at a name this toolkit installs, linked as `NAME -> .../NAME`.
  Anything else is left alone.

  This bullet said until 2026-09-20 that only links resolving *inside* this toolkit are
  removed and that everything else is left alone. Both halves were wrong: a pack link
  points outside the toolkit by definition, and an upgrade-path uninstall measured that day
  left **26 of 26 pack links** in place while reporting that nothing else was touched.
- **The undo is computed, not asserted, and the check is wider than the removal.** After
  removing, the script re-reads the config directory for links it can still attribute to
  itself and for broken links it cannot judge
  — the target is gone, so there is nothing to read. It names them, withholds
  `Nothing else was touched`, and exits non-zero. `--dry-run` previews the broken-link
  half of that scan, so it cannot promise a clean undo the real run will not deliver;
  the attributable-leftover half needs the removals to have happened and is a backstop
  for the real run only.

  The closing check deliberately looks at **more** than the remover acts on: it does not
  apply the name gate. Applying the same gate to both made every gate failure silent —
  a pack specification reformatted by a JSON writer, still valid and still accepted by
  `tools/check.py`, once made the name list come back empty, so the remover skipped all
  thirteen pack links and the check skipped them too. The cost is that a link of your own
  at one of these names, inside a pack checkout, is named in the summary as something to
  look at. That is the trade: a link to check beats a false clean undo.
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
