---
name: evidence-backed-synthesis
description: Compose an answer or report from established findings, citing what carries each claim and declaring what the evidence does not settle. Use when assembling findings from several agents or investigations into one deliverable, when writing a conclusion that others will rely on, when consolidating duplicate findings before reporting, or when a report must not claim more than its evidence supports.
---

# Evidence-backed synthesis

Turn a set of established findings into one coherent answer that says what they support,
cites what carries each part, and is honest about what they do not settle.

The discipline is **negative**. Everything that makes a model good at writing — filling gaps,
smoothing transitions, resolving tension into a clean narrative — is exactly what makes this
dangerous. The constraint:

> **Introduce no claim that the supplied support does not carry.**

## Before you start

1. **Is the support established?** Synthesising unchecked candidates produces a well-written
   answer resting on nothing.
2. **Is the support closed?** Your material is what you were given. If it is insufficient,
   *that is the finding to report* — not a licence to go and get more.
3. **Do I have the acceptance criteria?** You cite against them.
4. **Do I know what is unresolved?** Open conflicts, recorded gaps, branches that stopped
   without contributing. You must state these; you cannot state what you were not told.

## The procedure

### 1. Consolidate before you compose

Two agents finding the same thing is **one finding with two sources**, not two pieces of
evidence.

- Deduplicate on **content**: the normalised claim plus what the evidence actually is — not
  its per-run identifiers, and not its wording. A reworded duplicate is a duplicate.
- **Keep every original source visible.** "Three investigations independently found this"
  stays inspectable, and does not become three votes.
- **Independent corroboration is worth noting; repetition is not.** Two agents that both read
  the same file have not corroborated anything.

### 2. Separate the grades and keep them separate

| | |
|---|---|
| **Verified** | external evidence entails it — may be relied on |
| **Reviewed** | independent judgement found no defect — may be acted on, and may be wrong |
| **Unresolved** | asked and not settled |

Carry these through into the answer. The most common failure of this skill is flattening all
three into one confident voice.

### 3. Surface conflicts; do not resolve them

Where the support disagrees with itself, say so. Do not pick the side you found more
convincing — you are not the role with the authority to settle it, and choosing silently
destroys the information that a disagreement existed.

### 4. Cite at the claim level

For every required criterion and every material claim, name which support carries it.

- "Based on the findings above" is not a citation.
- A claim in your answer with nothing behind it is a defect, not a stylistic choice.
- **Cite only what you were given**, and only what still stands.

### 5. Do not upgrade hedges

This is where synthesis quietly manufactures confidence. Check each claim against its source:

| Source said | Answer must not say |
|---|---|
| "in the cases we measured" | "always" |
| "appears to be" | "is" |
| "one likely cause" | "the cause" |
| "no issues found in the paths tested" | "no issues" |

### 6. State the limitations plainly

Include:

- Questions that were asked and not answered.
- Criteria with no support, or partial support.
- Conflicts left open.
- What the evidence covered, and what it did not.
- Where a conclusion is reviewed judgement rather than verified fact.

**Absence of evidence is not absence of risk**, and must not be written as though it were.

A limitations section that says "none" is almost always wrong. If nothing was unresolved,
say what was checked and what was out of scope.

### 7. Answer the question that was asked

An answer that is accurate, well-cited and about something adjacent is a failure. Re-read the
objective last, before you finish.

## Output shape

```text
ANSWER
  <addresses the objective>

COVERAGE
  criterion-1  ← finding-a, finding-c
  criterion-2  ← finding-b
  criterion-3  ← NOT COVERED: <what is missing>

CLAIMS AND SUPPORT
  <material claim>  ← <what carries it>  [verified | reviewed]

CONFLICTS
  <where the support disagrees, both sides, unresolved>

LIMITATIONS
  <what the evidence does not settle; what was not examined>

SUMMARY
```

## What you may not do

- **Introduce a factual claim no supplied support carries.** The defining prohibition.
- **Cite what you were not given**, or anything withdrawn.
- **Go and find more support.** Your material is closed.
- **Create findings, produce evidence, or request work.**
- **Declare a criterion covered.** Cite what covers it; coverage is recomputed from your
  citations.
- **Resolve a conflict by choosing.**
- **Smooth over a gap.** Confident prose across missing evidence is the most damaging thing
  this skill can produce.
- **Call your own output final, verified or complete.** It is one candidate, pending
  independent judgement.

## The legitimate failure outcome

If the supplied support cannot answer the objective, **say exactly that**, naming which
criteria are uncovered and what is missing.

This is a valuable result, not a failed one. A report that ends with *"the evidence did not
settle this, and here is precisely what would"* is worth more than a confident answer nobody
can defend. Systems that cannot produce this outcome produce plausible answers to questions
they could not settle.

## Common failure modes

| Failure | What it looks like |
|---|---|
| Gap-filling | A transition sentence that asserts something no finding supports. |
| Hedge upgrade | "In our tests" became "always" between the finding and the answer. |
| Grade flattening | Measurement and opinion in one confident voice. |
| Duplicate as corroboration | The same fact from three agents, read as three-fold support. |
| Silent conflict resolution | Two findings disagreed; the answer reflects one, with no note. |
| Decorative citations | Citations present, but not at the claim level and not checked. |
| Empty limitations | "None identified", when three questions went unanswered. |
| Answering adjacently | Accurate, well-supported, and not the question asked. |

## Related

- Roles: [Synthesizer](../../roles/synthesizer.md) is the role built on this skill.
- [`evidence-verification`](../evidence-verification/SKILL.md) — where the grades come from.
- [`final-verification`](../final-verification/SKILL.md) — what judges your output next.
- [Orchestration O13, O19](../../docs/concepts/orchestration.md) — consolidation and using
  only what you were given.
