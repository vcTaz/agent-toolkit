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
   - Confirm these six toolkit skills are present:
     adversarial-review, bounded-context-handoff, evidence-backed-synthesis,
     evidence-verification, final-verification, independent-validation
   - Confirm these vendored skills are present (they are committed under vendor/ and
     linked from .claude/skills/): wrangler, durable-objects, cloudflare, brandkit,
     minimalist-ui, high-end-visual-design, orca-cli
   - Report the TOTAL count of skills whose SKILL.md resolves under this repository.
   - For adversarial-review, report the path you would load its SKILL.md from, and whether
     that path is a symlink.

3. AGENTS
   - List every subagent type available to you.
   - Confirm whether these seven are present: explorer, specialist, implementer, critic,
     validator, synthesizer, final-reviewer
   - For each, say whether it came from this repository, from a plugin, or is built in.

4. COMMANDS
   - List the custom slash commands available, and where each came from.

5. PLUGINS
   - List every plugin loaded, with its version and marketplace.
   - Confirm whether ecc, superpowers and ui-ux-pro-max loaded.
   - If any plugin declared in .claude/settings.json did NOT load, say which and why.

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
| Skills | 6 toolkit + **27 vendored** = 33 from this repo, plus ~181 `ecc:*`, plus account skills |
| Agents | The 7 roles, plus ~38 `ecc:*` |
| Commands | ~79 `ecc:*`; this repo ships none of its own |
| Plugins | `ecc`, `superpowers`, `ui-ux-pro-max` |
| MCP | claude.ai connectors certainly. Whether the ecc plugin's five stdio servers run is **genuinely unknown** — that is the point of asking |
| Permissions | Applied in a one-repo project; **not applied** in a multi-repo project |
| Binaries | All nine present, none MISSING |

## Interpreting failures

| Symptom | Likely cause |
|---|---|
| All 33 skills absent, agents present | `.claude/skills/` entry symlinks not followed, despite being the documented form. Fall back: replace the symlinks with real directories (`tools/vendor-sync.py` plus a copy step) |
| Vendored 27 absent, toolkit 6 present | Impossible by construction — both use the identical symlink mechanism. If seen, report it |
| Both absent | The repository is not attached to the project, or the Claude GitHub App is not installed on it |
| Plugins absent | No network access to the marketplace, or the marketplace source is unreachable |
| Deny rules absent | Expected in a multi-repo project. Re-declare them in **Project settings** |
| A binary MISSING | The environment image changed; add it to the setup script |

Record the result. This file documents an expectation, not a verified outcome — until a
thread has actually run it, cloud behaviour here is **statically validated only**.
