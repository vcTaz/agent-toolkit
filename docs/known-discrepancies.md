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

## 2. The seventh skill's cloud delivery, established 2026-09-22 in a validation repository

`checkable-findings` was added on 2026-09-21, making seven canonical skills, and for a day
everything this repository said about cloud skill discovery had been measured when it carried
six. That gap is now closed by a run, and the run's scope is the point of this section.

**What was measured**

- Claude Code **2.1.278**, on **2026-09-22**.
- A **fresh cloud session** — not a mid-session checkout, which cannot establish fresh-start
  discovery.
- A **temporary validation repository** whose `main` was exactly
  `2f68916d21c21ced2a88d18a5f6f17349a2e1eb2`, the commit object itself rather than a
  recreated tree.
- **Seven** canonical skills discovered by the harness.
- All **seven** `.claude/skills/` entries resolved.
- `checkable-findings` invoked successfully **through the Skill mechanism**.
- Its **body injected as active instructions**, demonstrated by three body-only answers with
  **no file read** in the tool log: 7 contract rows with `Identity` first; `SETTLES IT` then
  `BOUNDARY` after `EVIDENCE`; `Smuggled conditional` as the last failure-mode row.

That last item is the one worth keeping separate, because points one to four above are all
satisfied by a session that simply read the file. The discriminator asks questions whose
answers exist **only in the skill's body and nowhere in its description**, forbids
file-reading tools, and requires the tool log to show the path was never opened. A pass on
the questions *with* a read in the log would have established the first four and said nothing
about the fifth.

**What it does not cover.** The run measured that tree at that commit. Delivery from this
repository's own `main` carries the same shape but is a separate checkout and was not the
thing measured; Codex discovery through `.agents/skills` remains documentation-derived; and
none of it is a claim about whether the skill improves output.

`docs/host-integration.md`'s "33 skills loaded in the smoke test" is untouched by this. It is
scoped to when this repository carried 33 and is history, not a current-state claim.

### The attempt that did not execute, and why the validation repository existed

**A first attempt on 2026-09-22 did not execute the gate**, and the reason was the checkout,
not the packaging. The fresh session started on `main` at `8b2b797` — naming the branch and
the commit in the project metadata did not cause that ref to be checked out. On the tree it
actually got, all six skills that commit carries were discovered and all six
`.claude/skills/` entries resolved; `checkable-findings` was absent from the filesystem and
from the harness enumeration, invoking it failed closed with *"Unknown skill"*, and the
body-injection questions were void because no body existed to inject.

That is a **target-checkout failure and a gate not executed**. It is not evidence about the
seventh skill, whose commit the session never had, and it was not repaired by checking the
ref out mid-session. Two things it does support, both about the six-skill tree it did get:
discovery and entry resolution work in a fresh cloud session, and an absent skill fails
closed rather than silently resolving to something else.

The fix was to give the commit its own repository, where it **is** `main`, so the checkout
could not land anywhere else — which is also why the passing run above names a validation
repository rather than this one.

What the commit itself carries was checked here at the object level rather than inferred:
at `2f68916` there are seven `SKILL.md` files under `skills/`, seven `.claude/skills/`
entries all stored with git mode `120000` and targets `../../skills/<name>`, and
`.agents/skills` stored as a symlink to `../skills`.

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

## 4. K-Dense: the manifest says nothing landed, the Phase 2B record says it did

Recorded 2026-09-24, during the Phase 3A design, and **recorded here only**. This one is in a
file this toolkit does own, `manifest/external-skills.json`, and it is not corrected because
Phase 2B is closed and correcting it would reopen that phase. That decision is the
maintainer's, and it was made deliberately.

The two statements:

- **The manifest.** The `K-Dense-AI/scientific-agent-skills` row is `REFERENCE_ONLY`, and its
  basis begins *"Nothing from it landed in Phase 2A"*.
- **The Phase 2B implementation plan**, a working document outside this repository, says the
  sufficiency rows that did land in `skills/evidence-verification/SKILL.md` — *"the capability
  is available"* and *"the limit is N"* — *"absorbed K-Dense's 'unknown is not unlimited'"*.
  The Phase 2 external-source audit traces the same clause to K-Dense's
  `get-available-resources`.

Why it matters: the manifest's `bucketRule` is an ordered procedure, and its step 2 asks
whether anything from a repository landed in the canonical layer in Phase 2A. If the clause
counts as having landed, K-Dense is `IDEAS_ALREADY_ABSORBED`, not `REFERENCE_ONLY`.

What is **not** settled, and is a judgement rather than a measurement: whether a clause that
was re-derived and rewritten in this repository's own words, rather than copied, counts as
"landing" for step 2. Reading the row as "nothing from K-Dense landed" is also defensible. The
row stays as it is, byte-identical, until a new ask reopens Phase 2B deliberately.
