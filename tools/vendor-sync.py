#!/usr/bin/env python3
"""Materialise third-party skills from their pinned upstream commits.

Third-party content is not authored here. This script is the only supported way to put
it anywhere, so that what exists is always reproducible from a named upstream revision
rather than copied from somebody's laptop.

Two destinations, one mechanism:

    python3 tools/vendor-sync.py            verify vendored content against the pins
    python3 tools/vendor-sync.py --sync     (re)materialise it from the pins
    python3 tools/vendor-sync.py --update <source>   move a pin to upstream HEAD

    python3 tools/vendor-sync.py --pack <name> --into <dir>    build a pack repository
    python3 tools/vendor-sync.py --verify-pack --into <dir>    verify one, offline

`vendor/` is the old destination and is on its way out; `packs/` is the new one. Both
ride the same fetch, the same traversal refusal and the same staged-then-promoted swap,
because the failure modes they guard against are identical.

Stdlib only, like tools/check.py: urllib and tarfile, no dependency to install.
Network is required for --sync, --update and --pack; both verifications are offline.
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
VENDOR = ROOT / 'vendor'
SOURCES = VENDOR / 'sources.json'
PACKS = ROOT / 'packs'
TARBALL = 'https://codeload.github.com/{repo}/tar.gz/{ref}'
API_HEAD = 'https://api.github.com/repos/{repo}/commits?per_page=1'

problems: list[str] = []


def fail(where, message):
    problems.append(f'{where}: {message}')


def digest_tree(root: Path) -> dict:
    """sha256 per file, relative paths, sorted. The unit of provenance."""
    out = {}
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
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


def sync_source(name: str, spec: dict, sync: bool) -> None:
    dest_root = VENDOR / name
    if not sync:
        prov_path = dest_root / 'PROVENANCE.json'
        if not prov_path.is_file():
            fail(dest_root, 'no PROVENANCE.json; run tools/vendor-sync.py --sync')
            return
        prov = json.loads(prov_path.read_text())
        if prov.get('ref') != spec['ref']:
            fail(prov_path, f"pinned at {prov.get('ref')!r}, sources.json says {spec['ref']!r}")
        for skill in spec['skills']:
            here = dest_root / skill
            if not (here / 'SKILL.md').is_file():
                fail(here, 'vendored skill missing SKILL.md')
                continue
            recorded = prov['skills'].get(skill)
            if recorded is None:
                fail(here, 'not recorded in PROVENANCE.json')
            elif recorded != digest_tree(here):
                fail(here, 'CONTENT DRIFT: differs from the vendored revision. '
                           'Re-run --sync, or update the pin deliberately.')
        return

    print(f'  {name}: fetching {spec["repo"]}@{spec["ref"][:12]}')
    blob = fetch_tree(spec['repo'], spec['ref'])
    archive = tarfile.open(fileobj=io.BytesIO(blob), mode='r:*')

    # Build into a staging tree and swap it in only once everything succeeded. The
    # previous version deleted the existing tree first, so a truncated download, a
    # hostile member or a disk error left no vendored content at all and nothing to
    # roll back to.
    staging = VENDOR / f'.{name}.staging'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    try:
        for skill in extract_skills(archive, spec['skills'], staging):
            fail(f'{name}/{skill}',
                 f'nothing found at {spec["skills"][skill]} in {spec["ref"][:12]}')
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    try:
        # The licence travels with the content. Apache-2.0 and MIT both require it.
        root = archive.getnames()[0].split('/', 1)[0]
        for key, out_name in (('licenseFile', 'LICENSE'), ('noticeFile', 'NOTICE')):
            if not spec.get(key):
                continue
            try:
                member = archive.getmember(f'{root}/{spec[key]}')
            except KeyError:
                fail(f'{name}/{spec[key]}', 'declared in sources.json but absent upstream')
                continue
            extracted = archive.extractfile(member)
            if extracted is not None:
                (staging / out_name).write_bytes(extracted.read())

        (staging / 'PROVENANCE.json').write_text(json.dumps({
            'source': spec['repo'],
            'url': f'https://github.com/{spec["repo"]}',
            'ref': spec['ref'],
            'license': spec['license'],
            'vendoredBy': 'tools/vendor-sync.py',
            'note': 'Third-party content, not authored in this repository. Do not edit here; '
                    'change the pin in vendor/sources.json and re-run --sync.',
            'skills': {s: digest_tree(staging / s) for s in spec['skills']
                       if (staging / s).is_dir()},
            'upstreamPaths': dict(spec['skills']),
        }, indent=2, sort_keys=True) + '\n')
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # Promote. The old tree is kept until the new one is in place, and restored if the
    # swap itself fails, so an interrupted sync can never leave nothing behind.
    previous = VENDOR / f'.{name}.previous'
    shutil.rmtree(previous, ignore_errors=True)
    try:
        if dest_root.exists():
            dest_root.rename(previous)
        staging.rename(dest_root)
    except Exception:
        if previous.exists() and not dest_root.exists():
            previous.rename(dest_root)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(previous, ignore_errors=True)

    total = sum(len(v) for v in json.loads((dest_root / 'PROVENANCE.json').read_text())['skills'].values())
    print(f'    {len(spec["skills"])} skills, {total} files, {spec["license"]}')


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
documented as symlinkable. `.agents/skills` is a single container symlink, for Codex.

## Do not edit anything here

This tree is generated. Change the pin in `packs/{pack}.json` in the toolkit repository and
rebuild:

```bash
python3 tools/vendor-sync.py --pack {pack} --into <this directory>
python3 tools/vendor-sync.py --verify-pack --into <this directory>
```

`PROVENANCE.json` records the upstream repository, the exact commit, the licence, the upstream
path of every skill and a sha256 for every file. Verification is offline and exact. It proves
this tree matches what was recorded at build time; it does not prove the recorded tree matches
upstream. `PACK.json` is the specification this was built from, copied here so the pack
verifies on its own.
"""


