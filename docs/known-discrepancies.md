# Known discrepancies

Things that are not what they appear to be. Recorded rather than silently corrected,
because each one is in a file this toolkit does not own.

Two discrepancies that were here are about one machine rather than about this toolkit —
an attribution claim in a rule file, and `rtk`'s own upgrade advice. They moved to
`profile/known-discrepancies.md` on 2026-09-20. What remains is the one that is about
this repository's own claims.

## 1. Cloud behaviour is now part measured, part still only documented

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

`docs/host-integration.md` now separates *measured* from *documented*. The one cell it called
untested — whether a session that **spawns** with the settings file already on the default
branch behaves differently from one where the file appeared mid-life — was closed the same day:
a clean startup run delivered no plugins either, with settings loading without error and the
reconcile completing without failure.

That leaves a three-way split which this repository should keep intact:

- **Verified:** in the tested Anthropic-hosted cloud environment on 2026-09-20, project-scoped
  `enabledPlugins` and `extraKnownMarketplaces` did not deliver the declared plugins at fresh
  startup.
- **Best-supported but not proven:** that the reconcile ignores project-scoped plugin
  declarations. Only its inputs, counters and outputs were observed.
- **Not established:** that this holds across every Claude Code version or cloud configuration.

The habit this section is really about survives the result. The caution was right, the
correction that replaced it was wrong, and the thing that settled it was neither — it was a run.
