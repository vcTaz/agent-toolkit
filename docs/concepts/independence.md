# Independence

> The agent that produced an artifact must not be its only reviewer.

This is the load-bearing reliability rule of the whole toolkit. Everything else — the
verification boundary, the computed completion gate, the terminal vocabulary — assumes it
holds. When it does not, a run produces confident agreement rather than checked work, and
nothing downstream can tell the difference.

## Three reviews, not one reviewer

Collapsing review into a single "reviewer" is the most common and most damaging
simplification available. The three review roles ask different questions, accept different
answers, and fail in different directions.

| | **Critic** | **Validator** | **Final Reviewer** |
|---|---|---|---|
| **Scope** | one claim or artifact | one claim or artifact | the complete deliverable |
| **Question** | what is wrong with this? | does this actually hold? | is this acceptable? |
| **Posture** | falsify | independently establish | judge against requirements |
| **Decisions** | `PASS` · `CHALLENGE` · `INCONCLUSIVE` | `PASS` · `FAIL` · `INCONCLUSIVE` | `PASS` · `REVISE` · `REJECT` |
| **Authority** | decides nothing; records objections | promotes nothing alone | accepts nothing alone |
| **Characteristic failure** | nitpicks style, misses the load-bearing assumption | re-reads the author's reasoning instead of checking it | approves a well-written answer that does not meet the requirement |

The separation is not bureaucratic. A Critic asked to also confirm becomes reluctant to
challenge, because challenging creates work it must then resolve. A Validator asked to also
falsify starts hunting for defects instead of testing the claim. A Final Reviewer asked to
examine individual claims loses sight of the deliverable. Each role is protected from the
others' incentives by not being asked to hold them.

**The vocabularies are closed on purpose.** A reviewer that may answer anything answers
prose, and prose cannot be acted on mechanically. Three decisions, each with a defined
consequence, can be.

## Who may not be whom

Independence is a property of an identity's history, not of its current assignment.

```text
author of the claim        ─┐
                            ├─ may not be the Critic of that claim
                            │
author, or the Critic      ─┴─ may not be the Validator of that claim

any identity that produced any candidate answer in this run
                            ─── may not be the Final Reviewer of it
```

Three distinct identities for generate → criticise → validate. The Final Reviewer is
excluded more broadly: not merely from the version under review, but from *every* candidate
answer the run produced, because a reviewer that wrote an earlier draft is judging its own
approach.

### Decide independence before you spend the request

Independence must be settled **before** an agent is dispatched, not discovered afterwards.
By the time a reviewer has read the artifact, the request is spent and the context is
contaminated; declaring it ineligible then wastes the work, and letting it proceed anyway
silently voids the guarantee.

If no independent identity is available:

- **Record the gap.** The absence of a review is a fact about the run, and it must reach
  whoever reads the result.
- **Do not record a self-review as a review.** A review by the author is not a weaker
  review; it is a different and misleading thing. What you may do instead is the *disclosed
  degraded self-check* defined below, which satisfies nothing.
- **Bound the retries.** An unfillable review that is re-created every cycle becomes an
  infinite queue. Attempt it a fixed number of times, then leave a recorded gap.

> The original implementation refused the assignment with `NO_INDEPENDENT_REVIEWER` and
> spent no provider request. Its commit-time validation then refused to store a validation
> whose reviewer had also criticised the same target — defence in depth, not the primary
> control.

### Reserve capacity for the reviews you will need

A run that spends its whole budget or its whole identity pool on production work cannot
afford the independent review that would make the output trustworthy. Hold back capacity
for one synthesis and one final review from the beginning, and treat that reserve as
unavailable to optional work. A completion that "ran out of budget before review" is not a
completion.

## A fresh context of the same identity is not independent review

This is the canonical statement of the rule, and every place that used to prescribe the
opposite — the host agent definition, all four workflows' **Scaling it down** sections,
`workflows/README.md`, the generic-harness guidance — has been reconciled with it. If you
find one that still disagrees, that file is the defective one and both should be fixed to
match, per [`authority.md`](../authority.md). This document states the reasoning; it does
not outrank a canonical file, and it does not define a role.

- **A fresh context of the same identity is not independent review.** Independence is a
  property of an identity's history, not of the freshness of the current prompt or context
  window. Clearing the context does not clear the history.
- **It may be used as a disclosed degraded self-check** when only one identity is available.
  Disclosed means the output says what it was: a self-check, by the identity that produced
  the work, in a fresh context. That is a real and useful practice — it catches transcription
  errors, contradictions and unstated assumptions — and it is not review.
