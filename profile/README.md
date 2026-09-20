# profile/

**One person's machine and account. Nothing in this toolkit needs any of it.**

This tier exists to answer a question a reader could not previously answer: which of these
files describe the toolkit, and which describe the machine it happened to be built on. Every
file here is the second kind. A different machine has a different `profile/`, or none, and the
toolkit is unaffected either way.

| File | What it records | Moved from |
|---|---|---|
| `settings.fragment.json` | hooks, permissions and preferences from one Claude Code settings file | `local/` |
| `plugins.json` | the marketplaces and plugins installed on one account | `manifest/` |
| `machine-binaries.json` | `rtk`, `srt`, `bwrap`, `socat` and one un-remoted repository | `manifest/binaries.json` |
| `known-discrepancies.md` | two things that are not what they appear to be, in files on that machine | `docs/` |

All four moved on 2026-09-20. Nothing was deleted, and nothing was rewritten beyond the
pointers and the section numbering.

## Nothing here is applied unless you ask

```bash
./local/bootstrap.sh --with-plugins    # marketplaces and plugins from plugins.json
./local/doctor.sh --profile            # check the machine-specific material
```

A default `bootstrap.sh` links the canonical roles and skills and nothing else. A default
`doctor.sh` run does not so much as mention this directory: a machine with no `rtk` and no
plugins is a correct machine as far as the toolkit is concerned, and warning about it
unprompted is the same defect the binary tiers already fixed one level up.

## `settings.fragment.json` is not portable, and says so in machine-readable form

Its `requires` key lists what this repository does **not** contain and cannot supply:

- five hook scripts under `$HOME/.claude/scripts/hooks/` — `auto-tmux-dev.js`,
  `post-bash-command-log.js`, `run-with-flags-shell.sh`, `run-with-flags.js`,
  `session-start-bootstrap.js`
- the `ecc` plugin's own `scripts/hooks/`, resolved at run time from `CLAUDE_PLUGIN_ROOT` or a
  plugins cache; the `Stop` and `SessionEnd` hooks degrade to a warning when it cannot be
  resolved
- `node` and `jq`

Copying the fragment onto a machine without those gets you hooks that fail. The key is there
so a tool reading the file sees the prerequisites too, not only a human reading prose.

## Why `plugins.json` now carries two settings keys

`enabledPlugins` and `extraKnownMarketplaces` used to live in this repository's own
`.claude/settings.json`. They were **verified on 2026-09-20** not to deliver plugins at fresh
startup in the tested Anthropic-hosted cloud environment: the reconcile ran, reported no
failure, and installed none of them. Keeping them in the repository's settings asserted a
capability the repository does not have.

They are correct on a local machine, so they were moved rather than deleted, into
`claudeCodeSettings` here, and `local/bootstrap.sh --with-plugins` applies them. The deny
rules stayed in `.claude/settings.json`, which now contains those and nothing else: deny rules
are additive, can only tighten a session, and were measured to load and enforce in cloud.

Keep the three claim tiers apart when reading `plugins.json`: the delivery failure is
**verified** for the tested environment, the *cause* is **best-supported but not proven**, and
any universal claim about plugins in cloud is **not established**.

## This tier is not canonical and not portable

It defines no concept. `tools/check.py` refuses any reference to it from `roles/`, `agents/`,
`skills/` or `workflows/`, which is checked rather than reviewed — see the invariants in
`AGENTS.md`.
