#!/usr/bin/env python3
"""Build an optional skill pack from its pinned upstream commit.

Third-party content is not authored here and is no longer stored here. Each pack is its
own repository, built from a specification in `packs/` so that what exists is always
reproducible from a named upstream revision rather than copied from somebody's laptop.

    python3 tools/vendor-sync.py --pack <name> --into <dir>    build a pack repository
    python3 tools/vendor-sync.py --verify-pack --into <dir>    verify one, offline
    python3 tools/vendor-sync.py --update <pack>               move a pin to upstream HEAD

This file used to materialise the same content into a `vendor/` directory committed
here. That directory is gone: the packs are attached per Project instead, so a Project
that wants none of them pays for none of them. The extraction, the traversal refusal and
the staged-then-promoted swap are unchanged, because the failure modes they guard
against did not move.

`--pack` REFUSES a destination that is not empty and is not a pack this tool built, and
there is no flag that overrides it. See `refuse_unless_pack`. Provenance records a file
mode as well as a sha256, so a pack whose scripts stopped being executable no longer
verifies clean; that is `schemaVersion` 2, and a schema-1 pack must be rebuilt.

Stdlib only, like tools/check.py: urllib and tarfile, no dependency to install.
Network is required for --pack and --update; verification is offline.
"""
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKS = ROOT / 'packs'
TARBALL = 'https://codeload.github.com/{repo}/tar.gz/{ref}'
API_HEAD = 'https://api.github.com/repos/{repo}/commits?per_page=1'

problems: list[str] = []


def fail(where, message):
    problems.append(f'{where}: {message}')


def file_mode(path: Path) -> str:
    """The mode this tooling records and reproduces: executable, or not.

    Upstream trees carry 0644 and 0755 and nothing else in practice, and the thing that
    matters to a skill is whether a script it tells an agent to run will execute. So the
    recorded value is that one bit, normalised, rather than the raw stat bits -- which
    would make provenance depend on the umask of whoever built the pack.
    """
    return '0755' if path.stat().st_mode & 0o111 else '0644'


