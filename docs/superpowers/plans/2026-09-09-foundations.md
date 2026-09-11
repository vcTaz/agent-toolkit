# Stages 1–3 implementation plan

Goal: implement only the approved domain, audit storage, and execution seam.
Spec: INSTRUCTIONS/implementation-prompt-stages-1-3.md amends docs/architecture-review.md.
Architecture: frozen records, explicit domain services, transactional SQLite snapshots and events, async bounded execution producing proposals.
Stack: Python >=3.11, standard-library runtime and unittest. No scheduler or workflow.

1. Write domain tests in tests/test_domain.py for round trips, state guards, DAG/reference validation, idle role changes, immutable claims and invalidation. Run with PYTHONPATH=src python3 -m unittest discover -s tests -v. Implement domain.py and serialization.py, then rerun.
2. Write persistence tests in tests/test_persistence.py for record/event transactions, optimistic revisions, independent sequences, reload and storage errors. Implement events.py and persistence.py with SQLite transactions; rerun all tests.
3. Write execution tests in tests/test_execution.py for strict draft parsing, permissions, real arithmetic evidence, bounded repair/accounting, provider errors and deadlines. Implement contracts.py, output.py, execution.py, providers/fake.py and tools/arithmetic.py; rerun all tests.
4. Review trust boundaries, add regression tests for discovered gaps, update architecture amendments and README, run full suite and package checks. Stop before Stage 4.

No Git commits are possible in this workspace's empty .git directory. No reinitialization is part of this scope.
