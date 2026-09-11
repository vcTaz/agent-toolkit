# Documentation authority

Which file wins when two disagree.

## The chain

```text
1.  AGENTS.md                           project invariants and contribution rules
            ↓  may constrain, never redefine
2.  roles/  skills/  workflows/         CANONICAL — the only place a concept is DEFINED
    docs/concepts/                      the reasoning behind them
            ↓  may add platform mechanics, never redefine
3.  .claude/agents/  .codex/agents/     ADAPTERS — mechanics only
    .claude/skills   .agents/skills     LINKS — no content of their own
            ↓  may explain, never define
4.  docs/platforms/*.md                 USAGE — how to drive the above on one harness
```

**Higher wins.** Specifically:

- If an **adapter** and a **canonical role** disagree, the role wins and **the adapter is
  defective**. Fix `roles/`, then run `python3 tools/check.py --sync`.
- If a **platform document** and a **canonical file** disagree, the canonical file wins and
  the platform document is stale.
- If a **concept document** and a **role** disagree, they are describing the same thing at two
  altitudes and one of them is wrong. Decide which, fix it, and fix the other to match.
- If **`AGENTS.md`** and anything below it disagree about an invariant, `AGENTS.md` wins. It
  does not define roles, so it should rarely be in a position to conflict.

## What each layer may contain

| Layer | May contain | May never contain |
|---|---|---|
| `AGENTS.md` | repository map, invariants, contribution rules, pointers | role definitions, platform mechanics, long prose |
| `roles/` `skills/` `workflows/` | the definition of a concept | anything requiring a specific harness, vendor, model or language |
| `docs/concepts/` | why the canonical layer is shaped this way | a second, competing definition |
| `.claude/` `.codex/` | identifiers, tool limits, model/effort, permissions, a few operating notes, a marked verbatim copy | a reworded version of a role's responsibilities |
| `docs/platforms/` | how to use the above on one harness, with its limitations | any definition |

## The source-of-truth rule

> **One conceptual definition; multiple platform adapters.**

There is exactly one place each concept is defined. Everything else points at it or copies it
mechanically.

### The one accepted duplication

Adapter bodies copy the canonical role body verbatim, because a Claude Code split-pane
teammate uses a definition's body **in place of** its system prompt — a pointer would leave it
with a file path as its entire instruction set.

| | |
|---|---|
| **What is duplicated** | the body of each `roles/*.md`, into two adapters |
| **Why** | adapter bodies must be self-contained to function as system prompts |
| **Which is authoritative** | `roles/*.md`, always |
| **How drift is detected** | `tools/check.py` compares the embedded text and its recorded SHA-256 against the canonical file |
| **How it is repaired** | `python3 tools/check.py --sync` |

Both directions are caught: editing a role without syncing, and hand-editing an adapter body.
Both are proven to fail rather than assumed to.

Nothing else in this repository is duplicated. Skills are linked, not copied. Workflows and
concepts are referenced, not restated.

## Changing things safely

**A role:** edit `roles/<id>.md` → `python3 tools/check.py --sync` → `python3 tools/check.py`.
If you changed what the role *is* rather than how it is worded, check the workflows that name
it and the concept documents that reference it.

**A skill:** edit `skills/<name>/SKILL.md`. Nothing to sync — both harnesses read it directly.

**An adapter:** edit only the frontmatter and the operating notes above the marker. **Never
edit inside a `canonical:begin` / `canonical:end` block**, or the `developer_instructions`
string in a TOML adapter. If the canonical body is wrong, fix the role.

**A platform mechanism changed:** edit `docs/platforms/<harness>.md` and the adapter
frontmatter. The canonical layer should need no change — if it does, the canonical layer had
absorbed a platform assumption, which is a defect worth fixing properly.

## Avoiding circularity

Each layer points **downward or sideways**, never back up as an authority:

- `AGENTS.md` points at the canonical layer. The canonical layer does not cite `AGENTS.md`
  as its justification.
- Roles reference concept documents for reasoning; concept documents do not define roles.
- Platform documents reference canonical files; canonical files never reference a platform
  document.

Role files reference other documents by repository-root path in backticks rather than by
relative link, because their bodies are copied into other directories where a relative link
would break — or, worse, resolve to a different file. `tools/check.py` enforces the
prohibition on relative links; the backtick form itself is a convention, not a check.
