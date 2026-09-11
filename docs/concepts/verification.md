# Verification

```text
model agreement != verification
```

This is the epistemic boundary, and it is the most distinctive idea in this toolkit. Agents
are fluent. Several of them agreeing is a useful signal about *plausibility* and tells you
nothing about *truth*. If a system promotes claims on agreement, it will produce confident,
well-cited, internally consistent answers that are wrong, and it will have no way to notice.

The rule:

> A claim becomes trusted only when something outside the models — a tool result, a test
> run, a compiler, a measurement — is checked by an explicit policy that can say what that
> evidence establishes.

Review decides whether a claim *looks* sound. Verification decides whether it *holds*. They
are different operations with different authorities, and conflating them is what makes a
multi-agent system feel rigorous while being no more reliable than one model.

## A successful tool call is not a verified claim

This is the mistake almost every implementation makes. An agent runs a command, the command
exits zero, the agent asserts its claim, and the claim is recorded as evidence-backed.

Four separate things must line up, and only the last one is verification:

1. A tool ran.
2. It succeeded.
3. Its **inputs were the claim's own subject**.
4. Its **output entails the claim as stated**.

> The original implementation checked exactly this. Its arithmetic policy admitted a tool
> result only when the recorded operands were the claim's own operands and the recorded
> output stated that the computed total matched the asserted one. *A successful call over
> other numbers proves nothing*, and a call that contradicted the claim made the whole
> verification fail rather than being ignored.

Translated to ordinary engineering work, the same four steps are:

| Claim | Not verification | Verification |
|---|---|---|
| "the fix works" | the test suite passed | *this* test, which fails on the unfixed code, now passes |
| "it handles empty input" | there is a test file | a test whose input is empty and whose assertion is the claimed behaviour |
| "no regression" | CI is green | CI is green *and* covered the changed paths |
| "it's faster" | it felt faster | a measurement of the same workload before and after |

The question is never "did something succeed?" It is **"does this artifact entail this
exact claim?"**

## Evidence is recorded by the host, never asserted by the model

An agent may *propose* evidence. It may never mark its own evidence verified. Concretely:

- The arguments a tool was actually invoked with are recorded by whatever ran it, not
  restated by the agent afterwards.
- The output is the output, not the agent's summary of the output.
- A claim citing a result that was never recorded is refused rather than trusted.

An agent that can write "verified: true" about its own work has not been checked. It has
been asked how it feels.

## Not everything can be verified, and pretending otherwise is the failure

The honest part of this design is that most claims **cannot** be mechanically verified.
"This architecture is maintainable" has no verifier. Neither does "the user will find this
confusing", "this is the idiomatic approach", or "the root cause is X" before X is
reproduced.

So the toolkit distinguishes two grades, and keeps them visibly apart:

| | **Verified** | **Reviewed** |
|---|---|---|
| Basis | external evidence entails the claim | independent judgement found no defect |
| Strength | may be relied on | may be acted on, and may be wrong |
| Correct use | load-bearing conclusions, acceptance criteria | direction, prioritisation, design opinion |

A result may rest on both. What it may not do is present the second as the first.

## Verifier kinds, and failing closed

Different claims need different checks. Attach to each acceptance criterion a **verifier
kind** naming the check that would settle it, and register a policy per kind.

```text
criterion  ──has──▶  verifier kind  ──resolves to──▶  policy  ──reads──▶  recorded evidence
                                         │
                              no policy registered
                                         ▼
                                  INCONCLUSIVE
```

**A kind with no registered policy is `INCONCLUSIVE`, never guessed.** This is the
fail-closed rule, and it is the single most important property of the whole mechanism. A
verifier that returns "probably fine" for claims it does not understand is worse than no
verifier, because it manufactures confidence exactly where confidence is least warranted.

Three consequences worth stating explicitly:

- **Every criterion must pass; any failure fails the whole.** Partial verification is not
  verification.
- **An unsupported claim *form* is inconclusive too.** A policy that understands integer
  sums does not understand "roughly the same" just because both mention numbers.
- **Extending the system to a new domain means writing a policy that can say what that
  domain's evidence establishes** — not relaxing the ones you have.

## Refuse before you start, rather than exhausting usefully

If a run's required criteria depend on a verifier kind nothing can supply, the run will
proceed, do real work, fail to promote anything, and terminate having achieved nothing. It
will be *correct* to do so, and it will have wasted everything it spent.

> The original implementation refused such a configuration before a run record existed,
> "rather than started and quietly exhausted."

The portable form of this rule: **before starting, ask what evidence would settle each
acceptance criterion. If a required criterion has no answer, say so now.** Either the
criterion needs restating in checkable terms, or the objective needs to be honest that its
conclusion will be reviewed judgement rather than verified fact.

This is a five-minute conversation at the start instead of a wasted run and a misleading
report at the end.

## Invalidation propagates

Verification is not permanent. Evidence can stop standing — a test is deleted, a dependency
changes, a claim it rested on is withdrawn.

When support stops standing, **everything that depended on it loses its status too**, and
transitively. A conclusion built on a withdrawn claim is not "still probably right"; it is
unsupported until re-established. Anything already delivered to another branch on the
strength of it must be retracted, not left in place — see
[`orchestration.md`](orchestration.md).

## Checklist

Before treating any claim as established:

- [ ] Is there evidence outside the models, or only agreement between them?
- [ ] Were the evidence's inputs this claim's own subject?
- [ ] Does the output entail this claim *as stated*, not a weaker neighbour?
- [ ] Was the evidence recorded by something other than the agent asserting it?
- [ ] If no check exists for this kind of claim, is it labelled reviewed rather than verified?
- [ ] Does everything this claim depends on still stand?
