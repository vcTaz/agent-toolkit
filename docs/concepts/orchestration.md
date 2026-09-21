# Orchestration principles

Rules that govern a run as a whole and belong to no single agent. None of these is a role.
Most are deterministic: they need a decision, not a model.

Each principle states what it is, why it exists, and what it looks like when you ignore it.
They are numbered for reference from roles, skills and workflows.

---

## Authority

### O1 · Agents propose, the orchestrator decides, the artifact commits

```text
agent / model      proposes
orchestrator       decides
artifact / repo    commits authoritative state
```

An agent returns a *draft*: a claim, a patch, a verdict, a suggestion. Nothing it returns is
authoritative until something outside it admits it. The orchestrator alone changes status,
assigns work, spends budget and accepts results.

**Ignore it and:** an agent's confidence becomes the system's state. "I've verified this" is
recorded as verification; "I think we're done" ends the run.

### O2 · An agent's output contract is a boundary, not a suggestion

Each role may emit only certain kinds of output. A Critic returns a verdict and issues — not
findings, not patches, not new work requests. A Synthesizer returns one candidate answer —
it cannot create the support it cites, and cannot extend the run.

Enforce this where you can (tool allowlists, read-only agents, structured output) and check
it where you cannot. An output field a role is not entitled to should be **dropped, not
merged**.

**Ignore it and:** a reviewer quietly becomes an author, and the artifact it was meant to
check now includes its own contribution.

### O3 · Agents do not author their own schedulable work

An agent may *request* more work. That request is an inert proposal until the orchestrator
admits it. New work comes from a small number of named, bounded factories — review,
reconsideration, follow-up, repair, synthesis, final review — each with an admissibility
check, a limit, and a recorded refusal reason.

**Ignore it and:** "I should investigate further" becomes an unbounded work queue, and the
run's cost is decided by the thing least able to see the budget.

### O4 · Prefer a deterministic decision to a model call

Routing, deduplication, ranking, eligibility, progress measurement and readiness are all
decidable without a model. Spend model calls on judgement that genuinely needs judgement.

A deterministic policy is also inspectable: you can ask *why* it chose what it chose and get
the same answer twice.

**Ignore it and:** you pay latency and tokens for a decision that is now also
non-reproducible.

### O29 · Escalation is sticky until discharged by evidence

When a run or a task triggers a stronger classification — more review, higher risk, an
authority level above routine execution — that requirement **stays in force until something
discharges it**. It does not lapse because the run is nearly done, because the budget is
tight, or because the trigger is no longer being talked about.

This is not an absolute ratchet. A classification may come down; it may not come down
quietly. Downgrading requires all three:

```text
1. an explicit ruling            recorded, by whoever holds the authority to make it
2. evidence the trigger is gone  the condition that raised it no longer applies, shown
3. preservation of what accrued  any independent-review obligation already made necessary
                                 by the escalation survives the downgrade
```

The third is the one that gets dropped. An escalation that required an independent review
does not un-require it by being reclassified afterwards — the reason for the review was the
state the work passed through, and the work still passed through it.

**Ignore it and:** every escalation decays at exactly the moment it becomes expensive, which
is the moment it was for.

---

## Work and ownership

### O5 · One artifact, one owner

Every file, module or document under change has exactly **one** agent permitted to write it
for the duration of that work. Split by ownership, not by topic — two agents "both working
on auth" will collide; one owning `auth/session.py` and another owning `auth/tokens.py` will
not.

**Ignore it and:** the last writer wins, silently, and the lost work is usually noticed
several steps later.

### O6 · Parallelise only genuinely independent work

Run agents concurrently when their work shares no state, no files and no ordering
requirement. Sequential work that has been parallelised produces conflicts and rework that
cost more than the time saved.

Ask of any two parallel branches: *could one's output change what the other should do?* If
yes, they are sequential — or they need the hand-off in **O11**.

