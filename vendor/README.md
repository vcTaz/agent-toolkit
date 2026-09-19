# vendor/

Third-party skills, committed verbatim from a pinned upstream commit. **Nothing here is
authored in this repository.**

## Why this exists

Claude Projects load skills from a cloned repository's `.claude/skills/`, or from skills
enabled on a claude.ai account. There is no supported mechanism by which a *reference*
makes a skill available to a cloud session: a manifest entry is documentation, not
delivery. Writing into `~/.claude` from a setup script is not documented as supported
either, and cloud sessions are documented as **not reading `~/.claude/skills/`** at all.

Committing the content is therefore the only supported path for these 27 skills. Every
source permits it:

| Source | License | Skills | Pin |
|---|---|---|---|
| [cloudflare/skills](https://github.com/cloudflare/skills) | Apache-2.0 | 13 | `f96bff75` |
| [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | MIT | 13 | `e79ca9ec` |
| [stablyai/orca](https://github.com/stablyai/orca) | MIT | 1 | `fb322046` |

Each licence was verified by fetching the upstream `LICENSE` file, not by trusting a
metadata field — GitHub's own licence detection returns *none* for all three.

Every source's `LICENSE` is copied into its directory, as Apache-2.0 §4 and the MIT licence
both require. `cloudflare/skills` has no `NOTICE` file, so there is no NOTICE obligation.

## Do not edit anything here

Change `vendor/sources.json` and re-run the sync. A hand edit is detected as content drift
and silently lost on the next sync.

```bash
python3 tools/vendor-sync.py              # verify against the pins (offline)
python3 tools/vendor-sync.py --sync       # re-materialise from the pins (network)
python3 tools/vendor-sync.py --update <source>   # move a pin to upstream HEAD
```

`PROVENANCE.json` in each directory records the upstream repo, the exact commit, the
licence, the upstream path of every skill, and a sha256 for every file. Verification is
offline and exact.

## How these reach a session

`.claude/skills/<name>` is a symlink to `vendor/<source>/<name>`. Claude Code documents
exactly this: *"a `<skill-name>` entry in the enterprise, personal, or project location can
be a symlink to a directory elsewhere on disk."* The container `.claude/skills/` is a real
directory, because only the entries are documented as symlinkable.

## Pins are deliberately not HEAD

Each pin is the revision that matches what was installed locally, verified file-by-file —
27 of 27 vendored skills are byte-identical to the local copies. The point is that a cloud
session sees what the machine sees. `--update` moves a pin; nothing moves on its own.

For `orca-cli` the matching revision was found by walking the file's commit history, since
upstream HEAD had moved past it. For `taste-skill`, upstream directory names differ from the
skill names Claude Code uses (the name comes from `SKILL.md` frontmatter, not the folder);
the mapping in `sources.json` was derived by reading each upstream `SKILL.md`.

## One skill that travels but does not work

`orca-cli` drives a local `orca` executable. The skill text is portable; the capability is
not. It loads in a cloud session and reports the binary missing. Recorded in
`sources.json` as `runtimeNote`.
