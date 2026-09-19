# Workflows

How [roles](../roles/) and [skills](../skills/) cooperate to reach an objective larger than
any one of them.

These are **descriptions of a process, not programs**. Nothing executes them. A person or a
lead agent follows them, adapts them, and scales them down — every file below has a section
telling you how.

## The four

| Workflow | Objective | Parallel where |
|---|---|---|
| [software-engineering](software-engineering.md) | Build or change something, and be able to defend that it works | exploration; implementation on **disjoint files** |
| [research](research.md) | Answer an open question, honestly bounded | investigation on disjoint regions |
| [debugging](debugging.md) | Find a root cause you can prove | competing hypotheses in separate contexts |
| [architecture](architecture.md) | Settle an expensive decision before building on it | rarely — design is mostly sequential |

## What they have in common

Every one of them:

1. **Produces, then attacks, then checks.** Never produce-and-accept.
2. **Uses different identities for producing and checking.** See
   [independence](../docs/concepts/independence.md).
3. **Has a stated unsuccessful outcome.** A workflow that can only succeed will report
   success on everything.
4. **Bounds its loops up front.** Repair rounds, investigation rounds, hypothesis counts —
   stated before starting, not invented at the end.
5. **Says what it did not settle.**

## Four terminal states, not two

```text
reached by the run's own execution and evaluation
COMPLETED    reviewed, checked, and it holds
EXHAUSTED    the work happened and the evidence or the limits did not suffice
FAILED       it could not proceed at all

imposed from outside the run
CANCELLED    stopped by something other than the run's own evaluation
```

A workflow normally produces one of the first three itself: they are the states its own
execution and evaluation can reach. `CANCELLED` is not one a workflow arrives at by working
— it is imposed from outside — but any workflow may terminate in it at any point, so a
process that models only the first three has no way to record being stopped. The definitions
are **O22** in [orchestration](../docs/concepts/orchestration.md), which is authoritative for
all four.

**`EXHAUSTED` is the outcome most processes lack**, and its absence is why they produce
plausible answers to questions they could not settle. It is not failure: it carries the
partial result, the unresolved gaps, and what would close them. Treat producing it well as a
success of the workflow.

## Parallelism

Parallelism costs coordination and tokens. It pays only when work is **genuinely
independent**.

| Genuinely parallel | Never parallel |
|---|---|
| Investigation of disjoint regions | Two agents writing the same file |
| Implementation of disjoint files | Producing and checking the same artifact |
| Competing hypotheses in separate contexts | Anything whose output changes another's input |
| Independent modules behind a settled interface | Work with unsettled interfaces |

Before parallelising two branches, ask: **could one's output change what the other should
do?** If yes they are sequential, or they need an explicit hand-off.

In [research](research.md) and [debugging](debugging.md), parallelism is not primarily about
speed. It exists to prevent **anchoring** — sequential investigation frames everything after
the first theory. That is why those workflows also forbid cross-talk until reports are in.

## Choosing one

```text
Is the cause of a known symptom unclear?          → debugging
Is an expensive, hard-to-reverse decision open?   → architecture
Is the question open, with no known answer?       → research
Is something to be built or changed?              → software-engineering
```

They compose. Software engineering commonly contains an architecture phase; debugging
commonly ends in a software-engineering fix.

## Scaling down

Every workflow here has a **Scaling it down** section, and it is not an afterthought — most
real tasks should use a reduced form. Running a six-stage workflow on a small change costs
more than the change.

The stage never to drop: **independent checking by an identity that did not produce the
work.** Everything else is optimisation.

## Adding a workflow

The bar: a genuinely different **shape** of cooperation, not a different subject. "Security
review" is the software-engineering workflow with a security brief on the Critic. "Data
migration" is architecture plus software engineering.

A workflow that adds a role without giving it something the other roles cannot do is theatre.
Every role in every workflow here must be removable only at a stated cost.