**Ignore it and:** coordination overhead exceeds the parallelism gain, which is the usual
reason multi-agent runs are slower than one agent.

### O7 · Reject output computed against superseded state

When work is dispatched, pin what it relies on: the version of the artifact, the inputs, the
context it was given. When it returns, re-check those pins against current state. If
anything it relied on has moved, **reject the output rather than merging it.**

**Ignore it and:** a long-running agent's answer overwrites three newer changes, and the
result is a merge no one performed and no one reviewed.

### O8 · Budgets are authoritative, and completion is reserved

Track spend against a limit that lives with the run, and increment it *before* the work it
pays for. Hold back enough for one synthesis and one independent final review from the
start, and treat that reserve as unavailable to optional work.

**Ignore it and:** the run spends everything on exploration and reports an unreviewed answer,
or stops mid-review with nothing it can defend.

---

## Knowledge movement

### O9 · Propagate discoveries, never transcripts

What moves between agents is a **bounded, already-established insight** — not a conversation,
not a context dump, not another agent's reasoning. The original implementation capped an
insight at 800 characters and composed it on the host from an already-validated claim.

**Ignore it and:** every agent's context fills with other agents' deliberation, the signal
is buried, and cost scales quadratically with team size.

### O10 · Targeted delivery, never broadcast

A discovery goes to the branches it bears on, and to no others. There is no global channel.

A concrete, deterministic relevance policy — the one this toolkit inherits, offered as a
starting point rather than a law:

```text
+4   the target explicitly depends on the source
+2   the target shares an acceptance criterion with the source
+1   per shared tag, capped at +2
─────
 ≥2  required to deliver at all
 ≤3  targets, ordered by score, then priority, then stable id
```

Pure ancestry or one generic tag is not relevance.

**Ignore it and:** every finding interrupts every agent, and agents start ignoring deliveries
— including the one that mattered.

### O11 · A delivery requests reconsideration; it never proves the receiver wrong

The receiving branch owns its own conclusion. It must answer, from a closed set:

| outcome | meaning |
|---|---|
| `APPLIED` | the discovery changes what this branch does next |
| `NO_CHANGE` | considered, with a concrete reason the existing work stands |
| `FOLLOW_UP_REQUESTED` | a bounded question worth investigating |
| `UNREPORTED` | **recorded by the orchestrator**, never claimable by an agent |

**Silence is never read as agreement.** An unanswered delivery is recorded as unanswered.

**Ignore it and:** either deliveries are ignored with no trace, or they override branches
that had better reasons.

### O12 · Delivery is idempotent, and invalidation retracts

Key each delivery by `(what, which version, to whom)` so redelivering is a no-op. When the
underlying claim stops standing, send a **targeted retraction** to exactly the recipients
that received it.

**Ignore it and:** branches keep acting on a withdrawn discovery, and the same insight
arrives four times because four passes each thought it was new.

### O13 · Consolidate duplicates before anything synthesises

Two agents finding the same thing is one finding with two sources, not two pieces of
evidence. Deduplicate on **content** — the normalised claim plus a signature over the
evidence itself, not its per-run identifiers. Keep every original identity visible, so
"three agents independently found this" stays inspectable without becoming three votes.

Open a **conflict** only where a contradiction is actually establishable — incompatible
structured values, or an explicit declared contradiction. Disagreement in tone is not a
conflict.

**Ignore it and:** the synthesis reports the same fact three times and reads it as
corroboration.

### O14 · Invalidation is transitive

When a claim stops standing, everything that depended on it loses its status too, and so on
through the graph. Then retract what was delivered on its strength (**O12**).

**Ignore it and:** a withdrawn claim's conclusions stay in the answer, now unsupported and
indistinguishable from the supported ones.

---

## Progress and stopping

### O15 · Measure progress from what changed, not what was claimed

A branch reporting activity is not a branch making progress. Measure progress as a function
of what the branch actually changed:

