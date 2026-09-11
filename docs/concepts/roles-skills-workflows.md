# Roles, skills, workflows and orchestration principles

Four different things get called "an agent". Separating them is the first thing this
toolkit does, because most of the failure modes in multi-agent work come from putting a
concept at the wrong level — spawning a model to do arithmetic a function could do, or
burying a reliability rule inside one agent's prompt where nothing else can see it.

```text
ROLE                 what responsibility is an agent assuming for this assignment?
SKILL                what reusable procedure can an agent perform?
WORKFLOW             how do roles and skills cooperate to reach a larger objective?
ORCHESTRATION        what rule governs the whole run, belonging to no single agent?
```

## Role

A role answers: **what responsibility is this agent assuming, right now, for this piece of
work?**

A role is not a job title, a seniority level, or a person. It is a capability an
orchestrator assigns for the duration of one assignment and takes back afterwards. The same
underlying agent may be an Explorer on one assignment and a Critic on the next — but never
both at once, and never a Critic of something it produced as an Explorer.

The seven canonical roles live in [`roles/`](../../roles/). Each is defined by three things
that must all differ for a role to deserve its own definition:

| | |
|---|---|
| **Epistemic posture** | What is this role's relationship to truth? Producing a claim, attacking it, confirming it, assembling from confirmed claims, or judging the whole. |
| **Output contract** | What is this role structurally permitted to emit? A Critic that can emit findings is not a Critic. |
| **Independence requirement** | Whom may this role not be? A Validator that may be the author is not a Validator. |

A role that differs from an existing role only in *subject matter* is not a new role. It is
a **brief** — the same role pointed at a different problem. "Security reviewer",
"performance reviewer" and "accessibility reviewer" are three briefs for one Specialist or
one Critic, not three roles. This distinction is what keeps the role set from growing
without limit.

> **The admission bar for a new role:** a distinct epistemic posture, a distinct output
> contract, *and* a distinct independence requirement. Two out of three is a brief.

## Skill

A skill answers: **what reusable procedure can an agent perform?**

A skill is a portable method, not an identity. Roles use skills; skills do not have roles.
A Critic uses `adversarial-review`; so may an Implementer checking its own reasoning before
handing work on, and so may a lead deciding whether a teammate's report holds up.

The skills in [`skills/`](../../skills/) are written in the
[Agent Skills](https://agentskills.io) format — a published specification that roughly
forty agentic clients read, including both harnesses this toolkit targets. That is why they
need no platform adapter.

This toolkit deliberately ships **few** skills. Every one encodes a procedure that is
specific to reliable multi-agent work and is not already well served by the host platform.
Generic engineering procedures — writing tests, reviewing a diff, debugging — belong to the
harness's own skill ecosystem, not here. A skill added merely to populate the directory
costs context budget on every session that loads it and teaches nothing.

## Workflow

A workflow answers: **how do several roles and skills cooperate to reach an objective
larger than any one of them?**

A workflow names its roles, the order they act in, which segments are genuinely parallel and
why, what each hand-off carries, and — most importantly — the conditions under which it
terminates without success. The workflows in [`workflows/`](../../workflows/) are
descriptions of a process, not programs. Nothing executes them; a human or a lead agent
follows them.

A workflow that adds a role without giving it something the other roles cannot do is
theatre. Every role in every workflow here must be removable only at a stated cost.

## Orchestration principle

Some behaviour belongs to no agent. It is a property of how the run is conducted:

- route a relevant discovery to the branches it bears on, and to no others;
- give one artifact exactly one owner;
- consolidate duplicate findings before anything synthesises them;
- measure a branch's progress from what it changed, not from what it reported;
- compute whether the run is ready to answer, rather than asking a model.

None of these is a role. Manufacturing an agent for each — a "Consolidator", a
"Cross-Pollinator", a "Progress Monitor" — produces model calls that decide nothing and
obscures the fact that the rule is deterministic and belongs to the orchestrator. The
catalogue is [`orchestration.md`](orchestration.md).

> The original implementation this toolkit derives from registered nine roles. Two of them
> — `CONSOLIDATOR` and `CROSS_POLLINATOR` — were never once dispatched in any run, because
> both were deterministic host services all along. They are orchestration principles here,
> and the code proved it before this document claimed it.

## How to tell which one you have

Work through these in order. The first "yes" is your answer.

1. **Is it a rule about the run as a whole, that no single agent could enforce from inside
   its own assignment?** → orchestration principle.
2. **Can it be decided deterministically, without a model?** → orchestration principle. Do
   not pay for judgement you do not need.
3. **Is it a procedure that several different roles would each want to perform?** → skill.
4. **Does it have a distinct epistemic posture, output contract *and* independence
   requirement?** → role.
5. **Otherwise** → it is a brief for an existing role, or a step inside an existing skill.

## Agents, roles, and whether an agent may change role

An **agent** is a concrete process with a context window — a Claude Code subagent, a Codex
subagent, a teammate, a session, a thread. A **role** is what it is doing.

An agent may change role between assignments, and this toolkit assumes it will. What it may
never do is hold a role that conflicts with a role it previously held on the same artifact.
Independence is a property of the *history* of an identity, not of its current label; see
[`independence.md`](independence.md).

Two practical consequences:

- **Assign the role before you spend the request.** If no independent identity is available
  for a review, that is a fact to record and act on, not something to discover after the
  reviewer has already read the artifact.
- **Do not let a role leak across a hand-off.** A Critic that starts fixing what it found
  has stopped being a Critic, and its findings have lost their independent reviewer.
