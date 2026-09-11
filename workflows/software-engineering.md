# Software engineering workflow

Build or change something, and be able to defend the claim that it works.

## Use this when

- A change is non-trivial: it touches code whose invariants are not fully understood, or
  getting it wrong is expensive.
- The result will be relied on by people who did not watch it being made.
- Several parts can be built independently.

## Do not use this when

- The change is small and obvious. One agent writing a fix and running the tests is the right
  shape; this workflow's overhead would exceed its value.
- The requirement is not yet clear. Settle that first — implementing an unclear requirement
  produces a diff whose intent nobody can reconstruct.
- The design is unsettled. Use [architecture](architecture.md) first.

## Shape

```text
          Explorer(s)                      map the territory
               │                           parallel, one region each
               ▼
        [ design settled ]                 architecture workflow, if needed
               │
               ▼
         Implementer(s)                    make the change
               │                           parallel ONLY on disjoint files
               ▼
            Critic                         attack it
               │
               ▼
           Validator                       check it holds
               │
        ┌──────┴──────┐
        │             │
   issues stand   issues resolved
        │             │
        ▼             ▼
   Implementer   Final Reviewer            judge the whole
    (repair)           │
        │       ┌──────┼──────┐
        └───────┤      │      │
             REVISE  PASS  REJECT
```

## Stages

### 1 · Explore — `Explorer`, parallel

**Skip when the territory is already understood.** Otherwise: what exists, what the
invariants are, what will be affected.

Parallel Explorers must own **disjoint regions** and must not see each other's conclusions
until their reports are in. Explorers who talk mid-run converge, and convergence looks like
corroboration while being anchoring.

→ findings with locators, open questions, failed approaches

### 2 · Implement — `Implementer`, parallel only on disjoint files

One requirement, one owner, an explicit file list. **Parallel Implementers must own disjoint
files** — this is not advice. Two agents "both working on auth" will collide; one owning
`auth/session.py` and another owning `auth/tokens.py` will not.

The Implementer runs the project's checks and reports what they printed. That is evidence,
not review.

→ the change, the checks it ran and their output, what it did not do

### 3 · Criticise — `Critic`, not the Implementer

[`adversarial-review`](../skills/adversarial-review/SKILL.md) over the diff and the
requirement. Blocking issues get stable identifiers.

Give it the diff and the requirement. **Do not give it the Implementer's justification** —
see [`bounded-context-handoff`](../skills/bounded-context-handoff/SKILL.md).

→ `PASS` / `CHALLENGE` / `INCONCLUSIVE`, with identified issues

### 4 · Validate — `Validator`, neither the Implementer nor the Critic

[`independent-validation`](../skills/independent-validation/SKILL.md). Runs the checks
itself. Resolves the Critic's issues **by identifier**.

The step everyone skips: confirm a new test **fails without the change**. An assertion that
passes against broken code is decoration.

→ `PASS` / `FAIL` / `INCONCLUSIVE`, issues resolved by identifier, what it ran

### 5 · Repair — `Implementer` or `Specialist`, bounded

Only on a `CHALLENGE` or `FAIL`. Address issues **by identifier**; do not reopen the design.

Bound the rounds — two or three — and record the reason when you stop. A repair loop with no
limit terminates only when the budget does. A failed attempt usually failed for a domain
reason, which makes a `Specialist` often the better repairer.

→ back to stage 3, with a round counter

### 6 · Final review — `Final Reviewer`, independent of every producer

[`final-verification`](../skills/final-verification/SKILL.md) against the original
requirements, the unresolved findings, and the evidence.

→ `PASS` / `REVISE` (evidence or presentation) / `REJECT`

## Parallelism

| Genuinely parallel | Never parallel |
|---|---|
| Explorers on disjoint regions | Implementers on overlapping files |
| Implementers on disjoint files | Implement and criticise the same change |
| Independent modules with settled interfaces | Anything whose output changes another's input |

Before parallelising two branches ask: **could one's output change what the other should do?**
If yes, they are sequential — or they need an explicit hand-off.

## Independence requirements

```text
Implementer ≠ Critic ≠ Validator                      three identities
Final Reviewer ≠ every producer of a candidate
```

Decide this **before dispatching**, not after. If you cannot fill a review independently,
record the gap — do not fall back to self-review.

## Termination

| Outcome | When |
|---|---|
| **Complete** | Final Reviewer `PASS`, re-checked against current state, every required criterion met by support that still stands. |
| **Exhausted** | Repair rounds spent, or a `REVISE` that locates nothing the record confirms. **The work happened and did not converge** — report the partial result, the unresolved issues and what is missing. |
| **Failed** | It could not proceed at all: the requirement was incoherent, the environment unusable, the dependency absent. |

**Exhausted is not failed, and neither is a success.** A workflow that cannot produce
"exhausted" will report success on everything.

Say up front how many repair rounds are allowed. A limit invented at the end is a
rationalisation.

## Scaling it down

The full shape is for changes that warrant it. Smaller versions that keep the load-bearing
property:

| Situation | Minimum |
|---|---|
| Small, clear change | Implementer → Validator. One independent check is most of the value. |
| Understood territory | Drop exploration. |
| Risky change, one agent available | Implement, then start a **fresh context** to review. Say in the output that review was not independent. |

The one stage to never drop is **independent checking by someone who did not write it**.
Everything else is optimisation.

## Common failure modes

| Failure | What it looks like |
|---|---|
| Green means done | The suite passed, over paths the change never touched. |
| Collision | Two Implementers in one file; the later write silently won. |
| Review leak | The Critic was handed the Implementer's reasoning and checked its coherence. |
| Test tuned to pass | The assertion was widened until it went green. |
| Unbounded repair | Round seven, and the limit was never stated. |
| Reviewer as author | The Critic fixed what it found, and the change lost its reviewer. |
| Theatrical roles | Five agents where two would do, because the diagram had five boxes. |