def load_pack(name: str) -> dict:
    path = PACKS / f'{name}.json'
    if not path.is_file():
        available = sorted(p.stem for p in PACKS.glob('*.json'))
        raise SystemExit(f'no pack spec at {path}. Available: {", ".join(available) or "none"}')
    return json.loads(path.read_text())


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
    moved = []
    try:
        for entry in PACK_MANAGED:
            new = staging / entry
            if not new.exists() and not new.is_symlink():
                continue
            old = into / entry
            if old.exists() or old.is_symlink():
                old.rename(previous / entry)
                moved.append(entry)
            new.rename(old)
    except Exception:
        for entry in moved:
            target = into / entry
            if target.exists() or target.is_symlink():
                shutil.rmtree(target, ignore_errors=True) if target.is_dir() \
                    and not target.is_symlink() else target.unlink()
            (previous / entry).rename(target)
        shutil.rmtree(staging, ignore_errors=True)
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
        elif recorded != digest_tree(here):
            fail(here, 'CONTENT DRIFT: differs from the built revision. Rebuild, or move '
                       'the pin deliberately.')
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


def update_pin(name: str, spec: dict) -> int:
    data = json.loads(fetch(API_HEAD.format(repo=spec['repo'])))
    head = data[0]['sha']
    if head == spec['ref']:
        print(f'{name}: already at upstream HEAD {head[:12]}')
        return 0
    document = json.loads(SOURCES.read_text())
    document['sources'][name]['ref'] = head
    document['sources'][name]['refNote'] = f'Moved to upstream HEAD by --update: {head[:12]}.'
    SOURCES.write_text(json.dumps(document, indent=2) + '\n')
    print(f'{name}: pin moved {spec["ref"][:12]} -> {head[:12]}. Now run --sync.')
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


def main() -> int:
    argv = sys.argv[1:]

    # Pack modes first: they read packs/, not vendor/, and must keep working after
    # vendor/ is gone.
    if argv and argv[0] == '--pack':
        if len(argv) < 2 or argv[1].startswith('-'):
            raise SystemExit('--pack needs a name, e.g. --pack cloudflare --into ../dir')
        into = take_into(argv)
        try:
            return build_pack(argv[1], into)
        except ValueError:
            return report_problems()
    if argv and argv[0] == '--verify-pack':
        rc = verify_pack(take_into(argv))
        return report_problems() if problems else rc

    document = json.loads(SOURCES.read_text())
    sources = document['sources']

    if argv and argv[0] == '--update':
        if len(argv) != 2 or argv[1] not in sources:
            print(f'--update needs one of: {", ".join(sources)}', file=sys.stderr)
            return 2
        return update_pin(argv[1], sources[argv[1]])

    sync = argv == ['--sync']
    if argv and not sync:
        print(f'unrecognised argument(s): {argv}', file=sys.stderr)
        return 2

    print('syncing vendor/' if sync else 'verifying vendor/')
    for name, spec in sources.items():
        sync_source(name, spec, sync)

    if problems:
        return report_problems()
    total = sum(len(s['skills']) for s in sources.values())
    print(f'ok: {total} vendored skills across {len(sources)} sources '
          f'{"synced" if sync else "verified"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