def digest_tree(root: Path) -> dict:
    """sha256 AND mode per file, relative paths, sorted. The unit of provenance.

    Mode is recorded because content alone does not describe a skill. `turnstile-spin`
    ships four scripts its own SKILL.md tells the agent to run; a pack that reproduced
    their bytes and dropped their executable bit verified clean and could not do what it
    documented. Recording the mode is what makes chmod-only drift visible.
    """
    out = {}
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        out[str(path.relative_to(root))] = {
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'mode': file_mode(path),
        }
    return out


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={'User-Agent': 'vendor-sync'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def fetch_tree(repo: str, ref: str) -> bytes:
    """A tar of repo@ref, by whichever route this machine actually has.

    The codeload tarball is the primary route and needs nothing but urllib. Some
    networks reach github.com over git but deny plain HTTPS to codeload -- an agent
    proxy answering 403 to the tarball while `git fetch` works is the case this exists
    for. Falling back keeps the pins, the hashes and the rest of the pipeline identical;
    only the transport differs, and the route taken is printed rather than hidden.
    """
    try:
        return fetch(TARBALL.format(repo=repo, ref=ref))
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        print(f'    tarball unavailable ({exc}); falling back to git')

    if not shutil.which('git'):
        raise SystemExit('the codeload tarball is unreachable and git is not installed')
    work = Path(tempfile.mkdtemp(prefix='vendor-sync-'))
    try:
        run = lambda *args: subprocess.run(args, cwd=work, check=True,
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.PIPE)
        run('git', 'init', '--quiet')
        run('git', 'remote', 'add', 'origin', f'https://github.com/{repo}')
        try:
            run('git', 'fetch', '--quiet', '--depth', '1', 'origin', ref)
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode(errors='replace').strip().splitlines()[-1:] or ['']
            raise SystemExit(f'git could not fetch {repo}@{ref[:12]}: {detail[0]}')
        # The prefix mimics codeload's top directory, which members_for() strips.
        built = subprocess.run(
            ('git', 'archive', '--format=tar', f'--prefix={repo.split("/")[-1]}-{ref}/',
             'FETCH_HEAD'), cwd=work, check=True, stdout=subprocess.PIPE)
        return built.stdout
    finally:
        shutil.rmtree(work, ignore_errors=True)


def safe_join(base: Path, relative: str) -> Path:
    """Resolve base/relative and refuse anything that escapes base.

    A tar member's name is attacker-controlled: `startswith(prefix)` is satisfied by
    `<prefix>/../../etc/passwd` just as well as by a real path, and `Path.__truediv__`
    does not normalise `..` away. Resolving both sides and comparing is the check.
    ValueError rather than a silent skip, so a hostile archive fails the sync loudly.
    """
    base_resolved = base.resolve()
    target = (base_resolved / relative).resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise ValueError(f'archive member escapes the destination: {relative!r}')
    return target


def members_for(archive: tarfile.TarFile, prefix: str):
    """Every member under prefix/, with the tarball's top directory stripped."""
    root = archive.getnames()[0].split('/', 1)[0]
    want = f'{root}/{prefix}/'
    for member in archive.getmembers():
        if member.name.startswith(want) and (member.isfile() or member.isdir()):
            if member.issym() or member.islnk():
                continue                      # never materialise a link from an archive
            yield member, member.name[len(want):]


def extract_skills(archive: tarfile.TarFile, skills: dict, dest_root: Path) -> list:
    """Extract each mapped skill into dest_root/<name>/. Returns the ones that were empty.

    Every member path goes through safe_join, so a hostile archive raises rather than
    writing outside dest_root. Link members are dropped by members_for() and never
    materialised. Raising here is deliberate: the caller tears down its staging tree.
    """
    empty = []
    for skill, prefix in skills.items():
        found = False
        for member, relative in members_for(archive, prefix):
            target = safe_join(dest_root / skill, relative)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            target.write_bytes(extracted.read())
            # Executable INTENT, not the raw mode. `member.mode & 0o755` would turn an
            # upstream 0o600 into 0o400 and strip owner-write; the question being asked
            # is only whether upstream marked this file runnable.
            target.chmod(0o755 if member.mode & 0o100 else 0o644)
            found = True
        if not found:
            empty.append(skill)
    return empty


def frontmatter_name(skill_md: Path) -> str:
    """The `name:` from a SKILL.md's YAML frontmatter, or '' if there is none.

    Claude Code takes a skill's name from this field, not from the directory. For the
    frontend pack six of thirteen upstream folder names differ from the skill name, so
    a mapping typo would produce a pack that builds cleanly and delivers the wrong
    names. This is what makes that checkable rather than reviewed.
    """
    text = skill_md.read_text(encoding='utf-8', errors='replace')
    block = re.match(r'^---\n(.*?)\n---\n', text, re.S)
    if not block:
        return ''
    found = re.search(r'^name:\s*(.+?)\s*$', block.group(1), re.M)
    return found.group(1).strip('\'"') if found else ''


# Everything the builder owns inside a pack repository. Anything else in the destination
# -- .git above all -- is left untouched, because a pack is rebuilt in place after it
# exists as a repository, and a whole-directory swap would take its history with it.
PACK_MANAGED = ('skills', '.claude', '.agents', 'LICENSE', 'NOTICE',
                'PROVENANCE.json', 'PACK.json', 'README.md')

PACK_README = """# {pack} skills

Third-party skills, committed verbatim from a pinned upstream commit. **Nothing here is
authored in this repository**, and nothing here is edited here.

| Upstream | Licence | Skills | Pin |
|---|---|---:|---|
| [{repo}]({url}) | {license} | {count} | `{short}` |

This is an **optional** pack. Attach it to a Claude Project that wants these skills; every
other Project pays nothing for them.

## How these reach a session

`.claude/skills/<name>` is a symlink to `skills/<name>`. That is the mechanism: a repository
attached to a Project delivers skills through those entries and through nothing else. The
container `.claude/skills/` is a real directory, because only a `<skill-name>` entry is
documented as symlinkable. `.agents/skills` is a single container symlink to `../skills`, for
Codex — `../skills` and not `skills`, which would resolve to the link itself and loop.

## Do not edit anything here

This tree is generated. Change the pin in `packs/{pack}.json` in the toolkit repository and
rebuild:

```bash
python3 tools/vendor-sync.py --pack {pack} --into <this directory>
python3 tools/vendor-sync.py --verify-pack --into <this directory>
```

`PROVENANCE.json` records the upstream repository, the exact commit, the licence, the upstream
path of every skill, and a sha256 **and file mode** for every file. Verification is offline and
exact, and a file whose bytes match but whose mode does not is reported as MODE DRIFT rather
than passing. It proves this tree matches what was recorded at build time; it does not prove
the recorded tree matches upstream. `PACK.json` is the specification this was built from,
copied here so the pack verifies on its own.
"""


def load_pack(name: str) -> dict:
    path = PACKS / f'{name}.json'
    if not path.is_file():
        available = sorted(p.stem for p in PACKS.glob('*.json'))
        raise SystemExit(f'no pack spec at {path}. Available: {", ".join(available) or "none"}')
    return json.loads(path.read_text())


# Ignored when deciding whether a destination is empty. `.git` because the documented
# first build goes into a fresh `git init` or a GitHub-initialised repository, and this
# tool's own leftovers because an interrupted earlier run must not lock the directory out.
DESTINATION_IGNORES = ('.git',)


def refuse_unless_pack(into: Path, pack: str) -> None:
    """Refuse a destination that is not empty and is not a pack this tooling built.

    THIS RUNS BEFORE ANYTHING IS FETCHED, CREATED, RENAMED OR DELETED, and it is the
    whole safety property. `build_pack` promotes every name in PACK_MANAGED into the
    destination and then deletes what it displaced, so a destination that is somebody's
    project rather than a pack loses its README, its LICENSE and its .claude/ directory
    with no warning and an exit status of zero. A relative `--into ../something` and a
    wrong working directory is the entire distance between the documented invocation and
    that outcome.

    There is deliberately no --force. Destroying an arbitrary directory is not a thing
    anyone has needed to do on purpose, and a flag that permits it is a flag that gets
    typed. Emptying a directory first is explicit, reversible up to that point, and
    already what someone means.

    A destination is acceptable when it does not exist, when it holds nothing but the
    ignored entries above, or when it carries this tooling's own metadata -- both
    PACK.json and PROVENANCE.json, parseable, with PROVENANCE naming this builder. A pack
    built for a DIFFERENT spec is refused too: overwriting the cloudflare pack with the
    frontend one is the same mistake with tidier inputs.
    """
    if not into.exists():
        return
    if not into.is_dir():
        raise SystemExit(f'--into {into} exists and is not a directory')

    contents = [p.name for p in into.iterdir() if p.name not in DESTINATION_IGNORES
                and not (p.name.startswith(f'.{pack}.')
                         and p.name.endswith(('.staging', '.previous')))]
    if not contents:
        return

    refuse = (f'refusing to build into {into}\n'
              '  It is not empty and does not look like a pack built by this tool.\n'
              '  Building here would replace and then DELETE: '
              f'{", ".join(PACK_MANAGED)}.\n'
              '  Found instead: ' + ', '.join(sorted(contents)[:8])
              + ('' if len(contents) <= 8 else f' (+{len(contents) - 8} more)') + '\n'
              '  Build into an empty directory, or into the pack you mean to update.')

    spec_path, prov_path = into / 'PACK.json', into / 'PROVENANCE.json'
    if not (spec_path.is_file() and prov_path.is_file()):
        raise SystemExit(refuse)
    try:
        existing_spec = json.loads(spec_path.read_text())
        existing_prov = json.loads(prov_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f'{refuse}\n  (PACK.json/PROVENANCE.json present but unreadable: {exc})')
    if not str(existing_prov.get('vendoredBy', '')).startswith('tools/vendor-sync.py'):
        raise SystemExit(f'{refuse}\n  (PROVENANCE.json was not written by this tool)')

    found_name = existing_prov.get('pack') or existing_spec.get('pack')
    if found_name != pack:
        raise SystemExit(
            f'refusing to build the {pack!r} pack into {into}\n'
            f'  That directory is the {found_name!r} pack. Rebuilding one pack over\n'
            '  another would delete its skills. Use the right directory, or empty this one.')


def write_pack_metadata(staging: Path, spec: dict, archive: tarfile.TarFile) -> None:
    """LICENSE, PROVENANCE.json, PACK.json, README.md and the harness entry points."""
    up = spec['upstream']
    root = archive.getnames()[0].split('/', 1)[0]

    # The licence travels with the content. Apache-2.0 §4 and the MIT licence both require it.
    for key, out_name in (('licenseFile', 'LICENSE'), ('noticeFile', 'NOTICE')):
        if not up.get(key):
            continue
        try:
            member = archive.getmember(f'{root}/{up[key]}')
        except KeyError:
            fail(f'{spec["pack"]}/{up[key]}', 'declared in the spec but absent upstream')
            continue
        extracted = archive.extractfile(member)
        if extracted is not None:
            (staging / out_name).write_bytes(extracted.read())

    skills_root = staging / 'skills'
    (staging / 'PROVENANCE.json').write_text(json.dumps({
        # 1 recorded a bare sha256 per file. 2 records {sha256, mode}, so that a pack
        # whose scripts lost their executable bit no longer verifies clean.
        'schemaVersion': 2,
        'source': up['repo'],
        'url': up['url'],
        'ref': up['ref'],
        'license': up['license'],
        'pack': spec['pack'],
        'vendoredBy': 'tools/vendor-sync.py --pack',
        'note': 'Third-party content, not authored in this repository. Do not edit here; '
                f'change the pin in packs/{spec["pack"]}.json and rebuild.',
        'skills': {s: digest_tree(skills_root / s) for s in spec['skills']
                   if (skills_root / s).is_dir()},
        'upstreamPaths': dict(spec['skills']),
    }, indent=2, sort_keys=True) + '\n')

    (staging / 'PACK.json').write_text(json.dumps(spec, indent=2) + '\n')
    (staging / 'README.md').write_text(PACK_README.format(
        pack=spec['pack'], repo=up['repo'], url=up['url'], license=up['license'],
        count=len(spec['skills']), short=up['ref'][:8]))

    # The delivery mechanism. Without these entries the pack attaches and delivers nothing.
    claude_entries = staging / '.claude' / 'skills'
    claude_entries.mkdir(parents=True)
    for skill in spec['skills']:
        if (skills_root / skill).is_dir():
            (claude_entries / skill).symlink_to(Path('..') / '..' / 'skills' / skill)
    (staging / '.agents').mkdir()
    # ../skills, not skills: the link sits inside .agents/, so a bare target would
    # resolve to the link itself. That builds fine and loops on first resolution.
    (staging / '.agents' / 'skills').symlink_to(Path('..') / 'skills')


def build_pack(name: str, into: Path) -> int:
    spec = load_pack(name)
    up = spec['upstream']
    into = into.expanduser().resolve()

    # First, before the network and before a single byte is written, renamed or removed.
    refuse_unless_pack(into, name)
    into.mkdir(parents=True, exist_ok=True)

    print(f'  {name}: fetching {up["repo"]}@{up["ref"][:12]}')
    archive = tarfile.open(fileobj=io.BytesIO(
        fetch_tree(up['repo'], up['ref'])), mode='r:*')

    staging = into / f'.{name}.staging'
    shutil.rmtree(staging, ignore_errors=True)
    (staging / 'skills').mkdir(parents=True)
    try:
        for skill in extract_skills(archive, spec['skills'], staging / 'skills'):
            fail(f'{name}/{skill}',
                 f'nothing found at {spec["skills"][skill]} in {up["ref"][:12]}')
        # A mapping typo builds cleanly and delivers the wrong names, so check the one
        # thing that would catch it: the name the harness actually reads.
        for skill in spec['skills']:
            skill_md = staging / 'skills' / skill / 'SKILL.md'
            if not skill_md.is_file():
                fail(f'{name}/{skill}', 'no SKILL.md in the materialised tree')
                continue
            declared = frontmatter_name(skill_md)
            if declared != skill:
                fail(f'{name}/{skill}', f'SKILL.md frontmatter says name: {declared!r}; '
                                        f'packs/{name}.json maps it as {skill!r}')
        write_pack_metadata(staging, spec, archive)
        if problems:
            raise ValueError(f'{len(problems)} problem(s) building the pack')
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # Promote entry by entry, keeping the previous version until the swap succeeds, so an
    # interrupted build can never leave a half-populated pack -- and so .git survives.
    previous = into / f'.{name}.previous'
    shutil.rmtree(previous, ignore_errors=True)
    previous.mkdir()

    def discard(target: Path) -> None:
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target, ignore_errors=True)

    # An entry that DISPLACED something is restored from `previous`; an entry that was
    # newly created is removed. Tracking only the first left a half-promoted entry behind
    # on a failure -- NOTE on a pack that had none, say -- so the rollback was not one.
    moved, created = [], []
    try:
        for entry in PACK_MANAGED:
            new = staging / entry
            if not new.exists() and not new.is_symlink():
                continue
            old = into / entry
            if old.exists() or old.is_symlink():
                old.rename(previous / entry)
                moved.append(entry)
            else:
                created.append(entry)
            new.rename(old)
    except Exception:
        for entry in created:
            discard(into / entry)
        for entry in moved:
            discard(into / entry)
            (previous / entry).rename(into / entry)
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(previous, ignore_errors=True)
        raise
    shutil.rmtree(previous, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)

    print(f'    {len(spec["skills"])} skills, {up["license"]}, into {into}')
    return 0


