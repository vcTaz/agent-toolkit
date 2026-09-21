# Any other agent harness

You do not need Claude Code or Codex to use this repository, and you do not need to adopt any
runtime. The canonical layers — `roles/`, `skills/`, `workflows/` — are Markdown with no
vendor, model, language or framework dependency.

This page is how to map them onto a harness that is neither of the two with adapters here.

Claims below about other harnesses (which read `AGENTS.md`, which implement Agent Skills,
Zed's instruction-file precedence) were verified against those projects' documentation in
September 2026 and are the most perishable content in this repository. Check them before
relying on one.

## What you are adopting

```text
ROLE            a responsibility an agent assumes for one assignment
SKILL           a reusable procedure any role may perform
WORKFLOW        how roles and skills cooperate toward an objective
ORCHESTRATION   a rule governing the run, belonging to no single agent
```

Full treatment in `docs/concepts/roles-skills-workflows.md`.

## The mapping

| This toolkit | What your harness probably calls it |
|---|---|
| Role | subagent type, agent profile, persona, worker class, assistant definition |
| Role body | system prompt / developer instructions for that agent |
| Skill | skill, reusable prompt, playbook, tool description, or simply a document you paste |
| Workflow | your orchestration script, your runbook, or your own head |
| Orchestration principle | how you conduct the run — usually not a configurable object |

If your harness has **no** notion of distinct agents, everything here still applies: run the
roles sequentially in fresh contexts, because the separation of posture is most of the value
and it does not depend on the mechanism.

What it does **not** give you is independence. A fresh context of the same identity is a
disclosed degraded self-check, never an independent review, and it satisfies no criterion
that requires independent evidence — see `docs/concepts/independence.md`. Where a harness
gives you only one identity and completion requires an independent review, the honest
terminal state is `EXHAUSTED`, not a self-review recorded as a review.

## Minimum viable adoption

In increasing order of effort. Each step is useful on its own.

### 1 · Use the roles as prompts

Take the body of `roles/critic.md` and use it as the system prompt for a fresh agent. That is
the whole integration. The files are written in second person and directive precisely so this
works with no transformation.

### 2 · Enforce independence

The one rule that carries most of the value:

> The agent that produced an artifact must not be its only reviewer.

At minimum, review in a **fresh context that did not produce the work** and was not told the
conclusion. See `docs/concepts/independence.md`.

### 3 · Adopt the decision vocabularies

Closed sets, so a verdict can be acted on mechanically instead of interpreted:

```text
criticism      PASS | CHALLENGE | INCONCLUSIVE
validation     PASS | FAIL      | INCONCLUSIVE
final review   PASS | REVISE    | REJECT
terminal state COMPLETED | EXHAUSTED | FAILED | CANCELLED
```

The first three terminal states are reached by the run's own execution and evaluation;
`CANCELLED` is imposed from outside it. `EXHAUSTED` is the one most systems lack and the
reason they produce plausible answers to questions they could not settle.

### 4 · Adopt the verification boundary

`model agreement != verification`. Grade every load-bearing claim **verified** or **reviewed**,
and fail closed when no check exists. See `docs/concepts/verification.md`.

### 5 · Follow a workflow

Pick the one that matches your objective from `workflows/`. Each has a *scaling it down*
section; most real tasks should use a reduced form.

## Writing an adapter for your harness

If your harness has native agent definitions, a thin adapter is worth it. Follow the same rule
the existing two follow:

> **One conceptual definition; multiple platform adapters.**
> An adapter carries platform mechanics only. It never redefines the role.

An adapter should contain:

- the identifier and a description used for delegation
- tool or capability limits
- model or effort selection, where your harness has one
- permission or sandbox constraints
- a small number of harness-specific operating notes
- the canonical role body, **copied verbatim and marked as generated**

and nothing else. If you find yourself rewording the role's responsibilities in the adapter,
stop: either the canonical role is wrong and should be fixed, or you are forking it.

### Keeping the copy honest

`tools/check.py` is ~250 lines of standard-library Python that verifies role structure, skill
conformance, adapter coverage and — the important part — that every copied body still matches
its canonical source by SHA-256. `--sync` regenerates the copies.

Extending it to a third adapter format means adding a `sync_<platform>` function beside the
two that exist. That is the intended extension point, and it is the only one.

If you would rather not run Python at all, the markers are self-describing: each adapter
names its source file and the digest of the body it copied, so any tooling can check it.

## Skills need no adapter

`skills/` is written in the [Agent Skills](https://agentskills.io) format, a published
specification with a validator and roughly forty implementing clients. If yours is one of
them, point it at `.agents/skills` — the convention the specification recommends for
cross-client sharing — or at `skills/` directly.

If it is not, the files are still just Markdown with two frontmatter fields. Paste them.

## Instructions need no adapter either

`AGENTS.md` is read natively by Codex, Cursor, Zed, Amp, GitHub Copilot's coding agent, and a
long list of others; Aider and Gemini CLI read it with one line of configuration. `CLAUDE.md`
imports it rather than duplicating it.

**One caution:** some harnesses resolve project instructions by *first match* across a list of
candidate filenames. Zed, for example, checks `.rules`, `.cursorrules`, `.windsurfrules`,
`.clinerules`, `.github/copilot-instructions.md`, `AGENT.md`, and only then `AGENTS.md`. This
repository deliberately ships **none** of the earlier names, so `AGENTS.md` is reachable. If
you add one to a consuming project, expect it to shadow `AGENTS.md` there.

## What you should not build

Resist the urge to write a runtime for this. A scheduler, a DAG executor, a YAML workflow
language, a prompt compiler or a plugin system will cost more than it returns and will be
obsolete when your harness ships its own.

The value here is in the separations — who may review whom, what counts as evidence, when a
run is genuinely done — and those are enforced by discipline and by small checks, not by
machinery.
