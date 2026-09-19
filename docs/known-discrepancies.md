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

## 2. Cloud behaviour here is statically validated, not tested

Every cloud claim in this repository comes from Anthropic's documentation and from local
inspection of file formats, git object modes and script behaviour. **No cloud session has
executed any of it.** `cloud/SMOKE-TEST.md` exists precisely because that gap is real, and
nothing in this repository should be read as reporting a tested outcome until a thread has
run it.

Three claims previously asserted here turned out to be wrong when checked against the
documentation, which is the reason for this caution rather than an argument against it:
repository `.claude/commands/` *is* supported in cloud; repo-declared plugins *are*
installed at session start; ripgrep and uv *are* pre-installed. See
`docs/host-integration.md`.

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

The file belongs to the rtk install, not to this toolkit, so it is recorded here rather than
patched.