| moves progress | does not move progress |
|---|---|
| a new non-duplicate finding | an exact duplicate |
| a claim newly established | a reworded claim with the same signature |
| newly recorded evidence | a repeated `NO_CHANGE` |
| a conflict resolved | a redelivered discovery |
| criterion coverage changed | another agent agreeing without evidence |

**Ignore it and:** a branch that is looping produces steady output and is never stopped,
because it reports progress every round.

### O16 · Stop a branch with a reason, and record it

Stop when: the run stopped · no progress for N rounds · the wave limit is spent · its
findings are duplicates of another branch's · its criteria are covered · its own work failed
on budget, dependency or attempts.

Stopping cancels only that branch's pending work. Other branches are untouched, and
everything the branch established survives its closure.

**Ignore it and:** either work runs until the budget dies, or branches are killed for
reasons nobody can reconstruct afterwards.

### O17 · Bound re-exploration, and charge a wave only when it opens with real work

Exploration rounds are counted and limited. A new round is charged against the limit only
when the orchestrator actually admits executable work for it. A round considered and not
opened costs nothing.

Crucially: **there is no path from an agent's text to a new round.** "Let me keep looking"
is not a trigger. Triggers are concrete, consumed records — an undelivered discovery, an
unanswered follow-up request.

**Ignore it and:** the loop terminates only when the budget does.

### O30 · A loop cap is a decision point, not another iteration

When a repair or review loop reaches its configured cap, **do not silently run another
round**, and do not silently stop either. Reaching the cap is an event that has to be
resolved.

Every still-open finding gets an explicit disposition, from a closed set:

| Disposition | Means |
|---|---|
| resolved under a ruling | judged acceptable, with the ruling and its reason recorded |
| parked as unresolved | preserved, still open, and carried into the outcome |
| terminates the branch or run | the gap is load-bearing: `EXHAUSTED`, with reasons (**O22**) |
| continuation authorised | explicitly, under a new ruling, where the architecture permits it |

A finding with no disposition is the failure this principle exists to prevent: the loop ends,
the report does not mention it, and an open defect becomes indistinguishable from a closed
one.

**Everything established survives termination.** Hitting a cap ends iteration, not the
record: the evidence collected, the issues still open and the reasons the loop could not
close them all outlive the branch, exactly as a stop reason does (**O16**). A run that
discards its unresolved gaps on the way out has converted `EXHAUSTED` into silence.

**Ignore it and:** caps are either ignored — the loop runs on — or honoured silently, which
reports a clean finish over an unexamined pile.

---

## Completion

### O18 · Readiness is computed, never asserted

No agent decides the run is finished. Compute it from the state of the work:

```text
for every required criterion:
    supported          by a claim that currently stands
    verified           per docs/concepts/verification.md
    dependency-valid   nothing it rests on has been withdrawn
    unconflicted       no open conflict contests it
    unblocked          no unresolved blocking issue touches it
and:
    no required review outstanding
    no required branch work outstanding
    budget remains for one synthesis and one final review
```

The answer is `READY`, `NOT_READY` or `EXHAUSTED` — **always with reasons**.

**Ignore it and:** the run ends when a model feels finished, which correlates with context
pressure rather than with the work being done.

### O19 · Synthesis may only use what it was given

The orchestrator selects the supporting material; the Synthesizer composes from it. It may
not introduce a factual claim no supplied support carries, and it may not cite what it was
not given. **Recompute coverage from the citations it actually made**, never from its
assertion that a criterion is covered.

Anything the evidence does not settle is stated as a limitation rather than smoothed over.

**Ignore it and:** the answer's confidence is a property of its prose, and the citations are
decorative.

### O20 · A reviewed version is immutable

Once a candidate answer has been reviewed, it is never edited. A revision creates a **new
version naming the one it supersedes**, so the version a reviewer judged keeps its content,
its citations and its verdict.

**Ignore it and:** you cannot tell what was approved, and "the reviewer passed it" refers to
something that no longer exists.

### O21 · Re-check the PASS against current state before accepting

