# Architecture workflow

Produce a design that has been attacked and checked for feasibility before anyone builds on
it.

## Why there is no "Architect" role

Designing is a `Specialist` brief, not a distinct role. It has the same epistemic posture as
any other production role — it proposes, and something else checks — the same output contract,
and the same independence requirement. What makes architecture work reliable is not a special
kind of agent; it is that the design gets criticised and checked for feasibility **before**
it becomes expensive to change.

A design is an artifact like any other. The workflow is what differs.

See [roles/README.md](../roles/README.md) on the admission bar for a new role.

## Use this when

- A decision will be expensive to reverse: a data model, a public interface, a boundary
  between components, a technology commitment.
- Several approaches are viable and the trade-offs are not obvious.
- Parallel work is about to begin and needs a settled interface to work against.

## Do not use this when

- The decision is cheap to reverse. Make it, and change it when you learn more.
- Only one approach is actually viable. Write down why and move on.
- The constraints are unknown. Explore first — a design against unknown constraints is a
  guess with a diagram.

## Shape

```text
          Explorer                  what exists, what constrains us
              │
              ▼
      Specialist (design)           two or more real options, one recommendation
              │
              ▼
           Critic                   attack the recommended design
              │
              ▼
      Validator (feasibility)       does it actually work here?
              │
       ┌──────┴──────┐
       ▼             ▼
   revise design   Final Reviewer   meets the requirement?
       │                 │
       └─────────────────┘
                    approved design
```

## Stages

### 1 · Explore — `Explorer`

What exists, what it assumes, what constrains the change. Existing interfaces, data shapes,
deployment reality, team conventions, prior attempts.

**A design produced without this stage is a design for a system that does not exist.** This is
the most commonly skipped stage and the most commonly regretted.

→ current structure, constraints, invariants that must hold, prior attempts and why they
failed

### 2 · Design — `Specialist`, with a design brief

Produce **at least two real options**. One option is not a design; it is the first idea with
a diagram.

For each option:

- how it works, concretely enough to be criticised
- what it makes easy, and what it makes hard
- what it commits you to, and how expensive reversing it is
- how it fails, and what happens then
- what it assumes

Then a **recommendation with reasons**. A comparison with no recommendation pushes the
decision onto whoever reads it, with less context than the designer had.

Where a decision turns on how a specific technology actually behaves, that is a `Specialist`
question and should be answered with a citation or a measurement, not an expectation.

→ options, trade-offs, a recommendation, stated assumptions

### 3 · Criticise — `Critic`, not the designer

[`adversarial-review`](../skills/adversarial-review/SKILL.md) on the recommendation.

For designs specifically:

- Which assumption is **load-bearing** and unexamined?
- What happens at the edges — empty, huge, concurrent, partially failed, migrated?
- What does this make **hard later** that is easy now?
- Does it actually satisfy the constraints from stage 1, or does it satisfy a simplified
  version of them?
- Was the rejected option rejected for a reason, or for unfamiliarity?

Give the Critic the design and the constraints. **Do not give it the designer's advocacy.**

→ `PASS` / `CHALLENGE` / `INCONCLUSIVE`, issues identified

### 4 · Check feasibility — `Validator`

Designs fail in reality for reasons that look fine on paper. Where the design rests on a
claim about how something behaves, **check it**:

- Does the library actually support that, at the version in use?
- Does the data have the shape the design assumes? Look at it.
- Does the approach hold at the real volume, not the illustrative one?
- Is the migration path real, or does it assume a state nothing will reach?

The cheapest possible check counts: reading the actual source, running a ten-line spike,
querying the real data. **A design validated only by agreement has not been validated.** The
most common architectural failure is a coherent design resting on one wrong assumption about
an external system.

Label each design assumption **verified** or **reviewed** — see
[`evidence-verification`](../skills/evidence-verification/SKILL.md). A design whose
load-bearing assumptions are all "reviewed" is a hypothesis, and should be described as one.

→ which assumptions were checked and how; which could not be

### 5 · Revise or approve

`CHALLENGE` or `FAIL` returns to stage 2 with issues identified. Bound the rounds and say so
up front.

### 6 · Final review — `Final Reviewer`, independent of the designer

Does the design meet the **original requirement** — not the requirement as the design
reframed it? Are the unresolved issues acceptable? Are the limitations stated?

## What an approved design must carry

The output others build against:

```text
DECISION            what was chosen
ALTERNATIVES        what was rejected, and why — the most valuable part in six months
ASSUMPTIONS         each marked verified or reviewed
INTERFACES          precise enough to build against in parallel without further discussion
CONSTRAINTS         invariants that must hold; what implementers may not change
KNOWN LIMITATIONS   what this makes hard, and what remains unresolved
REVERSAL COST       what it takes to undo this
```

The interfaces section is the operational test: **if two agents could build against it in
parallel without talking to each other, it is precise enough.** If they would have to agree
on a type, a name or an error case first, it is not.

## Independence requirements

```text
Critic ≠ the designer
Validator ≠ the designer, ≠ the Critic
Final Reviewer ≠ the designer
```

Designers defend designs. That is not a character flaw; it is what having reasons feels like
from the inside, and it is why the check must come from elsewhere.

## Termination

| Terminal state | When |
|---|---|
| `COMPLETED` | An approved design with verified load-bearing assumptions and stated limitations. |
| `EXHAUSTED` | No option survives criticism and feasibility, or the trade-off is a genuine judgement call. **Report the options, what killed each, and what the remaining decision turns on** — that is a decision for a person, and handing it over cleanly is success, not failure. |
| `FAILED` | The constraints are contradictory, or the requirement is incoherent. Say which constraints conflict. |

`CANCELLED` is the fourth terminal state. This workflow cannot reach it by working, because it is imposed from outside the run, but any run may end in it — see [terminal states](README.md).

Escalating a genuine judgement call is the correct outcome, not a failure of the workflow.
What must not happen is a design chosen by whichever agent argued last.

## Scaling it down

| Situation | Minimum |
|---|---|
| One reversible decision | Write the decision, the alternative, and the assumption it rests on. Three sentences. Check the assumption. |
| Moderate stakes | Design → Critic → check the load-bearing assumption. Skip separate final review. |
| One agent available | Write two options and their trade-offs, then **start a fresh context** to attack the recommendation. Say the review was not independent. |

Never drop: **at least two options**, **an explicit list of assumptions**, and **checking the
load-bearing one**. A design with one option and unexamined assumptions is a preference.

## Common failure modes

| Failure | What it looks like |
|---|---|
| One option | The first idea, with a diagram and a rationale written afterwards. |
| Designing without exploring | An elegant design for a system that does not exist. |
| Unchecked assumption | Coherent design; the library does not do that at the version in use. |
| Agreement as validation | Three agents liked it. Nothing was checked. |
| Vague interfaces | "Returns the user data." Two implementers will build two shapes. |
| Lost alternatives | Six months later nobody knows why the obvious approach was rejected. |
| Designer as reviewer | The designer explained the objections away from the same context that produced them. |
| Requirement drift | The design meets the requirement it reframed, not the one that was asked. |
