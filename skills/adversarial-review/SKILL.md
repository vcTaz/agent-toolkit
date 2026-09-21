---
name: adversarial-review
description: Attack a claim, design, diagnosis or change to find what is wrong with it before it is relied on, and repair against issues raised that way. Use when reviewing work adversarially, critiquing a proposal, challenging an assumption, falsifying a hypothesis, stress-testing a design, when work looks convincing and nobody has tried to break it, or when acting on a review's blocking issues. Produces a PASS/CHALLENGE/INCONCLUSIVE verdict with individually identified blocking issues, and a per-identifier disposition when those issues are repaired.
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

### 5. Name what you declined to judge

A review is read as covering what it examined *and* what it did not mention. So every
materially relevant issue or area you deliberately chose not to assess is **named**, not
silently omitted:

- outside your competence, and you say which competence it needs;
- outside the scope you were given;
- unexaminable with what you were given — no access, no evidence, a moving target;
- deliberately deprioritised, because something else mattered more within the budget.

"I did not assess the concurrency of the queue consumer" costs one line and tells the reader
exactly where this review is not protection. Leaving it out converts a bounded review into
an unbounded-looking one, which is how an unreviewed area acquires a reviewer's `PASS`.

This is the counterpart of step 4. That one records checks that found nothing; this one
records judgements not made.

### 6. Give every blocking issue an identity

Prose objections get discharged by prose. "Addressed all concerns" resolves nothing you can
verify. So:

- Assign each blocking issue a **stable identifier** — `ISSUE-1`, `ISSUE-2`, or
  `<your-review-id>#1` where the surrounding system supplies one.
- State each in one line, with a locator: file and line, input, case.
- Those identifiers travel to whoever fixes and whoever validates. **A blocking issue is
  resolved only when a later reviewer names its exact identifier.**
- An identifier that was never issued resolves nothing. Naming a plausible-sounding issue
  buys nothing.

### 7. Separate blocking from non-blocking

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

## Repairing against issues

The other half of this skill, and it is performed by a **different identity**. The reviewer
that raised an issue may never repair it — "Fix anything" above is absolute, and the moment a
reviewer edits, the artifact has lost the review it just received. The repairer need not be
the original author; it must not be the reviewer of this artifact.

### 1. Work by identifier, one disposition each

Every issue you were given gets an explicit disposition, by its **exact identifier**:

| Disposition | Means |
|---|---|
| `FIXED` | changed, with the change and its evidence stated |
| `REFUTED` | checked against the artifact and the issue does not hold — with what you checked |
| `DEFERRED` | real, not repaired here, with the reason and what it waits on |
| `NEEDS_CLARIFICATION` | the issue is ambiguous; stated as a question, not guessed at |

An identifier you were not given resolves nothing, and an identifier you were given and did
not mention is unanswered — not implicitly fine.

### 2. Verify the issue against the artifact before acting on it

**Do not apply an issue blindly.** Read the artifact at the locator the issue names and
establish that what it describes is actually there. Reviews are wrong sometimes: against a
version that moved, against a misread, against a rule that does not apply here.

A repair applied to a defect that was not present is a change nobody reviewed, justified by
an issue nobody re-checked. `REFUTED` with your evidence is a legitimate and frequently
correct answer.

### 3. Ask when the issue is ambiguous

If an issue admits two readings that imply different changes, **do not pick one**. Return
`NEEDS_CLARIFICATION` with both readings. Guessing produces a change the reviewer did not ask
for, which then passes as "addressed".

### 4. Re-run the check the issue names

An issue that cites a check, an input, a case or a measurement is discharged by **that
evidence run again**, and its actual output recorded — not by a general check, and not by
your reading of the code. The specific evidence is what the issue was about.

### 5. No performative agreement, no silent scope expansion

- "Addressed all concerns", "all feedback incorporated", "resolved" — these discharge
  nothing. They are prose over a checklist, and the checklist is the point.
- Change **what the issues name**. A refactor you noticed the need for is a finding, not a
  licence; an improvement bundled into a repair makes the repair unreviewable, because the
  reviewer can no longer tell which change answers which issue.

### 6. Stop when the repair outgrows the issue

If fixing an issue would require reopening an assumption, an interface or a scope that the
issue did not question, **stop and report** with what you found. Do not resolve it by
quietly widening the change. That decision belongs to whoever owns the scope, and it needs
evidence of its own.

### 7. You are not the reviewer of your own repair

Producing the fix makes you the author of it. Your dispositions are **claims**, and they are
checked by an identity that is not you — see
[`independent-validation`](../independent-validation/SKILL.md), which resolves issues by the
same identifiers. Do not mark an issue resolved; mark it `FIXED` with evidence and hand it
on. `PASS` is not yours to record.

```text
ISSUE-3   FIXED              <what changed> — <the check re-run, and its actual output>
ISSUE-4   REFUTED            <what you read at the locator, and what it actually says>
ISSUE-7   NEEDS_CLARIFICATION  <reading A implies X; reading B implies Y>
```

## Common failure modes

| Failure | What it looks like |
|---|---|
| Anchoring | You read the author's reasoning first and spent the review checking whether it was coherent. |
| Stopping early | One good finding, reported, rest of the artifact unexamined. |
| Style substitution | Naming conventions and comment density, because real defects are harder to find. |
| Unlocatable objections | "Error handling could be better." Nobody can act on this. |
| Everything blocking | Twelve blocking issues, three of which actually block. The reader triages them, badly. |
| Politeness | Hedging a real defect into a suggestion, so it gets ignored. |
| Silent scope creep | You started fixing the thing you found. You are no longer the reviewer. |
| Silent abstention | A relevant area was not assessed and the review did not say so. |
| Blind repair | An issue was applied without checking it was present in the artifact. |
| Blanket discharge | "Addressed all concerns", against a list of identified issues. |
| Bundled repair | Three fixes and a refactor in one change; no issue is separately checkable. |
| Self-resolved issue | The repairer recorded its own fix as resolved and passed. |

## Related

- Roles: [Critic](../../roles/critic.md) is the role built on this skill; any role may use it.
- [`independent-validation`](../independent-validation/SKILL.md) is what happens next: your
  identifiers become its checklist.
- [Independence](../../docs/concepts/independence.md) — why you may not be the author, and
  why concurrent reviews of one artifact stay separately attributable.
- [`checkable-findings`](../checkable-findings/SKILL.md) — the producer-side contract your
  locators and evidence rely on.
