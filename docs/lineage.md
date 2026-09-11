# Lineage

Where these patterns came from, and what was removed.

## The origin

This repository previously contained **`swarm-foundations 1.0.0`**: a complete, working
multi-agent research runtime in Python — 43 modules, 9,846 lines, 675 passing tests, built
over eight authorized stages and verified on two Python versions and from a built wheel.

It ran. A packaged scenario went from an objective, through parallel exploration, adversarial
criticism, independent validation against tool evidence, deterministic knowledge routing,
consolidation, a computed completion gate, synthesis and independent final review, to a cited
answer with full provenance — and committed every decision to SQLite so the run could be
reconstructed afterwards.

It was removed anyway, and that is the point of this document.

## Why it was removed

The runtime was not removed because it was broken. It was removed because it answered a
different question than this repository now asks.

> A user should not need Python, a custom runtime or an orchestration engine to benefit from
> this repository.

The runtime could only be used by adopting it wholesale. Its reliability mechanisms — which
are the genuinely valuable part — were expressed as Python classes, SQLite schemas and
enum-keyed policy tables, unusable by anyone running Claude Code, Codex, or anything else.
The ideas were portable; the packaging of them was not.

So the ideas were extracted into `roles/`, `skills/`, `workflows/` and `docs/concepts/`, and
the implementation was removed rather than left behind as a second, divergent definition of
the same concepts.

## It is preserved, not lost

Everything removed is recoverable:

```bash
git show mvp-swarm-v1.0.0 --stat      # 97 files, 23,789 lines
git checkout mvp-swarm-v1.0.0         # the whole working runtime
```

The tag `mvp-swarm-v1.0.0` was created **before** any file was deleted, precisely so removal
would be reversible. The repository had no version control at all until that commit.

## What was extracted, and where it went

Fifty-four distinct mechanisms were carried across. The load-bearing ones:

| From the runtime | Now |
|---|---|
| Three-tier review with distinct closed decision vocabularies | `roles/critic.md`, `roles/validator.md`, `roles/final-reviewer.md` |
| Reviewer independence decided before a request is spent; no self-review fallback | `docs/concepts/independence.md` |
| Blocking issues with stable keys, resolvable only by exact name | `skills/adversarial-review`, `skills/independent-validation` |
| A model `PASS` can only be lowered by the host, never raised | `docs/concepts/independence.md`, `skills/independent-validation` |
| `verifier_kind` registry that fails closed on kinds it cannot check | `docs/concepts/verification.md`, `skills/evidence-verification` |
| A successful tool call is not a verified claim — operands must be the claim's own | `skills/evidence-verification` |
| Bounded context with recorded omissions; fail rather than truncate; never one side of a conflict | `skills/bounded-context-handoff` |
| Targeted propagation with relevance scoring; no broadcast; idempotent; retracts on invalidation | `docs/concepts/orchestration.md` O9–O12 |
| Reconsideration outcomes, with silence recorded as unanswered rather than read as agreement | O11 |
| Progress measured from what a branch changed, not what it claimed | O15 |
| Computed synthesis gate — no model decides a run is finished | O18 |
| Immutable reviewed versions; a revision supersedes rather than edits | O20 |
| `REVISE` classified evidence / presentation / none, from the record | `skills/final-verification` |
| `EXHAUSTED` distinct from `FAILED`, both first-class | O22, every workflow |
| Guards proven by mutation rather than assumed | O26 |

The full concept-by-concept ledger was maintained during the migration and every row was
verified present before a single file was deleted.

## What was deliberately not carried across

These existed only because the repository had its own runtime:

- SQLite persistence, event sourcing, record revisions, transactional commits
- The async work engine, controller, scheduler and admission checks
- The provider and tool abstraction, and the execution seam
- The scenario JSON schema, the CLI and its exit codes
- Inspection, timeline, metrics and rendering projections
- Python packaging, the built wheel, and 675 runtime tests
- Eight stage checkpoint reports documenting the above

The *rules* those modules enforced are in `docs/concepts/orchestration.md`. The machinery that
enforced them is in the tag.

## What the runtime proved that is worth knowing

Two things the implementation established that a specification alone could not:

**Two of its nine roles were never dispatched.** `CONSOLIDATOR` and `CROSS_POLLINATOR` were
registered as roles, given instructions, and then never once selected in any run — because
both were deterministic host services all along. That is why this toolkit has seven roles and
treats consolidation and routing as [orchestration principles](concepts/orchestration.md)
rather than agents. The code demonstrated it before this repository asserted it.

**Its guards were tested by breaking them.** A mutation battery introduced 37 single-guard
defects; all 37 were caught, alongside one control mutation that survived *by design* —
because without a known survivor, "everything was caught" is indistinguishable from a battery
that cannot detect anything. That discipline is now O26, and `tools/check.py`'s own drift
guards were proven the same way rather than assumed.

## The honest cost

This repository can no longer *show* these mechanisms running. It describes patterns it does
not execute, which is a real loss of evidence, and worth stating plainly rather than papering
over.

What mitigates it: the mechanisms were not invented here. Each one was implemented, tested
against deliberate mutation, and exercised end to end before it was written down — and the
implementation that did so is one `git checkout` away.
