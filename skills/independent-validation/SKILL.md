---
name: independent-validation
description: Independently determine whether a claim actually holds by checking evidence yourself rather than re-reading the author's reasoning. Use when confirming a result, verifying a fix works, checking whether review issues were resolved, establishing whether a finding can be relied on, or settling a disagreement with evidence. Produces a PASS/FAIL/INCONCLUSIVE verdict that external checks can only lower.
---

# Independent validation

Determine whether a claim **holds**.

This is not re-reading someone's reasoning and agreeing with it. It is going to the evidence
yourself and deciding whether that evidence entails the claim *as stated*. If a check can
settle it, run the check.

## The distinction that defines this skill

| | |
|---|---|
| **Review** | Is this sound? Did anyone find a defect? — judgement |
| **Validation** | Does this hold? What does the evidence establish? — **checking** |

An agent that reads the author's argument and finds it convincing has reviewed it. Validation
requires going to the thing itself.

## Before you start

1. **Is the claim precise enough to be true or false?** "The performance is acceptable"
   cannot be validated. Ask for a claim you could disprove.
2. **Am I independent?** You must be **neither the author nor the critic**. Generate,
   criticise and validate are three distinct identities. If fewer than three exist, say so
   and record the gap — do not validate anyway.
3. **What would settle this?** Decide the check *before* you look at the evidence, so you are
   not reverse-engineering a justification for what you find.

## The procedure

### 1. Restate the claim precisely

Write down exactly what is being asserted, including its scope and its qualifiers. Most
validation failures happen here: the evidence supports a weaker claim than the one asserted,
and nobody noticed because nobody wrote the claim down.

> Asserted: "the retry logic handles transient failures"
> Actually testable: "on a 503, `send()` retries up to 3 times with backoff, then raises"

### 2. Identify what would settle it

- A test that fails without the change and passes with it
- A command whose output entails the claim
- A measurement of the same workload before and after
- A specification or guarantee that covers this exact case

**If nothing would settle it, stop here and answer `INCONCLUSIVE`.** This is the single most
important step. An unverifiable claim that has been "validated" is more dangerous than one
honestly labelled as judgement, because everything downstream will rely on it.

### 3. Run the check yourself

Do not accept a report of a check. Run it, and record what it actually returned.

Then apply the four-part test — all four must hold:

1. **A check ran.**
2. **It succeeded.**
3. **Its inputs were this claim's own subject.** A passing test over different data proves
   nothing about this claim. This is the step most often skipped.
4. **Its output entails the claim as stated** — not a weaker neighbour.

> The green suite ran. It passed. But it never exercised the changed path. Three out of four
> is not validation.

### 4. Resolve blocking issues by identifier

You were given the Critic's blocking issues, each with an identifier. For each one:

- Determine whether it is **actually resolved**, not whether someone said it was.
- **Name its exact identifier** in your output. An identifier you were not given resolves
  nothing and will be discarded.
- An unresolved blocking issue means `FAIL`, regardless of how good the rest is.

### 5. Check the dependencies still stand

A claim resting on another claim is only as good as that one. If anything it depends on has
been withdrawn, the claim is unsupported now — whatever it was when it was written.

### 6. Say what the evidence does and does not establish

If the evidence supports something weaker than the claim, say which weaker thing. That is
often the most useful output of the whole exercise: not "false", but "true of the cases we
measured, and unestablished beyond them".

## Verdict

| Decision | Use when |
|---|---|
| `PASS` | You checked it against evidence and the evidence entails the claim as stated. |
| `FAIL` | The evidence contradicts the claim, or a blocking issue stands unresolved. |
| `INCONCLUSIVE` | No check exists, evidence is unavailable, or the claim is too vague to test. |

### Your PASS can only be lowered, never raised

| you say | external check says | recorded |
|---|---|---|
| anything | `FAIL` | `FAIL` |
| `FAIL` | anything | `FAIL` |
| `PASS` | `PASS`, all blocking issues resolved, dependencies standing | `PASS` |
| anything else | | `INCONCLUSIVE` |

There is no combination in which confidence upgrades a failed or inconclusive check.
`INCONCLUSIVE` never promotes anything.

## Output shape

```text
DECISION: PASS | FAIL | INCONCLUSIVE

CLAIM AS TESTED
  <the precise restatement you validated>

CHECKS RUN
  $ <command>
  <what it actually returned>

BLOCKING ISSUES RESOLVED
  ISSUE-1  resolved — <how you determined it>
  ISSUE-2  NOT resolved — <what still stands>

WHAT THE EVIDENCE ESTABLISHES
  <and, explicitly, what it does not>

SUMMARY
```

## What you may not do

- **Change the artifact.** If validation reveals a defect, report it.
- **Pass on agreement.** "This looks right" and "another model concurred" are not checks.
- **Resolve an issue you were not given.**
- **Mark your own opinion as verified evidence.**
- **Produce claims of your own**, or create work.

## Common failure modes

| Failure | What it looks like |
|---|---|
| Reading, not checking | You followed the reasoning, found it sound, and passed. Nothing was run. |
| Wrong subject | The check passed, over inputs unrelated to the claim. |
| Weaker neighbour | Evidence supports "works for ASCII"; claim says "works for all input"; you passed it. |
| Accepting a report | "The author says the tests pass." Run them. |
| Invented resolution | You named an issue identifier nobody issued. |
| Validating the unverifiable | The claim had no possible check and you passed it on plausibility. |
| Forgetting dependencies | The claim holds; the claim it rests on was withdrawn yesterday. |

## Related

- Roles: [Validator](../../roles/validator.md) is the role built on this skill.
- [`evidence-verification`](../evidence-verification/SKILL.md) — the deeper treatment of what
  evidence can establish and where the limits are.
- [`adversarial-review`](../adversarial-review/SKILL.md) — where your blocking issues came from.
- [Independence](../../docs/concepts/independence.md) · [Verification](../../docs/concepts/verification.md)
