---
name: final-verification
description: Judge a completed deliverable against its requirements and decide PASS, REVISE or REJECT. Use before accepting, shipping or reporting finished work, when deciding whether a run is genuinely done, when assessing whether an answer meets its acceptance criteria, or when checking that cited support still stands and limitations are honest. Classifies a REVISE as needing evidence, needing rewriting, or locating nothing.
---

# Final verification

Judge **the finished deliverable as a whole**, against what was actually asked for.

Not "is this claim true" — that was validation. Not "what is wrong with this" — that was
adversarial review. The question here is narrower and harder: **is this acceptable?**

## Before you start

1. **Do I have the acceptance criteria as originally stated?** Without them you are reviewing
   taste. Get them before anything else.
2. **Am I looking at one exact version?** If it changes while you review, you are assessing
   something that no longer exists.
3. **Am I independent?** You must not have produced *any* candidate answer in this run — not
   just this version. A reviewer who wrote an earlier draft is judging their own approach.
4. **Is it actually finished?** Reviewing a draft as a deliverable produces a `REVISE` that
   says only "it is not done".

## The procedure

### 1. Go criterion by criterion

This is the whole job, and impression-forming is the way it gets skipped. For **each required
criterion**, in order:

- Does the deliverable address it?
- What does it cite as support?
- Does that support actually carry it?
- Does that support still stand right now?

Record a per-criterion verdict. A summary judgement over the whole document cannot be acted
on and cannot be checked.

### 2. Recompute coverage from citations, never from claims of coverage

A deliverable saying "this satisfies criterion 3" is not evidence that it does. Look at what
it actually cites, and derive coverage from that. A declaration cannot manufacture support.

### 3. Check that cited support still stands

Between synthesis and review, a claim may have been withdrawn, a test deleted, a dependency
changed. **A citation to withdrawn support is a blocking issue**, even when the sentence it
supports is still true.

### 4. Check the unresolved findings

What did the work leave open? Blocking issues never resolved, conflicts never settled,
branches that stopped without contributing, recorded gaps. For each, ask: **should this have
stopped acceptance?**

A deliverable that is silent about an unresolved conflict is misleading regardless of whether
every sentence in it is accurate.

### 5. Check the limitations are honest

What the evidence did not settle must be stated, not smoothed over. Look specifically for:

- Questions that were asked and not answered.
- Reviewed judgement presented in the same confident voice as verified fact.
- Scope inflation — evidence for some cases, conclusions for all.
- Absence of evidence presented as absence of risk.

### 6. Separate "I would have done it differently" from "it does not meet the requirement"

If it meets the requirement by a route you would not have chosen, that is a non-blocking
observation. Rejecting on preference destroys the value of the verdict, because the next
reader cannot tell your standards from the requirement.

## Verdict

| Decision | Use when |
|---|---|
| `PASS` | Every required criterion is met by support that still stands, and nothing unresolved should have stopped it. |
| `REVISE` | Fixable. Name what is wrong and where. |
| `REJECT` | Not a viable candidate; a revision would not save it. |

**Name the fault.** A `REVISE` or `REJECT` that locates nothing is the worst outcome
available: it blocks acceptance and gives nobody anything to act on.

### Classify what a REVISE requires

Whoever acts on your verdict must know which kind it is. Determine it from the record, not
from how the complaint was phrased:

```text
a required criterion has no support               → EVIDENCE   more work is needed
a citation no longer stands                       → EVIDENCE
you named claims that are unsupported             → EVIDENCE
the criterion is covered but the answer omits it  → PRESENTATION  rewrite only
only wording or organisation is at fault          → PRESENTATION
nothing the record confirms                       → NONE
```

- **`EVIDENCE`** sends work back to producing roles. **Prose is never a repair for missing
  evidence.**
- **`PRESENTATION`** goes back to the writer with your issues attached, and nothing new is
  investigated.
- **`NONE`** is the honest third case: you disagreed, but pointed at nothing the record
  confirms. Neither prose nor evidence can act on it. Say so explicitly — this is a real
  outcome and the work should terminate as unresolved rather than loop.

### REJECT does not destroy the findings

A rejected version is discarded **as a candidate**. The established claims underneath survive
— they were validated independently of the answer citing them. Do not phrase a `REJECT` as
though everything found was wrong, unless it was.

## Output shape

```text
DECISION: PASS | REVISE | REJECT
REVISION KIND: EVIDENCE | PRESENTATION | NONE      (when REVISE or REJECT)

COVERAGE
  criterion-1  MET       cites: <what>  — still stands: yes
  criterion-2  NOT MET   <what is missing>
  criterion-3  MET       cites: <what>  — still stands: NO, withdrawn

BLOCKING
  <one line each, naming the criterion or claim at fault>

OBSERVATIONS
  <non-blocking>

UNRESOLVED FINDINGS CONSIDERED
  <what was open, and whether it should have stopped acceptance>

SUMMARY
```

## What you may not do

- **Edit the deliverable.** Not even a typo.
- **Change or re-decide any underlying claim.** Those were settled by identities independent
  of you.
- **Accept it.** You recommend; acceptance is a separate step that re-checks your `PASS`
  against current state.
- **Create work.**
- **Pass on the strength of good writing.** Fluency is not coverage.

## After a PASS

A `PASS` is a statement about the state at review time. Before anything is accepted, re-check
that the criteria still hold and every citation is still valid — work that landed during
review can invalidate what was just approved. Accept in the same step that records
completion, so the two cannot drift.

**A reviewed version is never edited.** A revision creates a new version naming the one it
supersedes, so the version you judged keeps its content, its citations and your verdict.

## Common failure modes

| Failure | What it looks like |
|---|---|
| Impression review | You read it, it seemed good, you passed. No criterion was checked. |
| Trusting declared coverage | It said it covered criterion 3, so you recorded criterion 3 as covered. |
| Stale citations | Every citation checked at synthesis time; one was withdrawn since. |
| Unlocatable REVISE | "Needs more rigour." Nobody can act on it. |
| Prose for evidence | You asked for a rewrite when support was actually missing. |
| Preference rejection | A working deliverable rejected for being built differently than you would. |
| Ignoring silence | The gaps it never mentioned were the ones that mattered. |

## Related

- Roles: [Final Reviewer](../../roles/final-reviewer.md) is the role built on this skill.
- [`evidence-backed-synthesis`](../evidence-backed-synthesis/SKILL.md) — what produced what
  you are judging.
- [Orchestration O18–O22](../../docs/concepts/orchestration.md) — computed readiness,
  immutable versions, and the terminal vocabulary.
