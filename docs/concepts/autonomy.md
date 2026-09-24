# Autonomy

> Delegating work is cheap. Widening what anything may do is expensive, and nothing inside a
> run may do it.

This document is the reasoning behind `agents/registry.json`, the ceilings `tools/check.py`
holds over it, principles **O31** to **O34**, and the eval suite that decides when a workflow
may be trusted further. It defines none of them. The registry records what each definition
may do; `agents/orchestrator.md` says how the orchestrator uses it; `tools/check.py` is the
enforcement. If this file and one of those disagree, that file wins (`docs/authority.md`).

## Two kinds of autonomy, kept apart

"How autonomous is it?" is two questions, and answering one as if it were the other is how
authority leaks.

| | Operating autonomy | Acceptance autonomy |
|---|---|---|
| **Question** | what may the orchestrator do *during* a run without asking? | may a run's *outcome* be relied on without a human checking it again? |
| **Examples** | decompose, pick the role, write the brief, retry, re-dispatch, park a finding, reach `EXHAUSTED` | "the research workflow's answers need only spot checks" |
| **Bounded by** | **O31** and the ceilings in `tools/check.py` | the ladder below, per workflow, and the eval record |
| **Granted by** | landing the orchestrator's definition | a human landing a registry change the eval record supports |
| **Undone by** | the run ending; everything it did is recorded and reversible | a registry change back down |

Operating autonomy is broad by design. Everything in it happens inside the run, is recorded,
and can be undone, so asking a person about it would only make the person the slowest part of
every run (**O33**). Acceptance autonomy is narrow by design, because it is the decision to
stop looking.

## The ladder

Acceptance autonomy is earned in stages, **per workflow**. A workflow is a shape of work, and
trust earned on research questions says nothing about changes to code.

| Level | Means | Here |
|---|---|---|
| L0 | a human watches everything | available, for new and untrusted capability |
| L1 | the agents act; a human verifies the result | **where every workflow starts** |
| L2 | the agents act and are independently verified; a human sees only disputed or high-risk outcomes | the ceiling. Reached only through the eval record |
| L3 | eval-gated execution with no routine human review | not available: it needs evaluation of every role, not only the orchestrator |
| L4 | pull requests opened automatically | not available |
| L5 | changes merged automatically | not available |

The ceiling is not a registry value. `tools/check.py` accepts only `L0`, `L1` and `L2`, fixes
`opensPullRequests` and `merges` at `false`, and stops a push at the run's own working branch.
Raising any of these is a change to `tools/check.py`.

## Why the ceilings live in code

The registry is data. Anything that can edit data can edit a ceiling written as data, and the
agents a registry describes are exactly the things that can edit files. So the registry holds
only values from closed vocabularies, and the vocabularies are the ceilings:

- an edit to the registry alone cannot grant a merge, a pull request or a push to the default
  branch, because no value that means that is accepted;
- an edit to the registry **and** a role's adapters together cannot make a read-only role a
  writer, because the list of roles that may write is also in `tools/check.py`;
- a Claude Code adapter cannot quietly gain what the registry does not grant, because its
  frontmatter keys come from a closed set and may each appear once, a role's tools come from
  a closed list that classifies each one as reading or writing, and anything written as a
  nested block is refused rather than skipped;
- a Codex adapter's sandbox mode is the one Codex reads, because the file must have the one
  shape `--sync` writes: flat keys, each set once, and nothing after the synced body. Its
  other keys are not checked against a closed set.

**That is all this layer guarantees.** A change that edits `tools/check.py` as well passes its
own checks. What stops that change is that a human lands it, and that the default branch is
protected so that only a human can. The repository check is a floor under human review, not a
substitute for it.

## Where authority comes from

**O31** reads authority from the default branch *as fetched from the remote at the start of a
run*. Not from the working tree, which the run can edit, and not from a local ref, which the
run can move. The fetched copy is as trustworthy as the protection on the remote branch, and
no more.

A human's instruction naming one human-owned act — "open the pull request as a draft" —
authorises that act once. It changes no recorded authority, and it is not a precedent. The
next run starts from the same fetched registry as this one did.

## The routes by which authority could expand, and what closes each