def verify_pack(into: Path) -> int:
    """Offline, exact. Re-hash the tree and compare against its own PROVENANCE.json."""
    into = into.expanduser().resolve()
    prov_path = into / 'PROVENANCE.json'
    spec_path = into / 'PACK.json'
    if not prov_path.is_file() or not spec_path.is_file():
        fail(into, 'not a built pack: PROVENANCE.json or PACK.json missing')
        return 1
    prov = json.loads(prov_path.read_text())
    spec = json.loads(spec_path.read_text())
    up = spec['upstream']

    if prov.get('ref') != up['ref']:
        fail(prov_path, f"pinned at {prov.get('ref')!r}, PACK.json says {up['ref']!r}")
    if not (into / 'LICENSE').is_file():
        fail(into / 'LICENSE', 'the licence must travel with the content')
    # Fail closed rather than silently checking less. A schema-1 pack records no mode, so
    # verifying it would pass over exactly the drift this version exists to catch.
    if prov.get('schemaVersion') != 2:
        fail(prov_path, f'schemaVersion {prov.get("schemaVersion")!r}: this pack predates '
                        'file-mode provenance and cannot be verified for chmod drift. '
                        'Rebuild it with --pack.')
        return 1

    entries = into / '.claude' / 'skills'
    if entries.is_symlink() or not entries.is_dir():
        fail(entries, 'expected a real directory of per-skill symlinks. Without it this '
                      'pack attaches to a Project and delivers nothing.')
        entries = None

    for skill in spec['skills']:
        here = into / 'skills' / skill
        if not (here / 'SKILL.md').is_file():
            fail(here, 'skill missing SKILL.md')
            continue
        declared = frontmatter_name(here / 'SKILL.md')
        if declared != skill:
            fail(here, f'SKILL.md frontmatter says name: {declared!r}, not {skill!r}')
        recorded = prov['skills'].get(skill)
        if recorded is None:
            fail(here, 'not recorded in PROVENANCE.json')
        else:
            current = digest_tree(here)
            if recorded != current:
                # Name the kind of drift. A pack whose bytes are intact but whose scripts
                # stopped being executable reads as fine in a diff and is not.
                shared = set(recorded) & set(current)
                mode_only = [f for f in sorted(shared)
                             if recorded[f].get('sha256') == current[f]['sha256']
                             and recorded[f].get('mode') != current[f]['mode']]
                content = [f for f in sorted(shared)
                           if recorded[f].get('sha256') != current[f]['sha256']]
                gone = sorted(set(recorded) - set(current))
                added = sorted(set(current) - set(recorded))
                if mode_only and not (content or gone or added):
                    fail(here, 'MODE DRIFT: content matches the built revision but the '
                               f'file mode does not: {", ".join(mode_only)}. Rebuild.')
                else:
                    detail = []
                    if content:
                        detail.append(f'{len(content)} changed')
                    if gone:
                        detail.append(f'{len(gone)} missing')
                    if added:
                        detail.append(f'{len(added)} unexpected')
                    if mode_only:
                        detail.append(f'{len(mode_only)} mode-only')
                    fail(here, f'CONTENT DRIFT ({", ".join(detail)}): differs from the '
                               'built revision. Rebuild, or move the pin deliberately.')
        if entries is None:
            continue
        link = entries / skill
        if not link.is_symlink():
            fail(link, 'expected a symlink to the skill, not a copy or a missing entry')
        else:
            try:
                resolved = link.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                fail(link, f'does not resolve: {exc}')
            else:
                if resolved != here.resolve():
                    fail(link, f'points at {resolved}, expected {here}')

    container = into / '.agents' / 'skills'
    if not container.is_symlink():
        fail(container, 'expected a container symlink to skills/')
    else:
        # A self-referential link raises rather than comparing unequal, so resolution
        # is guarded: a broken link is a finding, never a traceback.
        try:
            resolved = container.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            fail(container, f'does not resolve: {exc}')
        else:
            if resolved != (into / 'skills').resolve():
                fail(container, f'points at {resolved}, expected {into / "skills"}')

    if problems:
        return 1
    print(f'ok: {len(spec["skills"])} skills in the {spec["pack"]} pack verified offline '
          f'against {up["ref"][:12]}')
    return 0


