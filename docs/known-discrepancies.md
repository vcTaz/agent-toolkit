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

## 2. The seventh skill's cloud delivery: invocation established, session-start discovery not

**The gate ran on 2026-09-22**, in a cloud session at Claude Code 2.1.278, against commit
`713a61a` of `claude/phase-2a-canonical-core-ej50lt`. It was written up in the Project thread
that ran it. The result splits, and the split is the point:

**Established.** Points 2, 3, 4 and 5 of the list below. All seven `.claude/skills/` entries
resolve under `skills/<name>`; `.claude/skills` is a real directory and `.agents/skills` a
container symlink to `skills/`. `checkable-findings` appears under its intended name with its
intended description. `Skill(checkable-findings)` reported base directory
`.claude/skills/checkable-findings` and returned the whole body, and no file-reading tool
touched the skill's path at any point in that session.

**Not established.** Point 1, in the sense the gate meant it. The session started on `main` at
`8b2b797`, which carried six skills, because the environment was never pointed at the branch.
The seventh entered the harness's skill list only after a mid-session `git checkout`, which
the harness re-enumerated on the next skill call. Session-start enumeration of this symlink
layout is measured at six entries and has never been measured at seven.

**A defect in the gate itself, recorded rather than smoothed over.** Point 5's discriminator
was three questions whose answers exist only in the skill's body. The session answered all
three correctly with a clean tool log — but it had been handed the expected answers in its own
brief, so its recall carries no weight. What carries the weight is the recorded invocation
output, which is a primary artifact and shows the body arriving as active instructions. A
rerun that wants the discriminator to work must withhold the expected values from the session
running it.

**What the gate had to establish**, and the fifth item is the one that is easy to fake:

1. all seven canonical skills are discovered by the harness;
2. all seven `.claude/skills/` entries resolve;
3. `checkable-findings` appears under its intended name and description;
4. it can be invoked through the harness's skill mechanism;
5. **invocation loads the body as active instructions** — not merely that the file is
   readable.

`docs/platforms/claude-code.md` carries both halves as separate rows. The six-skill row stays
scoped to the six that existed when it was measured; nothing here has been edited into a
seven-skill session-start claim, which would be the exact failure section 1 is about.

`docs/host-integration.md`'s "33 skills loaded in the smoke test" is likewise scoped to when
this repository carried 33, and is history rather than a current-state claim.

## 3. `checkable-findings`'s body size is accepted, not established as optimal

The skill grew twice on 2026-09-21 while closing defects found by running it: from 188 lines
and 1,530 words when it was introduced to 251 lines and 2,342 words, which makes it the
largest skill body in this repository. That size is **accepted for Phase 2A and deliberately
not compressed** — a compression pass before the delivery gate would change the artifact the
gate is about, and the growth bought rules that observed failures required.

What is *not* established is that the size is right. Nothing here has measured whether a
shorter body produces the same behaviour. The two claims should stay apart:

- **Measured:** the discovery-time cost did not move. Name plus description is 557 characters
  for this skill and 3,458 across the seven, 43.2% of the 8,000-character fallback that
  `docs/platforms/codex.md` documents. The skill-list budget is what the admission criteria
  are about, and it is unchanged.
- **Not established:** that the body's per-invocation cost is justified at this length. Body
  text is paid on every invocation and no measurement here bounds it.

**Post-merge dogfooding item.** After several real invocations — not fixture runs — compare
this skill's behaviour against a behaviour-preserving compression of it, on the same inputs,
and keep the shorter one only if the findings it produces carry the same identities, statuses,
locators, evidence and boundaries. A compression that loses a rule is not behaviour-preserving,
and "it reads tighter" is not the measurement.
