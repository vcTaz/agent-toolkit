# Cloud smoke test

Paste everything in the fenced block below as the **first message** of a new thread in a
project that has this repository attached.

It is **read-only**. It writes no files, installs nothing, and runs no git command that
changes state. If any step would require a write, the expected answer is for Claude to say
so rather than do it.

---

```text
Run a read-only capability report on this session, then a short live check. Do not create,
modify, delete, move, or stage any file, and do not run any git command that changes state
(no add/commit/push/checkout/stash). If a step needs a write, skip it and say why.

PART 1 — REPORT

Answer each item. If something is absent, say "none" — do not guess or fill in from memory.

1. INSTRUCTIONS
   - List every CLAUDE.md and AGENTS.md currently loaded, with the repository each came from.
   - State whether this project has one repository or several, and name them.
   - Quote the first heading line of this toolkit's AGENTS.md to prove it is really loaded.

2. SKILLS
   - List every skill you can invoke, grouped by origin: this toolkit, a plugin,
     the claude.ai account, another repository.
   - Confirm these seven toolkit skills are present:
     adversarial-review, bounded-context-handoff, checkable-findings,
     evidence-backed-synthesis, evidence-verification, final-verification,
     independent-validation
   - Confirm NO third-party skills arrive from this repository. wrangler,
     durable-objects, cloudflare, brandkit, minimalist-ui and orca-cli must NOT be
     present unless a pack repository is also attached to the project, or they come
     from the account. This repository carries seven skills and no third-party content.
   - Report the TOTAL count of skills whose SKILL.md resolves under this repository.
   - For adversarial-review, report the path you would load its SKILL.md from, and whether
     that path is a symlink.

3. AGENTS
   - List every subagent type available to you.
   - Confirm whether these eight are present: explorer, specialist, implementer, critic,
     validator, synthesizer, final-reviewer, orchestrator
   - For each, say whether it came from this repository, from a plugin, or is built in.

4. COMMANDS
   - List the custom slash commands available, and where each came from.

5. PLUGINS
   - List every plugin loaded, with its version and marketplace, and for each say
     whether it came from the account, from Project settings, or from somewhere else.
   - This repository declares NO plugins in its settings. Do not expect any from it. It
     is itself packaged as the plugin `agent-toolkit`; if that appears, say whether it came
     from the account or from Project settings. A plugin that arrived because a
     repository's settings declared it would contradict the 2026-09-20 measurement, and is
     the interesting result.

6. MCP
   - List every MCP tool available, and for each say whether it is a claude.ai connector
     or came from a repository .mcp.json.
   - State whether any stdio MCP server is present AND whether its tools actually work.
     Do not assume either way: Anthropic's documentation does not say stdio servers are
     blocked in cloud sessions, and the ecc plugin ships a .mcp.json declaring five of
     them. This question is open, and your answer is the evidence. If any stdio tool is
     listed, call one read-only tool from it and report whether it responded.

7. PERMISSIONS
   - State whether permission deny rules from a repository's .claude/settings.json are in
     effect in this thread, and explain why given the one-repo/several-repo distinction.

8. BINARIES — run exactly this, nothing else:
   for t in git gh jq yq rg node python3 uv tmux; do
     printf '%-8s %s\n' "$t" "$(command -v $t 2>/dev/null || echo MISSING)"
   done

PART 2 — LIVE CHECK

Do one harmless thing per category that Part 1 found available. Skip any category that
reported "none" and say you skipped it.

a. SKILL — invoke `adversarial-review` against this throwaway claim, and give only its
   verdict plus one blocking issue:
   "This smoke test proves the toolkit works in every cloud configuration."
   (A correct critic should note that one passing session does not establish that.)

b. AGENT — dispatch the `explorer` subagent, read-only, to report the top-level directory
   layout of this toolkit repository in under 10 lines.

c. PLUGIN — name one capability a loaded plugin provides that is not otherwise available.
   Do not run it.

d. MCP — name one connector tool and the single call you would make to verify it works.
   Do not call it.

e. COMMAND — name one available custom command and what it would do. Do not run it.

PART 3 — VERDICT

Finish with a table: category | expected | observed | PASS/FAIL, one row per category
above, then one sentence naming the single biggest gap between this session and a full
local setup. Be blunt; a clean pass on everything is not the expected result.
```

---

## What a correct result looks like

| Category | Expected in a project with this repo attached |
|---|---|
| Instructions | This repo's `CLAUDE.md` → `AGENTS.md`, plus your app repo's, one per repository |
| Skills | **6** from this repo and no more, plus ~181 `ecc:*`, plus account skills. A pack repository, if attached, adds its own 13 |
| Agents | The 7 roles and the orchestrator — **8** from this repo — plus ~38 `ecc:*` |
| Commands | ~79 `ecc:*`; this repo ships none of its own |
| Plugins | **None from this repository.** It declares none, and repository-declared plugins were measured on 2026-09-20 not to be delivered. Whatever the account or Project settings provide |
| MCP | claude.ai connectors certainly. Whether the ecc plugin's five stdio servers run is **genuinely unknown** — that is the point of asking |
| Permissions | Applied in a one-repo project; **not applied** in a multi-repo project |
| Binaries | All nine present, none MISSING |

## Interpreting failures

| Symptom | Likely cause |
|---|---|
| All 7 skills absent, agents present | `.claude/skills/` entry symlinks not followed, despite being the documented form and despite two fresh-session pack tests following them on 2026-09-20. Report it: it would contradict a measured result |
| Third-party skills present from this repo | `vendor/` has come back, or an entry points outside `skills/`. `tools/test.sh` fails on a reintroduced `vendor/`; `tools/check.py` catches the stray entry but not the directory, so run both |
| Both absent | The repository is not attached to the project, or the Claude GitHub App is not installed on it |
| Plugins absent | Expected for anything this repository could declare — it declares none, and repository-declared plugins were measured not to arrive. For an account or Project-settings plugin: no network access to the marketplace, or the marketplace source is unreachable |
| Deny rules absent | Expected in a multi-repo project. Re-declare them in **Project settings** |
| A binary MISSING | The environment image changed; add it to the setup script |

Record the result. This file documents an **expectation**, and running it is what turns any
row into an outcome. Some rows already rest on a measurement and say so — skill-entry
symlinks being followed, deny rules being enforced, repository-declared plugins not being
delivered, and both packs delivering in a fresh session, all measured in Anthropic's hosted
cloud environment on 2026-09-19 and 2026-09-20. Every other row is still derived from the
documentation and from local inspection. A measurement taken then, there, is not a claim
about another environment or a later version, so re-running this after an environment change
is worth doing even for the rows that carry a date.