def update_pin(name: str) -> int:
    """Move a pack's pin to upstream HEAD. Deliberate, never automatic.

    A pin is the whole point of a pack: it is what makes a build reproducible and what
    stops upstream changing under a Project that did not ask. So this rewrites the spec
    and stops, leaving the rebuild, the verification and the push to a separate act.
    """
    path = PACKS / f'{name}.json'
    spec = load_pack(name)
    head = json.loads(fetch(API_HEAD.format(repo=spec['upstream']['repo'])))[0]['sha']
    if head == spec['upstream']['ref']:
        print(f'{name}: already at upstream HEAD {head[:12]}')
        return 0
    previous = spec['upstream']['ref']
    spec['upstream']['ref'] = head
    spec['upstream']['refNote'] = (
        f'Moved to upstream HEAD by --update on this run: {previous[:12]} -> {head[:12]}. '
        'The reason for the move belongs here; replace this sentence with it.')
    path.write_text(json.dumps(spec, indent=2) + '\n')
    print(f'{name}: pin moved {previous[:12]} -> {head[:12]}. '
          f'Now rebuild with --pack {name} --into <dir> and verify before pushing.')
    return 0


def report_problems() -> int:
    print(f'\n{len(problems)} problem(s):\n', file=sys.stderr)
    for problem in problems:
        print(f'  {problem}', file=sys.stderr)
    return 1


