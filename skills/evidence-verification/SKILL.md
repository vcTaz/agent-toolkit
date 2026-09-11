---
name: evidence-verification
description: Decide whether evidence actually entails a claim, and refuse to guess when no check exists. Use when deciding if something is proven or merely plausible, when agents agree and you need to know whether that means anything, when a tool ran and a claim is being drawn from it, when separating verified fact from reviewed judgement, or before relying on any conclusion. Enforces that model agreement is not evidence and that unknown claim kinds fail closed.
---

# Evidence verification

```text
model agreement != verification
```

Agents are fluent. Several agreeing is a signal about plausibility and tells you nothing
about truth. A system that promotes claims on agreement produces confident, well-cited,
internally consistent answers that are wrong — and has no way to notice.

**A claim becomes trusted only when something outside the models is checked by an explicit
rule that can say what that evidence establishes.**

## The four-part test

Before treating any claim as established, all four must hold. Only the fourth is
verification; the first three are preconditions people mistake for it.

```text
1. a check ran
2. it succeeded
3. its INPUTS were this claim's own subject
4. its OUTPUT entails this claim AS STATED
```

Step 3 is the one that is skipped. A green test suite that never exercised the changed path
satisfies 1 and 2 and establishes nothing about the change.

> The original implementation of this rule admitted a tool result only when the recorded
> operands were the claim's own operands and the recorded output stated they matched. *A
> successful call over other numbers proves nothing* — and a recorded result that
> contradicted the claim made the whole verification fail rather than being quietly ignored.

### Worked examples

| Claim | Not verification | Verification |
|---|---|---|
| "the fix works" | the suite passed | *this* test, which fails on unfixed code, now passes |
| "it handles empty input" | there is a test file | a test whose input is empty, asserting the claimed behaviour |
| "no regression" | CI is green | CI is green **and** covered the changed paths |
| "it's faster" | it feels faster | same workload, measured before and after |
| "the root cause is X" | the theory explains the symptom | changing X changes the symptom; reverting restores it |
| "this is thread-safe" | it looks synchronised | the race detector runs the concurrent path and reports nothing |

## Verifier kinds, and failing closed

Different claims need different checks. Name, for each claim or acceptance criterion, the
**kind of check that would settle it**.

```text
claim ──has──▶ verifier kind ──resolves to──▶ a check you can actually run
                     │
            no check for this kind
                     ▼
              INCONCLUSIVE
```

**A kind with no available check is `INCONCLUSIVE`, never guessed.**

This is the fail-closed rule and it is the most important property here. A verifier that
returns "probably fine" for claims it does not understand is worse than no verifier, because
it manufactures confidence exactly where confidence is least warranted.

Three consequences:

- **Every criterion must pass; any failure fails the whole.** Partial verification is not
  verification.
- **An unsupported claim *form* is inconclusive too.** A check that understands exact
  equality does not understand "roughly the same" just because both concern numbers.
- **Extending to a new domain means writing a check that can say what that domain's evidence
  establishes** — never relaxing the checks you have.

## Verified is not the same as reviewed

Most claims worth making **cannot** be mechanically verified. "This architecture is
maintainable" has no verifier. Neither does "users will find this confusing" or "this is the
idiomatic approach".

Keep the two grades visibly apart:

| | **Verified** | **Reviewed** |
|---|---|---|
| Basis | external evidence entails the claim | independent judgement found no defect |
| Strength | may be relied on | may be acted on, and may be wrong |
| Correct use | load-bearing conclusions, acceptance criteria | direction, prioritisation, design opinion |

A result may rest on both. What it must never do is present the second as the first. Labelling
a judgement as judgement is not a weakness in the output — it is the part that makes the rest
of it trustworthy.

## Evidence is recorded, not asserted

An agent may propose evidence. It may never mark its own evidence verified.

- The arguments a tool was invoked with are what was recorded, not what the agent says
  afterwards it ran.
- The output is the output, not the agent's summary of the output.
- A claim citing a result nothing recorded is refused, not trusted.

An agent that can write `verified: true` about its own work has not been checked; it has been
asked how it feels.

## Ask before you start, not after

If a required criterion depends on a check that does not exist, the work will proceed, be
done properly, establish nothing, and terminate having wasted everything it spent. It will be
*correct* to do so.

So, at the start: **for each acceptance criterion, what evidence would settle it?**

If a required criterion has no answer, resolve it now — restate the criterion in checkable
terms, or agree openly that its conclusion will be reviewed judgement rather than verified
fact. This is a five-minute conversation instead of a wasted run and a misleading report.

> The original implementation refused such a configuration *before the run existed*, rather
> than starting it and quietly exhausting.

## Invalidation propagates

Verification is not permanent. A test is deleted, a dependency changes, a supporting claim is
withdrawn.

When support stops standing, **everything that depended on it loses its status, transitively.**
A conclusion built on a withdrawn claim is not "still probably right"; it is unsupported until
re-established. Anything already sent to another branch on its strength must be retracted, not
left in place.

## Checklist

- [ ] Is there evidence outside the models, or only agreement between them?
- [ ] Were the evidence's inputs this claim's own subject?
- [ ] Does the output entail this claim *as stated*, not a weaker neighbour?
- [ ] Was the evidence recorded by something other than the agent asserting it?
- [ ] If no check exists for this kind of claim, is it labelled **reviewed** rather than verified?
- [ ] Does everything this claim depends on still stand?

## Common failure modes

| Failure | What it looks like |
|---|---|
| Agreement as proof | Three agents concurred, so it went in as established. |
| Exit code as proof | The command returned 0, so the claim is true. |
| Wrong subject | A real check, over inputs that were not this claim's. |
| Scope inflation | Evidence for one case; claim covers all cases. |
| Self-certification | The agent that made the claim also marked it verified. |
| Guessing on unknowns | No check existed, so it was passed on plausibility. |
| Stale support | Verified last week; what it rested on was withdrawn since. |
| Grade flattening | Judgement and measurement presented in the same confident voice. |

## Related

- [`independent-validation`](../independent-validation/SKILL.md) — the review procedure that
  applies this.
- [`evidence-backed-synthesis`](../evidence-backed-synthesis/SKILL.md) — carrying these grades
  into an answer.
- [Verification](../../docs/concepts/verification.md) · [Independence](../../docs/concepts/independence.md)
