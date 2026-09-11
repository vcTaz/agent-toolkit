# Canonical roles

These seven files are the **source of truth** for what each role is. Platform adapters
(`.claude/agents/`, `.codex/agents/`) carry platform mechanics and a synchronised copy of
the body below; they never redefine the concept. If an adapter and a role here disagree,
**the role wins and the adapter is defective**.

Nothing in this directory may require a particular harness, vendor, model or language.

## The seven roles

| Role | Posture | One line |
|---|---|---|
| [Explorer](explorer.md) | produce (breadth) | Map unfamiliar territory and report what is there. |
| [Specialist](specialist.md) | produce (depth) | Apply one domain's expertise to a bounded question. |
| [Implementer](implementer.md) | produce (change) | Change the artifact. The only role that may. |
| [Critic](critic.md) | falsify | Attack the work and report what is wrong with it. |
| [Validator](validator.md) | establish | Independently determine whether a claim holds. |
| [Synthesizer](synthesizer.md) | compose | Build one answer from established support only. |
| [Final Reviewer](final-reviewer.md) | judge | Accept, revise or reject the finished deliverable. |

```text
                    Explorer ─┐
                  Specialist ─┼──▶ Critic ──▶ Validator ──┐
                 Implementer ─┘                           │
                                                          ▼
                                                   Synthesizer
                                                          │
                                                          ▼
                                                  Final Reviewer
                                              PASS │ REVISE │ REJECT
```

## What is not a role

- **A different subject is a brief, not a role.** "Security reviewer" is a Critic or a
  Specialist with a security brief. Do not create a role per topic.
- **A deterministic service is not a role.** Routing discoveries, deduplicating findings and
  measuring progress need decisions, not model calls. They are
  [orchestration principles](../docs/concepts/orchestration.md).
- **A workflow step is not a role.** "Architect" is a Specialist producing a design, then
  reviewed like any other artifact — see [workflows/architecture.md](../workflows/architecture.md).

> The implementation this toolkit derives from registered nine roles. Two of them —
> `CONSOLIDATOR` and `CROSS_POLLINATOR` — were never dispatched in any run, because both
> were deterministic services all along.

**The admission bar for an eighth role:** a distinct epistemic posture, a distinct output
contract, *and* a distinct independence requirement. Two out of three means you have a brief.

## How a role file is written

Each file is **second person and directive**, because it is used verbatim as an agent's
instructions on every supported platform. Reading it as documentation and using it as a
prompt are the same act; that is what keeps the layers from diverging.

Every file has the same thirteen sections, in this order, and
[`tools/check.py`](../tools/check.py) enforces it:

```text
Purpose · Use this role when · Do not use this role when · Inputs · Outputs
Decision vocabulary · Independence · Allowed · Prohibited
Interaction with other roles · Verification expectations · Completion conditions
Orchestration principles that govern this role
```

Frontmatter carries `id` (matching the filename) and `summary` (one line).

## Modifying a role safely

1. Edit the canonical file here. Never edit an adapter body.
2. Run `python3 tools/check.py --sync` to regenerate the adapter blocks.
3. Run `python3 tools/check.py` to confirm structure and drift are clean.
4. If the change alters what the role *is* rather than how it is worded, check the workflows
   that name it and the concept documents that reference it.
