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

## 2. The seventh skill's cloud delivery is not established, and the gate is written

`checkable-findings` was added on 2026-09-21, making seven canonical skills. **No fresh cloud
session has run since.** Everything this repository says about skills being discovered in a
cloud session was measured when it carried six, and it has been scoped rather than updated:

- `docs/platforms/claude-code.md` reads "all six skills **this repository carried at the
  time** are discovered — verified, cloud session 2026-09-20", with a separate row marking
  the seventh **not established**.
- `docs/host-integration.md`'s "33 skills loaded in the smoke test" is likewise scoped to
  when this repository carried 33, and is history rather than a current-state claim.

Editing either into a seven-skill claim would be the exact failure section 1 is about: a
correction asserted from expectation rather than from a run. The measurement is cheap and it
has not been taken.

**What the gate has to establish**, and the fifth item is the one that is easy to fake:

1. all seven canonical skills are discovered by the harness;
2. all seven `.claude/skills/` entries resolve;
3. `checkable-findings` appears under its intended name and description;
4. it can be invoked through the harness's skill mechanism;
5. **invocation loads the body as active instructions** — not merely that the file is
   readable.

Point 5 needs a discriminator, because points 1–4 are all satisfied by a session that simply
read the file. The one written for this asks questions whose answers exist **only in the
skill's body and nowhere in its description**, with file-reading tools forbidden, and
requires the tool log to show the path was never opened. A pass on the questions with a read
in the log establishes 1–4 and says nothing about 5.

Until that session runs and reports, the honest status is `NOT ESTABLISHED` — not
`INCONCLUSIVE`, and not an assumption carried over from the six.

**A first attempt on 2026-09-22 did not execute the gate**, and the reason was the checkout,
not the packaging. The fresh session started on `main` at `8b2b797` — naming the branch and
the commit in the project metadata did not cause that ref to be checked out. On the tree it
actually got, all six skills that commit carries were discovered and all six
`.claude/skills/` entries resolved; `checkable-findings` was absent from the filesystem and
from the harness enumeration, invoking it failed closed with *"Unknown skill"*, and the
body-injection questions were void because no body existed to inject.

That is a **target-checkout failure and a gate not executed**. It is not evidence about the
seventh skill, whose commit the session never had. Two things it does support, both about the
six-skill tree it did get: discovery and entry resolution work in a fresh cloud session, and
an absent skill fails closed rather than silently resolving to something else.

What the commit itself carries, checked here at the object level rather than inferred: at
`2f68916` there are seven `SKILL.md` files under `skills/`, seven `.claude/skills/` entries
all stored with git mode `120000` and targets `../../skills/<name>`, and `.agents/skills`
stored as a symlink to `../skills`. The packaging is right in the object; what has not been
established is that a harness discovers it from a fresh clone.

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
