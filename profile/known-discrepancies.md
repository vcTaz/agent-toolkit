# Known discrepancies — this machine

Things that are not what they appear to be **on one machine**, in files this toolkit does
not own. Nothing here is a property of the toolkit; a different machine has a different
list, or none. `local/doctor.sh --profile` re-checks them.

Moved out of `docs/known-discrepancies.md` on 2026-09-20, unchanged apart from the
numbering. What stayed there is the one discrepancy that is about the toolkit's own claims.

## 1. "Attribution disabled globally" is not true

`~/.claude/rules/common/git-workflow.md` states:

> Note: Attribution disabled globally via `~/.claude/settings.json`.

Two problems, both verified 2026-09-19:

1. **No such key is set.** `~/.claude/settings.json` contains no `includeCoAuthoredBy` and
   no `attribution`. The claim describes a configuration that does not exist, so commits
   get Claude Code's default attribution behaviour, not the documented one.
2. **The implied key is deprecated.** `includeCoAuthoredBy` is marked *"Deprecated; use
   `attribution` to hide or change commit and PR attribution"* in the settings reference.

The rule file is a byte-identical copy of one shipped by the `ecc` plugin, so editing it in
place creates drift from upstream and is overwritten by the next ECC install. It is left
alone deliberately.

**To make the statement true**, add this to `~/.claude/settings.json` yourself:

```json
{
  "attribution": { "commit": false, "pr": false }
}
```

**Or**, to make the documentation true instead, treat the line as describing an *optional
manual setting* rather than a configured fact. Either resolves it; doing neither leaves a
rule file asserting something false about the machine.

This toolkit follows the stated *intent* — no attribution trailer — regardless of which you
pick, because intent is what the rule expresses.

## 2. `rtk`'s own upgrade advice would break it

`~/.claude/hooks/rtk-rewrite.sh` prints, on the version-too-old path:

```
[rtk] WARNING: rtk <v> is too old (need >= 0.23.0). Upgrade: cargo install rtk
```

`cargo install rtk` installs a **different project** — the crates.io crate named `rtk` is
`reachingforthejack/rtk` ("Rust Type Kit"), not `rtk-ai/rtk`. Following that advice replaces
a working binary with one that has no `rewrite` subcommand, silently disabling the
PreToolUse hook on every Bash call.

Latent, not active: it only fires below 0.23.0, and the installed version is 0.42.1. It is a
fresh-machine hazard. The correct command is in `manifest/binaries.json`:

```bash
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
```

### Why this has not simply been fixed

It was attempted, and the attempt was reverted. **The hook is integrity-protected.** rtk
stores its sha256 in `~/.claude/hooks/.rtk-hook.sha256` and refuses to execute at all when
the file does not match:

```
rtk: hook integrity check FAILED
  The hook at ~/.claude/hooks/rtk-rewrite.sh has been modified.
  This may indicate tampering. RTK will not execute.
```

Because a PreToolUse hook wraps every Bash call, editing one line disables rtk entirely
until the baseline is updated. The original was restored from a timestamped backup and
`rtk verify` returns `PASS`, 145/145 tests.

Fixing it therefore means rewriting a tamper-detection baseline, which is a decision for
the machine's owner and not something to do on their behalf. Two supported routes:

1. **Accept the latent defect.** It never fires at 0.23.0 or above, and
   `local/doctor.sh` warns about it on every run so it cannot be forgotten.
2. **Fix and re-baseline, deliberately:**
   ```bash
   cp ~/.claude/hooks/rtk-rewrite.sh ~/.claude/hooks/rtk-rewrite.sh.bak-$(date +%F)
   # edit the `Upgrade:` line to the install.sh command above
   sha256sum ~/.claude/hooks/rtk-rewrite.sh | \
     sed 's| .*/| |' > ~/.claude/hooks/.rtk-hook.sha256
   rtk verify        # must print PASS before continuing
   ```
   Note that `rtk init -g --auto-patch` regenerates the hook from rtk's own template and
   would revert the fix. `local/doctor.sh` warns again if that happens.

The cleanest resolution is upstream: the advice is wrong in rtk's own repository.

The file belongs to the rtk install, not to this toolkit, so it is recorded here rather than
patched.
