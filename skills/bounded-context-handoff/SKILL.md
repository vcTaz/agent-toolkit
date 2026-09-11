---
name: bounded-context-handoff
description: Construct exactly what a delegated agent needs and nothing more, so it can work independently without being anchored to your conclusions. Use when writing a subagent or teammate prompt, delegating work, handing findings between agents, briefing a reviewer, splitting work across parallel agents, or deciding what context to pass along. Prevents transcript dumping, conclusion-leaking into reviews, and one-sided conflict presentation.
---

# Bounded context handoff

What you pass to a delegated agent determines what it can do and biases what it will
conclude. Constructing that package deliberately is a skill; forwarding your own context is
the absence of one.

Two rules govern everything below:

> **Propagate discoveries, not transcripts.**
> **Never hand a reviewer the conclusion you want it to reach.**

## The procedure

### 1. Decide what this agent must be able to do

Write it down first, in one sentence. Then select against it. Selecting context before
deciding the job produces a package built from what you happen to have.

### 2. Select, bound, and record what you left out

| Include | Exclude |
|---|---|
| The objective, stated precisely | Your reasoning about the objective |
| The specific artifact and version | The conversation that produced it |
| Established findings, as bounded statements | Transcripts, deliberation, other agents' drafts |
| The criteria it will be judged against | Your expectations about the answer |
| What it owns and may change | Everything it does not own |
| Approaches already tried and failed | The narrative of trying them |
| Constraints and conventions that apply | Context "in case it's useful" |

**Record what you omitted and why.** Not for bureaucracy: when an agent returns a wrong
answer, the first question is whether it could have known better, and an unrecorded omission
makes that unanswerable.

**When in doubt about whether this agent may see something, leave it out.** Disclosure fails
closed. Being on a team permits *selection*; it does not authorise passing along everything
that exists.

### 3. Bound it with actual limits

Caps force selection. Without them, "relevant context" expands to everything.

> The original implementation capped one assignment's context at 8 validated findings, 4
> candidate summaries, 5 messages, 3 failed approaches and 3 delivered discoveries, within
> 24,000 characters — and recorded every selection, omission and reason.

Pick numbers that suit your work. The point is that a number exists.

### 4. If something indispensable will not fit, fail — do not truncate

If a required input cannot be included within the bounds, **stop and say so**. Do not
silently drop it and dispatch anyway.

An agent working from a quietly truncated package produces an answer that looks complete and
is not, and nothing downstream can tell. Failing loudly costs one round trip; truncating
silently costs a wrong answer that survives review.

### 5. Never present one side of an open conflict

If findings disagree and you pass only one, the receiving agent will treat it as settled and
build on it. **A contested finding travels with its counterparts, or not at all.**

This is the least obvious rule here and the one most likely to be violated by accident, since
passing the finding you believe is the natural thing to do.

### 6. For reviewers, withhold the conclusion

A reviewer given the author's reasoning checks whether the reasoning is coherent. A reviewer
given the artifact checks the artifact. These produce different reviews and only one of them
is worth having.

| Give a reviewer | Withhold |
|---|---|
| The artifact, at an exact version | The author's justification narrative |
| The requirement it must meet | Your opinion of whether it meets it |
| Blocking issues by identifier | How you expect them to be resolved |
| The evidence, as recorded | The author's summary of the evidence |

Fresh context is necessary and not sufficient. A clean context window that has been told the
conclusion is not independent of it.

### 7. Make the return contract explicit

State what you need back and in what shape: the decision vocabulary, the fields, the level of
detail. An agent that does not know what shape its answer should take will produce prose, and
prose cannot be acted on mechanically.

Say also what it must **not** do — write files it does not own, expand scope, create work.

### 8. Give it provenance, so independence can be checked

The package should make answerable: who produced this, at what version, and what has already
reviewed it. Independence is a property of history, and history that was not passed along
cannot be enforced.

## Handoff template

```text
OBJECTIVE
  <one sentence: what this agent must be able to do>

ROLE
  <which role; link the canonical role file>

YOU OWN
  <files, artifacts, region — explicit; nothing else may be written>

ESTABLISHED
  <bounded statements, with locators and epistemic grade — not transcripts>

CONTESTED
  <open conflicts, ALL sides, or omit the finding entirely>

ALREADY TRIED AND FAILED
  <so it is not repeated>

CRITERIA
  <what the result is judged against>

RETURN
  <required shape; decision vocabulary; what not to do>

OMITTED
  <what was left out, and why>
```

## What this prevents

| Failure | Cause |
|---|---|
| Anchoring | The reviewer was told the conclusion before examining the work. |
| False corroboration | Two "independent" agents shared a context and agreed with it. |
| Context bloat | Every agent reads every other agent's deliberation; cost scales quadratically. |
| Silent incompleteness | A required input was dropped to fit, and nothing said so. |
| Settled-looking conflicts | One side of a disagreement was passed; the receiver built on it. |
| Collisions | Two agents were not told who owned what. |
| Unusable returns | No shape was specified, so the answer is prose. |
| Unenforceable independence | Provenance was not carried, so nobody can check who wrote it. |

## Common failure modes

| Failure | What it looks like |
|---|---|
| Forwarding your context | "Here's everything I know" — the absence of the skill. |
| Just-in-case inclusion | Context added because it might help; the signal is now buried. |
| Summarising evidence | Passing your reading of a tool's output instead of the output. |
| Leaking the answer | "Review this fix for the race condition in `send()`" — you named the bug. |
| Unbounded selection | No caps, so selection never actually happened. |
| Silent truncation | It did not fit, so it was cut, and nobody was told. |

## Related

- [Independence](../../docs/concepts/independence.md) — why the handoff, not just the
  identity, determines whether a review is independent.
- [Orchestration O9–O12](../../docs/concepts/orchestration.md) — discoveries not transcripts,
  targeted delivery, reconsideration and retraction.
- Every role's **Inputs** section states what that role should receive.