A final-review `PASS` is a statement about the state at review time. Before acceptance,
re-check that the gate (**O18**) still holds and that every citation is still valid. Accept
the result in the same step that records completion, so the two cannot drift.

**Ignore it and:** work that landed during review invalidates the thing that was just
approved, and nothing notices.

### O22 · `EXHAUSTED` is not `FAILED`

Four terminal outcomes, each meaning something different, and all absorbing:

| | |
|---|---|
| `COMPLETED` | a reviewed answer, with its support and its provenance |
| `EXHAUSTED` | **the system worked and the evidence or the limits did not suffice** — partial knowledge and unresolved gaps are kept, not dressed up as an answer |
| `FAILED` | the run could not work at all |
| `CANCELLED` | stopped from outside |

`EXHAUSTED` is the honest outcome that most systems lack, and the reason they produce
plausible answers to questions they could not settle.

**Ignore it and:** every run "succeeds", and a successful run tells you nothing.

### O23 · Terminal conditions are explicit and stated up front

Before starting, state what would make this run stop without success: which criteria are
required, how many repair rounds are allowed, what evidence is unobtainable. A stopping
condition invented at the end is a rationalisation.

---

## Conduct of the run

### O24 · Record the decision and the reason, not the narrative

Every routing choice, refusal, stop and promotion should be answerable after the fact from
what was recorded, without re-reading any transcript. The concrete test — if you cannot
answer these from the record, you did not record enough:

```text
Why was this claim treated as established?     the review that settled it, and its decision
What evidence established it?                  the check, its actual inputs, its actual output
Why did this agent receive this discovery?     the routing decision and what matched
Why did this branch stop?                      the stop reason, recorded when it stopped
Why did the run end without an answer?         the gate's last reasons, and every refusal
Which findings support the conclusion?         recomputed from the citations, not asserted
```

**Derive these from the record, not from a parallel tally.** A second bookkeeping of progress
maintained alongside the work will disagree with it, and the disagreement will be discovered
at the worst moment. Recompute from what was actually committed.

**Ignore it and:** the only account of the run is a model's summary of it, which is the one
source that cannot be checked.

### O27 · Disclosure fails closed

Membership permits selection; it never authorises automatic injection. Before passing any
record to an agent, establish that this agent may legitimately see it. **If you cannot
establish who owns it, do not send it.**

The case that catches people: a conflict spanning two branches belongs to neither. Sending it
to one of them presents a contested question as settled — so it is undisclosable rather than
quietly shared with whichever branch is closer to hand.

**Ignore it and:** context leaks by default, and the leak looks like helpfulness.

### O28 · Report what nothing consumed

At the end, say what was recorded and never used: a discovery routed but never answered, a
follow-up requested but never scheduled, a finding nothing cited, a question raised and
dropped.

These are the quiet failures. Nothing went wrong loudly — work was simply done and then not
used — and a report that omits them looks identical to a run where everything mattered.

**Ignore it and:** you cannot tell a run that used its work from one that wasted half of it,
and the same waste repeats next time.

### O25 · Fail closed on anything unrecognised

An unknown verifier kind, an unrecognised expectation, an output field with no home, a
configuration key nothing consumes: **refuse it loudly**. Do not ignore it, and do not guess.

> The original implementation's evaluation harness failed on an expectation it did not
> recognise, precisely because silently ignoring one "would quietly reduce coverage every
> time a scenario is edited."

**Ignore it and:** coverage decays invisibly, and the checks that remain still report green.

### O26 · Prove the guard, do not assume it

A guard that has never refused anything may not work. Establish that each reliability
control actually fires — break it deliberately and confirm something notices.

> The original implementation ran a mutation battery: 37 single-guard mutations, 37 caught,
> plus one control mutation that survived **by design** — because without a known survivor,
> "everything was caught" is indistinguishable from a battery that cannot detect anything.

**Ignore it and:** you have the ceremony of review with none of its protection.
