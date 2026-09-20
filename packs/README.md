# packs/

Specifications for **optional** skill packs. No third-party content lives here — each file is
a pin, a licence declaration and a skill mapping, and `tools/vendor-sync.py` builds a pack
repository from it.

| Spec | Pack repository | Skills | Licence | Upstream |
|---|---|---:|---|---|
| `cloudflare.json` | `vcTaz/claude-skills-cloudflare` | 13 | Apache-2.0 | `cloudflare/skills` |
| `frontend.json` | `vcTaz/claude-skills-frontend` | 13 | MIT | `Leonxlnx/taste-skill` |

A pack is attached to a Project that wants it, and to no other. That is the whole point of the
tier: the context cost of a skill's description is paid by the Projects that use it, not by
every reader of this repository.

**Delivery is verified, not assumed.** On 2026-09-20 both packs were tested in separate fresh
cloud sessions with this repository absent: 13 of 13 skills discovered in each, every entry a
resolving symlink, and a representative skill — `wrangler` and `minimalist-ui` — invoked
through the Skill tool with its body injected from the pack's own `.claude/skills` base
directory. That is harness delivery rather than filesystem readability, and it is what
licensed removing the committed copies from this repository.

## Building a pack

```bash
python3 tools/vendor-sync.py --pack cloudflare --into ../claude-skills-cloudflare
python3 tools/vendor-sync.py --verify-pack --into ../claude-skills-cloudflare
```

The build fetches the pinned upstream revision, extracts only the mapped skills, copies the
upstream `LICENSE`, writes `PROVENANCE.json` and a copy of the spec as `PACK.json`, and lays
out the harness entry points. It asks for a tarball first and falls back to a shallow
`git fetch` plus `git archive`, printing which route it took — in the environment this was
built in the tarball host answers 403 and the fallback is the path that actually runs.

`--verify-pack` is offline and works in both directions. It re-hashes and re-reads the mode
of every file under a declared skill, and of `LICENSE`, `NOTICE`, `PACK.json` and
`README.md`, comparing both against `PROVENANCE.json`. A file whose bytes match but whose
mode does not is reported as MODE DRIFT rather than passing. `PROVENANCE.json` is the one
file a pack cannot self-verify, since it cannot hash itself; a tampered one is caught by its
`ref` disagreeing with `PACK.json`.

The other direction is that the pack may contain **nothing else**: an undeclared skill
directory, a loose file under `skills/`, an entry under `.claude/` or `.agents/` that is not
the skills link, or any extra file at the pack root is rejected. Both directions were added
on 2026-09-20 and 2026-09-21, and each closed a measured hole: until the first, a 14th skill
with its own entry verified clean; until the second, so did a `.claude/agents/<name>.md`, a
root `CLAUDE.md`, and a `LICENSE` whose text had been replaced with "All rights reserved".

A pack built before whole-pack provenance existed has no `files` key and **fails** with a
message saying to rebuild it — rather than passing while unable to check those files.

## What a built pack looks like, and why

```text
skills/<name>/                 content, materialised from the pinned commit
.claude/skills/<name>       →  ../../skills/<name>
.agents/skills              →  ../skills
LICENSE                        fetched from upstream, not trusted from a metadata field
PROVENANCE.json                upstream repo, exact ref, licence, per-file sha256 + mode
PACK.json                      a copy of this spec, so the pack verifies on its own
README.md                      generated: what this is and how to rebuild it
```

**The `.claude/skills/` entries are load-bearing.** A repository attached to a Claude Project
delivers skills only through them. Verified on 2026-09-20 by treeless clone at upstream HEAD:
`cloudflare/skills`, `Leonxlnx/taste-skill` and `stablyai/orca` ship **zero** such entries
between them, which is why attaching an upstream directly was ruled out. A pack that shipped
only `skills/<name>/SKILL.md` would attach and deliver nothing, with no error and no log line.

The shape mirrors this repository's own: a real `.claude/skills/` directory of per-skill
symlinks, because only a `<skill-name>` entry is documented as symlinkable, and a single
`.agents/skills` container symlink for Codex.

## Pins are held, not tracked

Each `upstream.ref` is the revision that matches what was vendored, and `refNote` records why.
Moving a pin is a deliberate act with its own evidence — the cloudflare pin is currently one
skill behind upstream HEAD on purpose, and the spec says so.

## What this tier gives up

Honest limits, both recorded here rather than discovered later:

- **A spec is a promise; only a built pack is an artifact.** If a pack repository is deleted
  or never rebuilt after a pin moves, the content exists nowhere this repository controls.
  That is the price of the split, and it is why both packs were built, pushed and tested
  before the committed copies were removed from here.
- **Integrity is not identity.** `PROVENANCE.json` proves a pack matches what was recorded at
  build time. It does not prove the recorded tree matches upstream. That was equally true of
  the committed copies, and `tools/vendor-sync.py` says so in the same words.
