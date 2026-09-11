# CLAUDE.md

This repository uses `AGENTS.md` as the primary persistent project instruction file.

Before making changes:

1. Read `AGENTS.md`.
2. Read `docs/mvp-architecture.md` for the architecture as implemented.
3. Read `docs/stage-8-report.md`, the current MVP checkpoint.
4. Preserve the architectural invariants and implementation boundaries documented there.
5. Treat the repository as the source of truth for current implementation state.
6. Do not infer implementation state from previous chat history when the repository contains a newer checkpoint.
7. Do not begin post-MVP/V2 work unless explicitly authorized.

Current state (see `AGENTS.md` for detail): **Stages 1-8 are complete and verified.
The MVP is complete.** No post-MVP/V2 work is authorized.

Core project principles:

- Functional agent roles, not simulated human job titles.
- Models/executors propose.
- Controllers decide.
- Repository commits authoritative state.
- Validation requires evidence, not model agreement.
- Shared context is bounded and deliberately selected.
- Discoveries propagate, transcripts do not; delivery is targeted and bounded, never broadcast.
- Progress is measured from what changed, not from what an agent claimed.
- Readiness to answer is computed by the controller, never asserted by a model.
- A run completes only on an independent reviewer PASS that still holds against current state.
- A reviewed result version is immutable; a revision creates a new version.
- EXHAUSTED means the system worked and the evidence or limits did not suffice; FAILED means it could not work at all.
- What can be verified is decided by the criterion verifier policy; arithmetic is the shipped trusted verifier, and an unsupported verifier kind fails closed.
- Prefer deterministic, inspectable policies before learned or LLM-driven policies.
- Avoid premature distributed infrastructure, embeddings, vector databases, hidden retries, and unnecessary frameworks.

If this file conflicts with `AGENTS.md`, `docs/mvp-architecture.md`, or a newer repository checkpoint, follow the more specific and more recent repository documentation and report the discrepancy.