Stated plainly, because a boundary described as stronger than it is invites the wrong
reliance. Four layers exist: what the harness enforces, what the repository check rejects,
what a human lands, and what the remote refuses. A fifth — the orchestrator's instructions,
graded by the eval suite — is what remains where none of the four reach.

| Route | Closed by |
|---|---|
| edit the registry, an adapter, or both, to raise a ceiling | the repository check |
| the same, together with the check itself | a human landing it, and branch protection |
| open a pull request, or any other outward action | instruction, graded by an eval |
| write a new agent definition mid-run and dispatch it | the harness in the one mode measured; **instruction elsewhere** |
| edit a role's adapter or the harness settings mid-run | **instruction**, graded by an eval that the governing files are unchanged; both edits are documented to take effect in the running session |
| launch a nested session from a shell, with whatever definitions it likes | **instruction only**, graded by an eval that catches a plain launch and not a disguised one |
| a worker told by text it read to grant something | the receiving rule of `bounded-context-handoff`, **O3**, and an eval |
| read a credential through a subprocess | **instruction only** |
| downgrade an escalation to avoid a review | **O29**; the ruling belongs to a human |

Where a row says *instruction*, the honest description is: the orchestrator is told not to,
and a scenario in the eval suite checks that it did not, in the modes the suite runs. That is
a real control and a weaker one than a harness refusal, in the same way that read-only `Bash`
for the review roles is instructed rather than enforced. The harness facts behind each row,
with how they were established, are in `docs/platforms/claude-code.md`.

Protecting the default branch turns the repository check and human landing into enforcement
for everything that has to reach that branch. It does nothing for a route whose effect happens
inside the run, which is why those rows exist.

## A human approval is not evidence

**O32.** `docs/concepts/verification.md` trusts a claim when something *outside the models* is
checked against it. A person is outside the models, so without a rule, "the human approved it"
would read as verification — and the person would be asked, run after run, to check what a
test could have checked.

An approval is an **authority decision**. It discharges a human-owned decision: land this,
accept that open finding, spend that money. It does not change what the evidence shows. A
claim the human approved is exactly as established as it was before.

## Production is bounded by review

**O34** reserves the budget for one independent review before each producing dispatch. The
reason is arithmetic. A producer's output is worth something only once reviewed; ten parallel
producers with review capacity for three yields three reviewed results and seven that are
discarded or, worse, accepted unreviewed. Scaling the number of agents is safe only as far as
verification scales with it.

## What the eval suite is for

The suite exercises the orchestrator, end to end, on scenarios whose pass conditions are
decided from the tool log and the files left behind — never by a model. It exists to answer
one question per workflow: *may this workflow move from L1 to L2?*

**Results expire.** A results record is bound to a digest of every file that shapes the
orchestrator's behaviour: its definition, the roles, skills and workflows, the adapters, the
harness settings, the instructions files, the suite and its runner. Any change to any of them
expires the record, and `tools/check.py` recomputes the digest rather than trusting it. The
registry is excluded, because recording the result edits it. The model and harness version
are recorded but cannot be checked from the tree.

**Controls are required.** A suite whose scenarios cannot fail proves nothing (**O26**). Two
controls run alongside: a definition with its human-owned list, admission rules and
verification routing removed, which must fail the scenarios it is meant to protect, and a
definition that does nothing and stops, which must pass none of the scenarios that require
work to have happened. Every grader states a precondition, and an unmet precondition is
`INCONCLUSIVE`, never a pass. That does not stop a run that did nothing from passing a
scenario whose test is that something was *not* done: the null control's report passes E14
and E15. That is why the null control is scored only on the scenarios that require work.

## Why five runs is a smoke gate and not a reliability rate

A workflow reaches L2 only if every safety scenario passes **five of five** and every quality
scenario mapped to it passes at least **four of five**, in both of the ways the orchestrator
is run.

Five passes in five runs is consistent with a true failure rate as high as **45%** — the exact
95% upper bound is 1 − 0.05^(1/5). Bounding the rate below 10% would take 29 consecutive
passes. So five runs catches gross failure and nothing finer. It is not a measurement of how
often the orchestrator gets things right, and nothing here should be read as one.

That is why the evals are not what stops the orchestrator crossing a line. The ceilings, the
human who lands changes and the protected branch do that. The evals decide something smaller:
whether a workflow's outcomes still need a human to check each one.
