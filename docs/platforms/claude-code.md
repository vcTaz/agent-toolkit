# Claude Code

Verified against **Claude Code 2.1.278**, measured with `claude --version` in a cloud
session on 2026-09-20. This header read 2.1.269 until then, with a month and no date and no
record of how it was obtained, while five other files said 2.1.278; the number here is now a
measured one rather than the more popular one. That standard does not extend to every claim
below: **What was checked, and how** at the foot of the file gives each one its own method
and date, because running a mechanism and reading about it are not the same evidence.
Mechanisms change; if something here disagrees with the official documentation, the official
documentation is right and this file is stale.

## What this repository provides

| Layer | Path | Mechanism |
|---|---|---|
| Roles | `.claude/agents/*.md` | subagent definitions — also serve as teammate types |
| Skills | `.claude/skills/` | real directory; each entry is a symlink to the skill |
| Instructions | `CLAUDE.md` → imports `AGENTS.md` | project memory |

Nothing needs installing. Open the repository with Claude Code and all three are
discovered. On Windows, clone with `git clone -c core.symlinks=true`, or those symlinks are
checked out as text files and skills are not found.

### The skills directory is a real directory of symlinks, not a symlink

This is the single most-misdescribed thing in the repository, so it is stated exactly.

`.claude/skills/` is a **real directory**. Each `<skill-name>` entry inside it is a symlink to
the skill's own directory. Nothing is copied, so there is still exactly one copy of each skill
and no adapter layer for them — but the link is one level lower than a casual reading suggests.

The shape is not cosmetic. Anthropic documents that a *`<skill-name>` entry* in a project
skills directory may be a symlink and that Claude Code reads `SKILL.md` from the target. It
does **not** document a symlinked skills *container*. So the container stays real and the
entries do the linking, and `tools/check.py` fails if either drifts:

```text
.claude/skills/              real directory
.claude/skills/<name>   →    ../../skills/<name>      the seven canonical skills
.agents/skills          →    ../skills                container symlink (see below)
```

Measured 2026-09-20 in a cloud session: the entry symlinks are followed, and every skill this
repository carried then — six — appeared in the session's skill list. The same shape was
confirmed twice more that day against the optional pack repositories, in fresh sessions with
this repository absent — see `packs/README.md`. Third-party skills are no longer in this
directory; they are attached per Project instead, which is what that open question resolved to.

Measured again 2026-09-22, at 2.1.278, once the seventh skill existed: a fresh cloud session
given a temporary validation repository whose `main` was commit
`2f68916d21c21ced2a88d18a5f6f17349a2e1eb2` discovered all **seven**, resolved all seven
entries, and invoked `checkable-findings` through the Skill mechanism. That run is scoped to
that tree at that commit; delivery from this repository's own `main` carries the same shape
but is a separate checkout and was not the thing measured.

`.agents/skills` **is** a container symlink to `skills/`, for Codex and the other clients that
implement the Agent Skills convention. That asymmetry is deliberate: the Agent Skills
convention is generic about the container, and Claude Code's documentation is specific about
the entry. Do not "tidy" the two into the same shape.

## Installing it as a plugin

Opening the repository serves that repository only. To use the toolkit from any other project
without a checkout, install it as a plugin. The repository is its own marketplace:

```text
/plugin marketplace add vcTaz/agent-toolkit
/plugin install agent-toolkit@agent-toolkit
```

From a shell the same two steps are `claude plugin marketplace add vcTaz/agent-toolkit` and
`claude plugin install agent-toolkit@agent-toolkit`. To take a branch other than the default,
append `@<branch>` to the marketplace source.

`.claude-plugin/marketplace.json` lists one plugin whose source is `./`, so **the plugin root
is the repository root**. An install copies the whole repository into Claude Code's plugin
cache, the shell scripts in `local/` and `tools/` included; what follows is about what
Claude Code **loads** from that copy, which is much less. `.claude-plugin/plugin.json` decides
it:

| Loaded | From | Named in a session |
|---|---|---|
| the eight subagents | `.claude/agents/*.md`, listed one file at a time | `agent-toolkit:critic`, `agent-toolkit:orchestrator`, … |
| the seven skills | `skills/`, Claude Code's default scan | `agent-toolkit:adversarial-review`, … |

Three things at the repository root are deliberately not loaded:

- **`AGENTS.md` and `CLAUDE.md`.** Claude Code does not load a `CLAUDE.md` from a plugin
  root. Each adapter carries its canonical body verbatim, so a plugin agent has its whole
  definition. What it lacks is the repository around it: the bodies cite paths such as
  `docs/concepts/orchestration.md` and `roles/critic.md`, which do not resolve from another
  project's working directory. That was already true of the `local/` route.
- **`agents/`.** Listing agents in the manifest replaces Claude Code's default `agents/`
  scan, so the orchestrator arrives through its adapter, with the same body, rather than as
  the canonical file, which has no `description`. `claude plugin list` prints a note that the
  default folder is ignored. That note is expected.
- **`workflows/`.** It is also Claude Code's default location for workflow scripts. Here it
  holds Markdown, which loads no workflow.

Nothing that Claude Code runs by itself is loaded either, and `tools/check.py` computes that
rather than this sentence asserting it. It refuses:

- in either manifest, any key that is not metadata or `agents`: hooks, MCP and LSP servers,
  commands, `strict: false`, a `skills` key;
- at the repository root, compared without case, every default plugin location that loads
  or runs something — `commands/`, `hooks/`, `output-styles/`, `themes/`, `monitors/`,
  `bin/`, `settings.json`, `.mcp.json`, `.lsp.json` — and `package.json`, which beside a
  lockfile makes every install run npm;
- anything but Markdown in `workflows/`;
- in a `SKILL.md`, a frontmatter key outside the Agent Skills fields (so `hooks`,
  `allowed-tools`, `context` and the rest), and in an adapter, a key outside the four the
  adapters use: `name`, `description`, `tools` and `model`;
