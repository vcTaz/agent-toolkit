# Debugging workflow — competing hypotheses

Find a root cause you can prove, by making several explanations compete instead of accepting
the first plausible one.

## Use this when

- The cause is genuinely unclear and the symptom has more than one plausible explanation.
- A previous fix did not work, which usually means the diagnosis was wrong.
- The bug is intermittent, environment-dependent, or spans components.
- Getting the diagnosis wrong is expensive — a confident wrong root cause produces a fix that
  changes nothing and closes the investigation.

## Do not use this when

- The stack trace names the line. Read it and fix it.
- One person already knows. Ask them.
- The symptom is not reproducible **and cannot be made so**. Establish reproduction first;
  everything below depends on it.

## The problem this solves

A single investigator finds one explanation that accounts for the symptom and stops looking.
That explanation is usually *sufficient* — it would produce the symptom — without being
*true*. Sequential investigation makes this worse: each new theory is framed by the first.

The correction is structural, not motivational. Generate competing hypotheses **in parallel,
in separate contexts**, and have each investigator try to **disprove the others** rather than
defend its own.

## Shape

```text
              reproduce                      MANDATORY GATE
                  │
     ┌────────────┼────────────┐
     ▼            ▼            ▼
 Explorer     Explorer     Specialist        independent, separate contexts
 hypothesis A hypothesis B hypothesis C
     │            │            │
     └────────────┼────────────┘
                  ▼
          cross-falsification               each attacks the others
                  ▼
               Critic                        attacks the survivor
                  ▼
             Validator                       prove it: change cause, change symptom
                  ▼
            Implementer                      fix the proven cause
                  ▼
             Validator                       the fix works and nothing else broke
```

## Stages

### 0 · Reproduce — a gate, not a stage

**Do not proceed without a reliable reproduction.** Record the exact conditions, the exact
symptom, and how often it occurs.

Without this you cannot falsify anything, and you cannot prove the fix worked — "it stopped
happening" is indistinguishable from "it happens less often than we looked".

If you cannot reproduce it, that is the investigation. Make reproduction the objective.

### 1 · Generate competing hypotheses — parallel, independent

Three to five. Each investigator gets:

- the symptom and the reproduction
- a **region or layer to own**
- **no other investigator's theory**

Each hypothesis is reported per [`checkable-findings`](../skills/checkable-findings/SKILL.md): the disproof condition is what would settle it, and
"this would explain the symptom" is `inferred` until something exercises it.

Each must produce not just a theory, but **what would disprove it** — stated before
investigating. A hypothesis with no disproof condition is not a hypothesis; it is a
preference, and it will survive every test.

→ hypothesis, mechanism, predicted evidence, **disproof condition**

### 2 · Cross-falsify — the mechanism that makes this work

Now let them see each other's theories. Each investigator's job is to **disprove the others**,
not to defend its own.

For each hypothesis, ask:

- What does this predict that we can check right now?
- What does it predict that we **do not** observe? That is disproof.
- Does it explain the **whole** symptom, including the timing, the frequency, the conditions
  under which it does not happen?
- Is it sufficient, or is it necessary? Many theories are sufficient; the cause is necessary.

A theory that survives deliberate attacks from agents with rival theories is worth
considerably more than one that survived its author's review.

→ surviving hypotheses, each with the attacks it withstood, and what killed the others

### 3 · Criticise the survivor — `Critic`, not its author

[`adversarial-review`](../skills/adversarial-review/SKILL.md) on the leading hypothesis.
Specifically: what does it assume? What would make it false that nobody has checked?

If two hypotheses survive, **do not pick one**. Carry both forward and design the check that
separates them.

### 4 · Prove it — `Validator`

A diagnosis is verified only by **intervention**:

```text
change the cause        → the symptom changes
revert the change       → the symptom returns
```

Both halves. One direction is correlation.

Everything short of this is a story that fits the evidence:

| Not proof | Proof |
|---|---|
| The theory explains the symptom | Changing the cause changes the symptom |
| The logs are consistent with it | Reverting restores the symptom |
| A fix made it stop | The fix targets the proven mechanism |
| Three agents agree | The prediction was checked and held |

See [`evidence-verification`](../skills/evidence-verification/SKILL.md).

### 5 · Fix — `Implementer`

Fix the **proven cause**, not the symptom. Add a test that fails on the unfixed code — confirm
it does; an assertion that passes against broken code proves nothing.

### 6 · Verify the fix — `Validator`, not the Implementer

Uses [`independent-validation`](../skills/independent-validation/SKILL.md). The reproduction
no longer reproduces, the new test fails without the fix, and nothing else broke.

## Independence requirements

```text
investigators                 independent of each other AND in separate contexts
Critic ≠ the hypothesis's author
Validator ≠ the Implementer
```

Separate contexts matter more here than anywhere else in this toolkit. A shared context means
a shared prior, and a shared prior is exactly the thing competing hypotheses exist to break.

## Termination

| Terminal state | When |
|---|---|
| `COMPLETED` | Root cause proven by intervention, fix implemented, fix independently verified. |
| `EXHAUSTED` | Hypotheses eliminated without a survivor, or the survivor cannot be proven. **Report what was eliminated and what would settle the remainder** — that is real progress and the next investigation starts from it. |
| `FAILED` | Cannot reproduce, or cannot instrument the system enough to test anything. |

`CANCELLED` is the fourth terminal state. This workflow cannot reach it by working, because it is imposed from outside the run, but any run may end in it — see [terminal states](README.md).

**A hypothesis that cannot be disproven has not been confirmed.** If the leading theory
survives only because nothing can test it, say so — do not fix on the strength of it. A fix
applied to an unproven cause is indistinguishable from a fix that did nothing, until the bug
returns.

Set the hypothesis limit up front. Generating theories is cheap and unbounded; testing them
is not.

## Scaling it down

| Situation | Minimum |
|---|---|
| Two plausible causes | Two investigators, one round of cross-falsification, then prove by intervention. |
| One agent available | Write down **three** hypotheses with disproof conditions *before* investigating any, then test each in turn. The structure does most of the work even without parallelism. A fresh context used to attack the survivor is a degraded self-check. |
| Obvious cause | Skip to intervention: change it, confirm the symptom changes, revert, confirm it returns. |

A fresh context of the same identity is a **disclosed degraded self-check**, not independent review: it may be run and must be labelled as what it is, and it satisfies no criterion that requires independence. Where completion requires independent review and no independent identity exists, the honest terminal state is `EXHAUSTED` — see [independence](../docs/concepts/independence.md).

Never drop: **reproduction**, **a stated disproof condition per hypothesis**, and
**intervention as proof**. Those three are the workflow.

## Common failure modes

| Failure | What it looks like |
|---|---|
| First plausible cause wins | It would produce the symptom, so it was taken as the cause. |
| No reproduction | The fix "seems to have worked" and nobody can tell. |
| Correlation as proof | The fix was applied and the symptom stopped. Nothing was reverted to check. |
| Unfalsifiable theory | "It's a race condition somewhere." Nothing can disprove it. |
| Shared context convergence | Investigators saw each other's theories early and merged into one. |
| Partial explanation | The theory covers the symptom but not the timing, and the gap was never asked about. |
| Symptom fix | The error stopped appearing because it is now caught and discarded. |
| Premature fix | Implementation began while two hypotheses were still live. |