- **It never satisfies a requirement for independent evidence.** Not a workflow stage, not a
  readiness criterion, not a completion condition, and not a Critic, Validator or Final
  Reviewer requirement. Anything that explicitly requires independence remains unmet.
- **If completion requires independent review and no independent identity is available, the
  honest terminal state is `EXHAUSTED`.** The work happened; the independence the criterion
  demanded was unobtainable. That is not a failure of the run and it is not a completion
  either — see the terminal vocabulary in
  [`orchestration.md`](orchestration.md) (**O22**).

The tempting move is the one this rule exists to refuse: run the self-check, find nothing,
and let the criterion quietly count it. A criterion satisfied by a degraded substitute is
indistinguishable, afterwards, from one that was actually met.

## Concurrent reviews stay separately attributable

Independent reviews of the same artifact — run concurrently, or simply by different
identities — are **separate results, and they stay separate**.

> Their findings and rankings must not be silently merged or re-ranked by the orchestrator,
> because doing so turns orchestration into substantive review judgement.

The orchestrator may route, deduplicate on content, and order work. Deciding that one
reviewer's blocking issue is really the same as another's, or that a ranked list of concerns
should be re-ordered, is not routing — it is the review judgement the reviewers were
dispatched to make, performed afterwards by an identity with no independence requirement of
its own and no obligation to defend it.

What is permitted:

- **Consolidating exact duplicates on content**, keeping every original identity visible, so
  that "two reviewers independently raised this" stays inspectable (**O13**).
- **Recording an establishable contradiction as a conflict**, and passing all sides on
  (**O13**, and the handoff rule against presenting one side of an open conflict).

What is not:

- Dropping one reviewer's finding because another's reads better.
- Merging two near-but-not-identical findings into one, which loses whichever part the
  wording did not survive.
- Re-ranking a reviewer's severities, or promoting a non-blocking item to blocking, or
  demoting a blocking one.

Two reviews that disagree are a result, not a problem to be tidied. The disagreement is
information about the artifact, and resolving it is a review question — so it goes to a
review identity, not to the orchestrator's summary.

## Blocking issues have identity

A critique whose objections are prose can be discharged by a later agent writing "addressed
all concerns". Objections therefore need **identity**.

1. Every blocking issue a Critic raises gets a **stable key** — in the original
   implementation, `<review-id>#<index>`.
2. Those keys are handed to the Validator as part of its brief.
3. A blocking issue is resolved only when a passing review **names its exact key**.
4. A key that was never issued resolves nothing. Invented keys are discarded before the
   review is recorded, so naming a plausible-sounding issue buys nothing.
5. An artifact with an unaddressed blocking key cannot be promoted, regardless of what any
   reviewer concluded.

This converts "the critic had concerns" from a narrative into a checklist with a closed set
of items, and it is the mechanism that makes `CHALLENGE` meaningful rather than advisory.

## A model's PASS is necessary and never sufficient

A reviewer's decision is one input to the recorded outcome, and it can only ever be
weakened by what the host can check:

| reviewer says | host check says | recorded |
|---|---|---|
| anything | `FAIL` | `FAIL` |
| `FAIL` | anything | `FAIL` |
| `PASS` | `PASS`, every blocking key resolved, dependencies still standing | `PASS` |
| anything else | | `INCONCLUSIVE` |

**The host can only lower the outcome, never raise it.** There is no combination in which
model confidence upgrades a failed or inconclusive check. `INCONCLUSIVE` never promotes
anything — an examination that reached no conclusion is not a weak yes.

See [`verification.md`](verification.md) for what "the host can check" means and where its
limits are.

## Independence in practice, per harness

The canonical rule is identity-based and harness-neutral. How you satisfy it differs:

- **Fresh context is necessary but not sufficient.** A subagent with a clean context window
  that is handed the author's reasoning to review is not independent of it; it has been
  told the conclusion. What you pass matters as much as who you pass it to — see
  [`skills/bounded-context-handoff`](../../skills/bounded-context-handoff/SKILL.md).
- **One session acting in sequence cannot preserve independence.** A single agent switching
  hats keeps the artifact and its own prior reasoning in its history, and a fresh context
  does not remove it. If that is all you have, run it as a **disclosed degraded self-check**
  under the rule above: say in the output what it was, and do not let it satisfy anything
  that requires independence.
- **Name your agents and track what they touched.** Independence cannot be enforced if you
  cannot answer "who wrote this?" — which is why hand-offs should carry provenance.

## What independence does not buy you

Independent review is *review*. Three separate models agreeing that a claim is true is
still three models agreeing; it is not evidence that the claim holds. Treating agreement as
proof is the precise failure the next document exists to prevent.