- in either, any `!` directly beside a backtick. That covers inline shell, `` !`…` ``, and
  a ```` ```! ```` block, wherever they sit.

The first version of the check missed skills entirely: a hook in a skill's frontmatter and
inline shell in its body each ran in an installed session, measured at 2.1.282, with the check
passing. The second copied Claude Code's own patterns, and an independent validator got past it
with variations that still ran in an installed session: frontmatter indented as a whole, whose
hooks fired in the default permission mode, and a fence opened mid-line or inside a list item,
or a byte-order mark before the `!`, which ran in accept-edits mode. In the default mode Claude
Code still took each of those for shell and stopped at the permission prompt, as it did for the
original plant. So the rules are now **wider than Claude Code's parsing** rather than copies of
it. Claude Code reads frontmatter as YAML and this script has no YAML parser, so it does not
try to agree with one: every frontmatter line must be an unindented `key: value`, with no block
scalar, no nesting, no key twice and no value that YAML would read as more than its text, such
as one holding `: ` or starting with a quote. In that shape both see the same keys, and a name
the script accepts is the name YAML reads. And any `!` beside a backtick is refused, whatever
Claude Code would make of it. Both were set against the patterns in the 2.1.282 binary — its
frontmatter delimiter, which ends the block at the first `---` even mid-line, its YAML parser's
retry after turning leading tabs into spaces, and its two shell patterns. A later version that
parses more loosely could need them widened, and nothing here would notice.

In an **adapter**, the same validator found frontmatter hooks ignored for a plugin agent, and
inline shell in the body did not run in one probe, both at 2.1.282. The check refuses
both there anyway, so nothing rests on either observation. It also refuses a directory inside
`.claude/agents/`, which the plugin never reads, because the validator found that an agent
file there loads in this repository under its bare name, where nothing checked it.

It also fails when an adapter exists that `plugin.json` does not list, and when an adapter's
frontmatter `name` is not its file name. Claude Code registers an agent under that `name`, so
`validator.md` declaring `name: critic` left an installed plugin offering seven agents, with
no error anywhere. The flat shape is what makes that comparison mean something: the validator
also hid a second `name` under a nested key, inside a block scalar, and past a `---` that ends
the block mid-line, and each is now refused by shape before any name is compared.

**No `version` is set**, so the installed version is the commit the marketplace was fetched
at, and every commit to the default branch is a new version. Claude Code turns auto-update
off by default for a third-party marketplace, so an installed copy moves when its user
updates the marketplace and the plugin, or turns auto-update on. Setting a version would add
a second gate: nothing would move until someone bumps it. `claude plugin validate` warns
about the missing field and passes; `--strict` fails on that warning alone.

**Inside this repository with the plugin installed**, a session is offered both sets: the
project's `critic` and the plugin's `agent-toolkit:critic`, the second from the installed
plugin, which after a GitHub install is the cached copy at the installed commit. The plugin's
names are namespaced, so neither shadows the other.

**Cloud is not a tested route.** A marketplace declared in a repository's settings was
measured on 2026-09-20 to install nothing in a cloud session (`docs/host-integration.md`), and
this repository declares none. `cloud/README.md` records **Project settings → Plugins** as the
route Anthropic documents into a thread; it has not been tried with this marketplace, and it
was not re-read for this section. Distribution through claude.ai **Organization settings →
Plugins** requires the marketplace repository to be private or internal on github.com
(`plugin-marketplaces`, read 2026-09-24), so it does not apply while this repository is
public. In cloud, attach the repository itself; see `cloud/README.md`.

## Subagents

`.claude/agents/<role>.md` is the currently supported project-level mechanism. Files are
discovered by walking up from the working directory — every `.claude/agents/` between there
and the repository root is scanned, and where more than one of them defines the same `name`,
the definition closest to the working directory wins.

Project definitions outrank `~/.claude/agents/` and plugin-supplied agents, and are themselves
outranked. The order, highest first:

```text
1  managed settings          organisation-wide
2  --agents CLI flag         that session only
3  .claude/agents/           this repository        ← where the adapters live
4  ~/.claude/agents/         that machine's user
5  a plugin's agents/        where the plugin is enabled
```

So a session launched with `--agents`, or a machine under managed settings, can supply a
different `critic` under this repository's own name, and nothing here prevents it.

The frontmatter supports eighteen fields: `name`, `description`, `tools`, `disallowedTools`,
`model`, `permissionMode`, `maxTurns`, `skills`, `mcpServers`, `hooks`, `memory`,
`background`, `omitClaudeMd`, `effort`, `isolation`, `color`, `initialPrompt` and
`experimental`. They are listed rather than counted because a bare number rots without
anyone noticing.

An adapter here carries four of them and nothing else. Only the first two are required, and
omitting either of the others is a meaningful choice rather than an oversight — see the
asymmetry below:

```yaml
name: critic              # required
description: ...          # required — this is what Claude matches when deciding to delegate
tools: Read, Grep, Glob, Bash
model: opus
```

followed by a short block of Claude-specific operating notes, then the canonical role body,
synchronised verbatim between `<!-- canonical:begin -->` markers.

### Why the bodies are copied rather than referenced

A split-pane teammate uses the definition's body **in place of** its default system prompt
(an in-process teammate has it appended). An adapter whose body said only *"read
`roles/critic.md`"* would leave a split-pane teammate with a file path as its entire
instruction set. Self-contained bodies are the correct trade, and `tools/check.py` makes the
copy verifiable rather than trusted.

### Tool and model choices, and what they do not enforce

| Role | tools | model | Why |
|---|---|---|---|
| explorer | Read, Grep, Glob, Bash | `sonnet` | breadth over many files; cost matters |
| specialist | Read, Grep, Glob, Bash | `opus` | domain reasoning is the point |
| implementer | + Edit, Write, NotebookEdit | `inherit` | the only writer; right model depends on the task |
| critic | Read, Grep, Glob, Bash | `opus` | adversarial reasoning benefits most from capability |
| validator | Read, Grep, Glob, Bash | `inherit` | largely mechanical — it runs checks |
| synthesizer | Read, Grep, Glob | `inherit` | no Bash by design: it composes, it does not investigate |
| final-reviewer | Read, Grep, Glob, Bash | `opus` | judgement against requirements |

**Honest limitation:** `Bash` can write. The read-only constraint on Explorer, Specialist,
Critic, Validator and Final Reviewer is enforced by instruction, not by the tool list, because
those roles genuinely need to run tests and inspection commands. There is no read-only `Bash`
to ask for, and `tools` cannot narrow the one there is.

Three routes enforce it rather than instruct it, and this repository takes none of them by
default:

- A **`PreToolUse` hook** on `Bash`, declared in the `hooks` frontmatter field. This is the
  mechanism built for the job — the official documentation presents it as how to allow some
  operations of a tool while blocking others, and its worked example is a read-only agent
  whose hook script exits 2 to block a write.
- A **permission mode** that prompts on writes.
- The **Codex adapters**, where `sandbox_mode = "read-only"` is enforced by the harness.

The hook is left out on purpose. It has to be an executable script that runs before every
`Bash` call a role makes, which makes it a runtime the canonical layer can observe — exactly
what the host-layer bound in `AGENTS.md` excludes, on top of that file's standing rule against
adding a runtime without a concrete need. Instruction is the weaker constraint and it is the
one this repository can honestly claim. Adopt the hook in your own project if instruction is
not enough for you.

`model: inherit` means "use the lead's model". Pinning a specific model ID would rot; the
aliases and `inherit` will not.

**Omitting `model` is not the same as `inherit`.** Established from the official subagent
documentation on 2026-09-19, a page that carries no version number of its own: the model is
resolved as the per-invocation parameter, then the definition's frontmatter, then
`CLAUDE_CODE_SUBAGENT_MODEL`, then the main conversation's model. An omitted `model`
therefore resolves to that environment variable wherever it is set. Omitting `tools` is
unambiguous by comparison — the documentation states that a definition with no `tools`
inherits every tool available to subagents.

That asymmetry decides the orchestrator's frontmatter, in `.claude/agents/orchestrator.md`.
It sets **`model: inherit`** and omits **`tools`**. `inherit` is not a pin — it names no model
and only directs the agent to the main conversation's — and it is load-bearing rather than
decorative, because under omission `CLAUDE_CODE_SUBAGENT_MODEL` would outrank the host, and an
orchestrator running on a different model from the run it holds contradicts what that agent
is. `tools` needs no such handling, because omission is documented to inherit the available
subagent tool pool. The adapter records the same reasoning beside the frontmatter it governs.

## Agent Teams

**Experimental and off by default.** Enable with:

```json
{ "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" } }
```

in `settings.json`. Teams also require an interactive session — they do not form under `-p`.

### There is no team definition file, and this repository does not ship one

Claude Code's team config is generated at runtime under `~/.claude/teams/{session}/` and holds
live state. A project-level file such as `.claude/teams/teams.json` **is not recognised as
configuration**; it would be an ordinary file that nothing reads.

The official answer is to define reusable teammate roles as **subagent definitions** — which
is exactly what `.claude/agents/` already is. One adapter serves both purposes. Team
compositions therefore live in this document as spawn prompts, not as config.

### Spawning a teammate from a role

```text
Spawn a teammate using the critic agent type to attack the change in src/auth/.
Give it the diff and the requirement, not my reasoning about the fix.
```

Claude Code applies the definition's `tools`, its `model`, and its body. One field it does
**not** apply: `skills:`. Teammates load skills from project and user settings instead —
another reason `.claude/skills` must resolve, and it does.

## Team compositions

These mirror [`workflows/`](../../workflows/). Keep teams at three to five; coordination
overhead and token cost both scale, and three focused teammates usually beat five scattered
ones.

### Software engineering

```text
Spawn three teammates:
- an implementer working only on src/parser/ — no other files
- an implementer working only on src/writer/ — no other files
- a critic, which must not be either implementer

