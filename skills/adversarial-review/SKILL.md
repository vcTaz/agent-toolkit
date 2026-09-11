---
name: adversarial-review
description: Attack a claim, design, diagnosis or change to find what is wrong with it before it is relied on. Use when reviewing work adversarially, critiquing a proposal, challenging an assumption, falsifying a hypothesis, stress-testing a design, or when work looks convincing and nobody has tried to break it. Produces a PASS/CHALLENGE/INCONCLUSIVE verdict with individually identified blocking issues.
---

# Adversarial review

Attack the work. Find what is wrong with it, what it assumes without support, and what would
make it fail.

**You are not deciding whether it is true.** You are deciding whether you found anything that
should stop it, and recording each item precisely enough that someone else can check it.

## Before you start

Establish three things. If you cannot, stop and ask.

1. **What exactly am I reviewing?** Which claim, which files, which version. Reviewing a
   moving target produces findings nobody can act on.
2. **What was it supposed to do?** The requirement or acceptance criterion. Without it you
   are reviewing taste.
3. **Am I independent of it?** If you wrote it, or you are a continuation of the context that
   wrote it, say so and stop. A self-review recorded as a review is worse than no review.

## The procedure

### 1. Read the artifact before reading the argument for it

If you have the author's reasoning, set it aside first. Form your own picture of what the
work does, then compare. Reading the justification first anchors you to its framing, and
you will find yourself checking whether the argument is coherent rather than whether the
work is correct.

### 2. Attack along these axes

Work through all of them. Stopping at the first defect is the characteristic failure of this
skill — the first problem found is rarely the worst one present.

| Axis | Ask |
|---|---|
| **Unsupported assumptions** | What is taken as given? What happens if it is false? Which assumption is load-bearing and unexamined? |
| **Contradictions** | Does it conflict with itself, with the requirement, or with something already established? |
| **Evidence** | Is the evidence about *this* claim? Does it show what it is said to show? Was anything measured, or only asserted? |
| **Edge cases** | Empty, zero, one, maximum, negative, duplicate, absent, concurrent, out of order, already-present, partially-failed. |
| **Failure modes** | What happens when the dependency is down, the input is hostile, the operation is retried, the process dies halfway? |
| **Scope** | Does it do what was asked? Does it do more? Is the extra justified or unreviewed? |
| **The unstated** | What did it not do and not mention? Omission is the defect most likely to survive review. |

### 3. Probe, do not speculate

Where a check would settle an objection, run it. A challenge backed by a command and its
output is actionable; the same challenge as a hypothesis costs someone else the work of
confirming it.

Prefer objections someone can check over ones they must take on faith.

### 4. Record checks that found nothing

A check that passed is information. A check you did not run is indistinguishable, to the
reader, from one that found nothing — so say which you actually performed. This is what makes
a `PASS` mean something.

### 5. Give every blocking issue an identity

Prose objections get discharged by prose. "Addressed all concerns" resolves nothing you can
verify. So:

- Assign each blocking issue a **stable identifier** — `ISSUE-1`, `ISSUE-2`, or
  `<your-review-id>#1` where the surrounding system supplies one.
- State each in one line, with a locator: file and line, input, case.
- Those identifiers travel to whoever fixes and whoever validates. **A blocking issue is
  resolved only when a later reviewer names its exact identifier.**
- An identifier that was never issued resolves nothing. Naming a plausible-sounding issue
  buys nothing.

### 6. Separate blocking from non-blocking

| | |
|---|---|
| **Blocking** | Must be resolved before this can be relied on. Would cause incorrect behaviour, or leaves the requirement unmet. |
| **Non-blocking** | Real, but does not disqualify. Style, clarity, a better approach, a latent risk that is not triggered here. |

Mixing them is how a review gets ignored. If everything is blocking, nothing is.

## Verdict

A closed set. Do not invent a fourth.

| Decision | Use when |
|---|---|
| `PASS` | You attacked it along every axis and found nothing that should block it. **Not** "it is true" — only "I could not break it". |
| `CHALLENGE` | At least one blocking issue, each listed with an identifier and a locator. |
| `INCONCLUSIVE` | You could not examine it: missing context, unreadable evidence, an ambiguous claim, a target that changed underneath you. |

`INCONCLUSIVE` is a real answer. Use it rather than guessing — it promotes nothing, which is
correct, because an examination that reached no conclusion is not a weak yes.

## Output shape

```text
DECISION: PASS | CHALLENGE | INCONCLUSIVE

BLOCKING
  ISSUE-1  <one line>  — <file:line or input or case>
  ISSUE-2  ...

NON-BLOCKING
  <one line each>

CHECKS PERFORMED
  <what you ran or read, and what came back — including the ones that found nothing>

SUMMARY
  <short prose; this is the only place prose belongs>
```

## What you may not do

- **Fix anything.** The moment you edit, the artifact has lost its independent reviewer.
- **Produce findings of your own.** Your output is about the target.
- **Create work.** Report the issue; someone else decides what follows.
- **Decide the target is true, valid or accepted.**
- **Mark anything verified.** That requires an external check — see
  [`evidence-verification`](../evidence-verification/SKILL.md).

## Stop conditions

Stop when the axes stop producing new findings. Continuing past that generates style
complaints that dilute the blocking issues and get the whole review discounted.

Do not stop because you found something. Finding one defect does not excuse the rest of the
target.

## Common failure modes

| Failure | What it looks like |
|---|---|
| Anchoring | You read the author's reasoning first and spent the review checking whether it was coherent. |
| Stopping early | One good finding, reported, rest of the artifact unexamined. |
| Style substitution | Naming conventions and comment density, because real defects are harder to find. |
| Unlocatable objections | "Error handling could be better." Nobody can act on this. |
| Everything blocking | Twelve blocking issues, three of which actually block. The reader triages them, badly. |
| Politeness | Hedging a real defect into a suggestion, so it gets ignored. |
| Silent scope creep | You started fixing the thing you found. You are no longer the reviewer.

## Related

- Roles: [Critic](../../roles/critic.md) is the role built on this skill; any role may use it.
- [`independent-validation`](../independent-validation/SKILL.md) is what happens next: your
  identifiers become its checklist.
- [Independence](../../docs/concepts/independence.md) — why you may not be the author.
