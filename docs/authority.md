# Documentation authority

Which file wins when two disagree.

## The chain

```text
1.  AGENTS.md                           project invariants and contribution rules
    docs/concepts/orchestration.md      the invariants' full catalogue, O1-O30
            ↓  may constrain, never redefine
2.  roles/  skills/  workflows/         CANONICAL and portable
    agents/                             CANONICAL and host-specific
    docs/concepts/*                     the reasoning behind them
            ↓  may add platform mechanics, never redefine
3.  .claude/agents/  .codex/agents/     ADAPTERS — mechanics only
    .claude/skills   .agents/skills     LINKS — no content of their own
            ↓  may explain, never define
4.  docs/platforms/*.md                 USAGE — how to drive the above on one harness

    manifest/  packs/  profile/        HOST — delivery, alongside the chain and
    local/  cloud/  .claude-plugin/           outside it; defines nothing.
    .claude/settings.json                     tools/check.py enforces this set
```

`docs/concepts/orchestration.md` sits at level 1 rather than level 2 for a derived reason:
`AGENTS.md` states the invariants as "standing constraints, not suggestions" and names that
file as their full catalogue. The O-numbers are therefore invariant material, and nothing
below may contradict them. Every other concept document is level 2 — reasoning about the
canonical layer, not a competing definition of it.

The `HOST` layer is not a rung. It defines no concept, and `AGENTS.md` forbids anything in
`roles/`, `agents/`, `skills/` or `workflows/` from referencing it, so it can never be in a
position to win or lose a disagreement about meaning. Remove it and the canonical layer is
unchanged and still correct.

**What `check_host_invariant()` actually rejects**, so a contributor whose edit is refused can
see why without reading the source. Two patterns, matched against the text of every file in
`roles/`, `agents/`, `skills/` and `workflows/`:

| | |
|---|---|
| directory prefixes | `local/` `cloud/` `manifest/` `packs/` `profile/` `vendor/` `.claude-plugin/` |
| bare filenames, wherever they appear | `settings.json` `settings.local.json` `settings.fragment.json` `bootstrap.sh` `doctor.sh` `setup.sh` |

`vendor/` is in the set although this repository no longer has one: it is what stops a
reintroduced copy being referenced from the canonical layer. The filenames are matched on
their own, not only under a host directory, so naming `doctor.sh` in a role is rejected
however it is written. Paths are matched rather than words, because `roles/README.md` uses
the word "vendor" to state the portability rule itself.

**Higher wins.** Specifically:

- If an **adapter** and its **canonical definition** disagree, the definition wins and **the
  adapter is defective** — for a role in `roles/` and for an agent in `agents/` alike. Fix the
  canonical file, then run `python3 tools/check.py --sync`.
- **A harness working differently is not permission to redefine.** If the platform cannot do
  what a canonical definition requires, that is a limitation to state, not a semantics to
  rewrite. The precedent is in `docs/platforms/claude-code.md`: Claude Code has no read-only
  Bash, and that is recorded as an honest limitation of the adapters rather than by weakening
  the roles that depend on it.
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
| `agents/` | the definition of an agent that is not a role, including the harness mechanics it cannot be written without | a definition that would satisfy the three-part role bar; a reference to the `HOST` layer |
| `manifest/` `packs/` `profile/` `local/` `cloud/` `.claude/settings.json` | delivery and installation — shell and JSON data | any definition, and anything the canonical layer is expected to read |
| `.claude-plugin/` | delivery — the two JSON manifests that make the repository root a Claude Code plugin | any definition; any component that runs, which `tools/check.py` refuses |
| `docs/concepts/` | why the canonical layer is shaped this way | a second, competing definition |
| `.claude/` `.codex/` | identifiers, tool limits, model/effort, permissions, a few operating notes, a marked verbatim copy | a reworded version of a role's responsibilities |
| `docs/platforms/` | how to use the above on one harness, with its limitations | any definition |

## A worked case: the orchestrator

The host agent is the case where every layer has something to say, so it is worth spelling
out. Five things could disagree about what the orchestrator is:

| # | Source | Authoritative for | May never |
|---|---|---|---|
| 1 | `docs/concepts/orchestration.md` | what the rules of a run **are** — O1 to O30 | be contradicted by anything below |
| 2 | `agents/orchestrator.md` | what the orchestrator **is**: its decisions, its state, its exclusions | contradict a principle it cites |
| 3 | `.claude/agents/orchestrator.md`, outside the markers | this harness's `name`, `description`, `tools`, `model` and operating notes | restate a responsibility in its own words |
| 4 | `.claude/agents/orchestrator.md`, between the markers | nothing — it is a mechanical copy | differ from its source by one byte |
| 5 | `docs/platforms/claude-code.md` | how to drive it here, and what this harness cannot do | define any of the above |

Read downwards. **1 beats 2 beats 3 beats 5, and 4 is not a party to the argument** — a
difference there is drift, which `tools/check.py` reports and `--sync` repairs.

Two consequences worth stating plainly:

- **An adapter may not redefine orchestrator semantics because the harness works
  differently.** If Claude Code makes something awkward, the adapter's operating notes say so
  and `docs/platforms/claude-code.md` records the limitation. Neither may quietly substitute
  a looser rule. An adapter whose notes said the orchestrator may judge a run finished would
  be defective, because **O18** says readiness is computed, and no harness fact changes that.
- **`agents/orchestrator.md` carrying Claude Code mechanics does not make it an adapter.** It
  is canonical and host-specific: authoritative about the agent, and making no claim that it
  survives a move to another harness. That is why no Codex adapter is generated from it — see
  `agents/README.md`.

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