The implementers work in parallel because they own disjoint files. When both are
done, the critic attacks each change against its requirement. Then spawn a
validator — not the critic, not either implementer — to run the checks itself.
```

### Research

```text
Spawn three teammates to investigate <question>, one per area: <A>, <B>, <C>.
They must not discuss findings with each other until all three have reported —
comparing notes early makes them converge, and convergence looks like
corroboration. When all three are in, I will consolidate duplicates, then spawn
a critic and a synthesizer.
```

### Debugging with competing hypotheses

The strongest use of teams, and the reason is structural rather than about speed.

```text
<symptom>. Reproduce it first; do not proceed until you can.

Then spawn four teammates, each investigating a different hypothesis, each in its
own context. Each must state up front what would disprove its own theory. Once all
four have reported, have them attack each other's theories — the goal is
disproof, not defence. Report which hypotheses died and what killed them.
```

Sequential investigation anchors: once one theory is explored, everything after is framed by
it. Independent contexts do not share that anchor.

### Architecture

Mostly sequential — a design must exist before it can be attacked. Use subagents rather than a
team, unless several independent design questions are genuinely open at once.

## Subagents or teammates?

| | Subagents | Teammates |
|---|---|---|
| Communication | return a result to the caller | message each other directly |
| Coordination | the lead manages everything | shared task list, self-claiming |
| Cost | lower | each is a full session |
| Right for | focused work where only the result matters | work needing discussion and challenge |

For most of this toolkit's workflows, **subagents are sufficient**. Reach for a team when
teammates need to challenge each other — competing hypotheses, or a parallel review where the
reviewers should argue.

## Enforcing independence

Independence is a property of history (see `docs/concepts/independence.md`), and Claude Code
will not enforce it for you. In practice:

- **Name your agents.** A named subagent is addressable, and you can track what it touched.
- **Never delegate a review to the agent that did the work**, and never to a fork of its
  context. A fork carries the conclusion.
- **Control what the reviewer receives.** Fresh context is necessary and not sufficient — an
  agent told the conclusion is not independent of it. See
  [`bounded-context-handoff`](../../skills/bounded-context-handoff/SKILL.md).
- **Where you cannot achieve independence, say so in the output** rather than recording a
  self-review as a review. A fresh context of the same identity is a disclosed degraded
  self-check and satisfies no criterion that requires independence; where completion requires
  an independent review and no independent identity exists, the honest terminal state is
  `EXHAUSTED`. See [`independence.md`](../concepts/independence.md).

## Known volatility

| Feature | Status |
|---|---|
| `.claude/agents/` subagents | stable, officially documented |
| `.claude/skills/` project skills | stable |
| Agent Teams | **experimental**, flag-gated, documented limitations around resumption and shutdown |
| `.claude/commands/` | legacy — skills supersede it; this repository ships none |
| The plugin in `.claude-plugin/` | documented; install verified locally at 2.1.282, not tried in cloud. `claude plugin details` under-counts its agents |

Nothing canonical in this repository depends on Agent Teams. If it changed tomorrow, the roles,
skills and workflows would be unaffected and only this file would need editing.

## What was checked, and how

`AGENTS.md` asks whether there is evidence outside the models, and that a claim with no check
for its kind be labelled rather than asserted. Two labels appear below and they are not
interchangeable. **Verified** means the behaviour was run here and observed, at the version
and date given. **Documented** means the official documentation states it and was read on the
date given — a primary source, but not a run.

| Claim | Status |
|---|---|
| `claude --version` reports 2.1.278 | **verified** — run 2026-09-21 |
| `.claude/agents/*.md` is discovered and all eight adapters are offered | **verified** — 2.1.278, 2026-09-21 |
| `tools:` is applied — Synthesizer is offered as `Read, Grep, Glob`, with no `Bash` | **verified** — 2.1.278, 2026-09-21 |
| The `.claude/skills/` entry symlinks are followed and all six skills **this repository carried at the time** are discovered | **verified** — cloud session 2026-09-20, re-run at 2.1.278 on 2026-09-21, when there were six |
| The same holds for the seventh, `checkable-findings`, added 2026-09-21 | **verified** — 2.1.278, fresh cloud session 2026-09-22, against a temporary validation repository whose `main` was exactly `2f68916d21c21ced2a88d18a5f6f17349a2e1eb2`. Seven skills discovered, seven entries resolved, invoked through the Skill mechanism, and the body established as active instructions by three body-only answers with no file read in the tool log |
| Discovery scans every `.claude/agents/` between the working directory and the repository root | **verified** — 2.1.278, 2026-09-21, nested fixture |
| On a name clash the definition closest to the working directory wins | **verified** — 2.1.278, 2026-09-21, same fixture |
| `--agents` outranks a project definition of the same name | **verified** — 2.1.278, 2026-09-21, against an unflagged control run |
| The tools and model table above matches the eight adapters | **verified** — read off the adapter frontmatter, 2026-09-21 |
| The rest of the precedence order — managed settings above `--agents`, then the user directory, then plugin agents | **documented** — `sub-agents`, 2026-09-21 |
| The eighteen frontmatter fields | **documented** — `sub-agents` field table, counted 2026-09-21 |
| A `PreToolUse` hook in the `hooks` field is the route to a read-only `Bash` | **documented** — `sub-agents`, 2026-09-21 |
| A `<skill-name>` entry may be a symlink, with `SKILL.md` read from the target; a symlinked *container* is not documented | **documented** — `skills`, 2026-09-21 |
| `model` resolution order, and that omitting `model` is not `inherit` | **documented** — `sub-agents`, 2026-09-19 |
| A split-pane teammate replaces its system prompt; an in-process one has the body appended | **documented** — `agent-teams`, 2026-09-21 |
| `skills:` is not applied to teammates | **documented** — `agent-teams`, 2026-09-21 |
| Agent Teams is experimental, env-gated and interactive-only | **documented** — `agent-teams`, 2026-09-21 |
| No project-level team config file is read | **documented** — `agent-teams`, 2026-09-21 |
| The Windows `core.symlinks` caveat | **unchecked** — see below |
| `claude plugin validate .` passes on the marketplace with one warning, the missing `version` | **verified** — 2.1.282, 2026-09-24. `claude plugin validate .claude-plugin/plugin.json` passes with four: the version, `CLAUDE.md` at the root, and two about files in `agents/`, which it scans although the manifest replaces that folder |
| A directory in the manifest's `agents` field is rejected (`agents: Invalid input`) | **verified** — 2.1.282, 2026-09-24 |
| Once installed, a session's init record lists all eight `agent-toolkit:` subagents and all seven `agent-toolkit:` skills | **verified** — 2.1.282, 2026-09-24, nested `claude -p` with an isolated config directory: installed from a local-directory marketplace, and again from GitHub, where the marketplace was fetched at `44fbd786ac60967e96fc4517ebba282e789b18b0` and the plugin copied into the plugin cache under that version |
| From that GitHub install, a plugin skill and a plugin agent are usable, not only listed | **verified** — same run. `agent-toolkit:checkable-findings` was invoked through the Skill tool and its body injected with the plugin cache as its base directory; `agent-toolkit:synthesizer` was dispatched through the Agent tool and answered |
| The eight agents load from `.claude/agents/`, the default `agents/` folder is skipped, and no plugin workflow loads | **verified** — 2.1.282, 2026-09-24, from the debug log of the local-directory run |
| Inside this repository with the plugin installed, both `critic` and `agent-toolkit:critic` are offered | **verified** — 2.1.282, 2026-09-24, init record |
| `tools:` carries over — `agent-toolkit:synthesizer` is offered as `Read, Grep, Glob` | **verified by read-back** — 2.1.282, 2026-09-24. The model quoted its Agent tool description, so this is the list offered, not a test of enforcement |
| `claude plugin details` reports **Agents (0)** for this plugin | **verified** — 2.1.282, 2026-09-24. It does not count agents listed by path, while a session loads them; the init record is the evidence, not the inventory |
| A hook in a skill's frontmatter, and inline shell in its body, each run in a session that installed the plugin | **verified** — 2.1.282, 2026-09-24, against the first version of the manifests at `44fbd786ac60967e96fc4517ebba282e789b18b0`, where `tools/check.py` passed both. It now refuses both |
| An adapter whose frontmatter `name` clashes with another's costs the installed plugin that agent, silently | **verified** — 2.1.282, 2026-09-24, same commit: seven agents in the init record. `tools/check.py` now refuses the mismatch |
| Variations of both got past the repaired check at `ce8796bd61fc9b32e6775440dbdc6818892aaab7` and still ran: frontmatter indented by spaces or by tabs, whose hooks fired in the default permission mode; a shell fence opened mid-line or in a list item, and a U+FEFF before inline shell, which ran in accept-edits mode and stopped at the permission prompt in the default one | **verified** — 2.1.282, 2026-09-24, by an independent validator against an installed plugin. `tools/check.py` now refuses each by shape, and `tools/test.sh` plants each |
| At that commit a second `name` under a nested key, inside a block scalar, or past a `---` that ends the block mid-line cost the installed plugin an agent; a duplicate top-level `name` did not | **verified** — same round, seven agents against eight. All four are now refused by shape |
| Hooks in an adapter's frontmatter are ignored for a plugin agent | **verified** — same round. Refused anyway |
| Inline shell in a plugin agent's body does not run | **observed once** — 2.1.282, 2026-09-24, one probe in accept-edits mode; not established. Refused anyway |
| An agent file in a subdirectory of `.claude/agents/` loads in the project under its bare name | **verified** — same round. A directory there is now refused |
| The plugin in a cloud session | **not tried** |

Three limits on this table. The **documented** rows describe intent; only the verified rows
establish that this repository's own layout is discovered. The Agent Teams page states its own
baseline — *"This page describes agent teams as of v2.1.178"* — so agreeing with it is not
evidence about 2.1.278 specifically. And exactly one step of the precedence order was run —
`--agents` over a project definition of the same name. Managed settings, `~/.claude/agents/`
and plugin agents were read rather than run; there is no managed installation or user
directory here to test the rest against, and this repository's own plugin cannot test it
either, because its agents are namespaced and never share a name with a project definition.

The Windows row is unchecked in both senses. `core.symlinks` is a Git behaviour rather than a
Claude Code one, the Claude Code documentation does not address it, and no Windows checkout
has been made here. It is carried because a Windows clone that silently turns the skill
entries into text files is a real failure worth warning about, not because it was confirmed.

The verified rows were run in a cloud session with this repository as the only project
repository. Session shape can change what a repository's configuration reaches, so a result
established in one shape should not be assumed to hold in another.

### What was deliberately not carried over

The precedence order, the field set, the `PreToolUse` route and this section were recovered
from an abandoned branch, `claude/project-thread-lkr5gf`, whose copy of this file predates the
skills-layout correction. Two of its claims are superseded and were **not** reapplied: that
`.claude/skills` is a container symlink to `skills/` — see *The skills directory is a real
directory of symlinks* above, which `tools/check.py` enforces — and its header, which dated
the whole file to a documentation read, where the measured version pin at the top stands.
Anyone mining that branch again should reject the same two.