def take_into(argv: list) -> Path:
    if '--into' not in argv:
        raise SystemExit('--into <dir> is required')
    index = argv.index('--into')
    if index + 1 >= len(argv):
        raise SystemExit('--into needs a directory')
    return Path(argv[index + 1])


def reject_stray(argv: list, mode: str, consumed: set) -> None:
    """Fail on any argument this mode does not use.

    `main` dispatches on argv[0] alone, so `--pack cloudflare --verify-pack
    --into <dir>` used to BUILD and ignore the --verify-pack entirely. Someone
    who meant to verify a pack got it rebuilt instead. The destination guard
    stops that destroying a non-pack directory, but silently doing the opposite
    of what was asked is not something to leave in place.
    """
    stray = [a for a in argv if a not in consumed]
    if stray:
        raise SystemExit(
            f'{mode} does not take {", ".join(stray)}\n'
            f'  Did you mean one of these?\n{USAGE}')


USAGE = """usage:
  tools/vendor-sync.py --pack <name> --into <dir>    build a pack repository
  tools/vendor-sync.py --verify-pack --into <dir>    verify a built pack, offline
  tools/vendor-sync.py --update <pack>               move a pin to upstream HEAD
"""


def main() -> int:
    argv = sys.argv[1:]

    if argv and argv[0] == '--pack':
        if len(argv) < 2 or argv[1].startswith('-'):
            raise SystemExit('--pack needs a name, e.g. --pack cloudflare --into ../dir')
        into = take_into(argv)
        reject_stray(argv, '--pack', {'--pack', argv[1], '--into', str(into)})
        try:
            return build_pack(argv[1], into)
        except ValueError:
            return report_problems()
    if argv and argv[0] == '--verify-pack':
        into = take_into(argv)
        reject_stray(argv, '--verify-pack', {'--verify-pack', '--into', str(into)})
        rc = verify_pack(into)
        return report_problems() if problems else rc

    available = sorted(p.stem for p in PACKS.glob('*.json'))
    if argv and argv[0] == '--update':
        if len(argv) != 2 or argv[1] not in available:
            print(f'--update needs one of: {", ".join(available)}', file=sys.stderr)
            return 2
        return update_pin(argv[1])

    print(USAGE, file=sys.stderr)
    print(f'packs: {", ".join(available) or "none"}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
