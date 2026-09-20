# CLAUDE.md

@AGENTS.md

`AGENTS.md` above is the primary instruction file for this repository, imported here because
Claude Code does not read it natively. Everything in it applies.

## Claude Code specifics

- **Roles** are available as subagents in `.claude/agents/` — `explorer`, `specialist`,
  `implementer`, `critic`, `validator`, `synthesizer`, `final-reviewer`. The same definitions
  work as Agent Teams teammate types, where enabled — Agent Teams is experimental and off by
  default.
- **Skills** are discovered through `.claude/skills/`, which is a **real directory whose
  entries are symlinks** — not a symlink to `skills/`. Only a `<skill-name>` entry is
  documented as symlinkable, so the container must stay a real directory; `tools/check.py`
  fails if either shape drifts. `.agents/skills` is the container symlink, for Codex.
- **`docs/platforms/claude-code.md`** has the team compositions, the subagent-versus-teammate
  decision, and the honest limitations — including that `Bash` is not read-only-enforceable,
  so the read-only roles rely on instruction rather than sandboxing.

## Before changing a role

Edit `roles/<id>.md` — never `.claude/agents/<id>.md`. The adapter's body is a synchronised
copy; hand-editing it is caught by `tools/check.py` and will be overwritten by `--sync`.

```bash
python3 tools/check.py --sync    # regenerate adapter bodies from roles/
python3 tools/check.py           # structure, conformance, drift, links
```

If this file, `AGENTS.md`, or a canonical file disagree, follow `docs/authority.md` and report
the discrepancy.
