# Research workflow

Investigate an open question and produce an answer that says what the evidence supports —
and what it does not.

## Use this when

- The question is open: nobody knows the answer, not just nobody has looked it up.
- Several areas need surveying and it is not clear in advance which one matters.
- The answer will inform a decision, so being confidently wrong is expensive.
- Breadth matters: a single investigator will find one plausible answer and stop.

## Do not use this when

- The answer is retrievable. Look it up.
- The question is narrow and within one domain. One `Specialist` is the right shape.
- Nobody has stated what would count as an answer. Settle the acceptance criteria first —
  otherwise synthesis has nothing to cite against and review has nothing to judge.

## Shape

```text
   Explorer   Explorer   Specialist        parallel, disjoint regions,
      │          │           │             no cross-talk until reports are in
      └──────────┼───────────┘
                 ▼
          consolidate                      deterministic; not an agent
                 ▼
              Critic                       attack the findings
                 ▼
            Validator                      check what can be checked
                 ▼
          Synthesizer                      compose from what survived
                 ▼
         Final Reviewer
     PASS │ REVISE │ REJECT
```

## Stages

### 1 · Investigate — `Explorer` and `Specialist`, parallel

Findings are reported per [`checkable-findings`](../skills/checkable-findings/SKILL.md) — one claim each, with a locator, the evidence as recorded
and an `observed`/`inferred`/`unresolved` status — because stage 2 consolidates on content
and cannot deduplicate what is written as prose.

This is the stage parallelism genuinely earns its cost, and the reason is not speed.
Sequential investigation **anchors**: once one theory has been explored, everything after is
biased toward it. Independent investigators do not share that anchor.

Three conditions, all required:

- **Disjoint regions.** Two agents on the same region report the same things, and neither
  covers what was missed.
- **No cross-talk until reports are in.** Investigators who compare notes mid-run converge,
  and convergence looks like corroboration while being contagion.
- **Separate contexts.** A shared context is a shared prior.

Use `Specialist` where a region needs domain depth, `Explorer` where it needs mapping.

→ findings with locators and epistemic grade, open questions, failed approaches

### 2 · Consolidate — deterministic, no agent

Before anything judges the findings, deduplicate them. This is a decision, not a judgement,
and it needs no model call.

- Deduplicate on **content**: the normalised claim plus what the evidence actually is. A
  reworded duplicate is a duplicate.
- **Keep every original source visible.** "Three investigations independently found this"
  must stay inspectable without becoming three votes.
- **Two agents that read the same source have not corroborated anything.** Independent
  corroboration counts; repetition does not.
- Open a **conflict** where findings actually contradict — incompatible values, or an explicit
  contradiction. Disagreement in tone is not a conflict.

### 3 · Criticise — `Critic`, not an investigator

[`adversarial-review`](../skills/adversarial-review/SKILL.md) over the consolidated findings.
Which are load-bearing? Which rest on an unexamined assumption? Which are inference presented
as observation?

Where findings conflict, the Critic attacks **both sides**. Passing it only the side you find
convincing produces a review of your preference.

→ `PASS` / `CHALLENGE` / `INCONCLUSIVE`, issues identified

### 4 · Validate — `Validator`, neither investigator nor Critic

[`independent-validation`](../skills/independent-validation/SKILL.md) on the findings that
matter.

Most research findings **cannot** be mechanically checked, and that is the important part.
For each load-bearing finding, decide honestly: is this **verified** against external
evidence, or **reviewed** judgement? Label it and move on. An unverifiable finding marked
validated is more dangerous than one honestly labelled — see
[`evidence-verification`](../skills/evidence-verification/SKILL.md).

→ per-finding grade, issues resolved by identifier, what could not be checked and why

### 5 · Synthesise — `Synthesizer`, given a closed set

[`evidence-backed-synthesis`](../skills/evidence-backed-synthesis/SKILL.md). The support is
selected **for** it; it does not go looking for more.

The failures to watch for are the ones fluent writing causes: gaps filled by transition
sentences, hedges upgraded between finding and answer, verified and reviewed flattened into
one confident voice, a conflict quietly resolved in favour of the more convincing side.

→ one answer, citations at claim level, limitations, unresolved conflicts

### 6 · Final review — `Final Reviewer`, independent of every producer

[`final-verification`](../skills/final-verification/SKILL.md), criterion by criterion. For
research specifically: **is the limitations section honest?** The gaps an answer does not
mention are the ones that mislead.

## Independence requirements

```text
investigators                 independent of each other, and of their reviewers
Critic ≠ any investigator
Validator ≠ any investigator, ≠ Critic
Synthesizer ≠ the investigators whose findings it assembles (where possible)
Final Reviewer ≠ every producer of a candidate answer
```

The investigator-to-investigator independence is specific to this workflow and is the reason
it works. Everywhere else, independence protects review; here it also protects the
investigation.

## Termination

| Terminal state | When |
|---|---|
| `COMPLETED` | Final Reviewer `PASS`; every required criterion answered by support that still stands; limitations stated. |
| `EXHAUSTED` | Investigation rounds spent, or the evidence cannot settle the question. **Report the partial answer, what is uncovered, and precisely what evidence would settle it.** |
| `FAILED` | The question could not be investigated at all — no access, no sources, incoherent question. |

`CANCELLED` is the fourth terminal state. This workflow cannot reach it by working, because it is imposed from outside the run, but any run may end in it — see [terminal states](README.md).

**`EXHAUSTED` is the terminal state research workflows most need and most often lack.** A research
process that cannot say *"the evidence does not settle this, and here is what would"* will
instead produce a plausible answer to a question it could not answer. That failure is
invisible, because the output looks exactly like success.

State up front how many investigation rounds are allowed.

## Re-exploration, if you allow it

A second round is worth opening only when there is **something concrete to investigate**: an
unresolved conflict, a specific gap a named investigation would close, a follow-up a first
round asked for.

There is no path from "keep looking" to another round. An agent's appetite for more
investigation is not a trigger; a named, consumable gap is.

## Scaling it down

| Situation | Minimum |
|---|---|
| Two or three areas, low stakes | Two investigators → Critic → Synthesizer. Drop separate validation; grade findings inline. |
| One area | One `Specialist` → `Critic`. This workflow is overhead. |
| One agent available | Investigate, then review in a **fresh context**, then synthesise — as a degraded self-check. |

A fresh context of the same identity is a **disclosed degraded self-check**, not independent review: it may be run and must be labelled as what it is, and it satisfies no criterion that requires independence. Where completion requires independent review and no independent identity exists, the honest terminal state is `EXHAUSTED` — see [independence](../docs/concepts/independence.md).

Never drop: **the honest grading of what is verified versus reviewed**, and **the limitations
section**. Those are what make a research answer usable rather than merely confident.

## Common failure modes

| Failure | What it looks like |
|---|---|
| Convergence mistaken for confirmation | Investigators compared notes and agreed. Nothing was corroborated. |
| Duplicate as evidence | The same fact from three agents, read as three-fold support. |
| Anchoring | Sequential investigation; everything after the first theory was framed by it. |
| Overlapping regions | Two investigators covered the same ground; a third region went unexamined. |
| Grade flattening | Judgement and measurement presented identically in the answer. |
| Empty limitations | "None identified", with three questions unanswered. |
| Silent conflict resolution | Findings disagreed; the answer reflects one side, with no note. |
| No stopping condition | Investigation continued until the budget ran out and was then called complete. |
