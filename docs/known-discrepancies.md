# Known discrepancies

Things that are not what they appear to be. Recorded rather than silently corrected,
because each one is in a file this toolkit does not own.

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

## 2. Cloud behaviour is now part measured, part still only documented

**Superseded 2026-09-20.** This section previously said no cloud session had executed any of
this toolkit. That is no longer true: `cloud/SMOKE-TEST.md` was run, and a controlled pair of
sessions measured the settings and plugin behaviour directly.

What changed, and why it is recorded here rather than quietly edited into the claims:

- The caution was **right**. The first measurement contradicted two claims this repository
  called established — repo-declared plugins installing at session start, and `gh` being
  pre-installed in cloud. Both had been asserted confidently from documentation.
- One of the contradicted claims was itself a *correction* of an earlier caution. "Plugin
  auto-install in cloud is unverified" was replaced by "repo-declared plugins install at
  session start" on the strength of the documentation, and the replacement was wrong. A
  correction is not evidence either.
- The caution was also **incomplete in the other direction**. The measurement established
  that a repository's `.claude/settings.json` *is* read in cloud and its `permissions.deny`
  rules *are* enforced. Reading the missing plugins as "repo settings do not reach cloud" is
  the opposite error and was made once already.

`docs/host-integration.md` now separates *measured* from *documented*, and names the one cell
of the plugin question that remains untested — whether a session that **spawns** with the
settings file already on the default branch behaves differently from one where the file
appeared mid-life. Until that reports, nothing in this repository should state the plugin
result as a settled negative.

## 3. `rtk`'s own upgrade advice would break it

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
