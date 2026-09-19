#!/usr/bin/env python3
"""Vendor third-party skills from their pinned upstream commits.

Content under vendor/ is not authored here. This script is the only supported way to
put it there, so that what is committed is always reproducible from a named upstream
revision rather than copied from somebody's laptop.

    python3 tools/vendor-sync.py            verify vendored content against the pins
    python3 tools/vendor-sync.py --sync     (re)materialise it from the pins
    python3 tools/vendor-sync.py --update <source>   move a pin to upstream HEAD

Stdlib only, like tools/check.py: urllib and tarfile, no dependency to install.
Network is required for --sync and --update; plain verification is offline.
"""
import hashlib
import io
import json
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / 'vendor'
SOURCES = VENDOR / 'sources.json'
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


def members_for(archive: tarfile.TarFile, prefix: str):
    """Every member under prefix/, with the tarball's top directory stripped."""
    root = archive.getnames()[0].split('/', 1)[0]
    want = f'{root}/{prefix}/'
    for member in archive.getmembers():
        if member.name.startswith(want) and (member.isfile() or member.isdir()):
            if member.issym() or member.islnk():
                continue                      # never materialise a link from an archive
            yield member, member.name[len(want):]


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
    blob = fetch(TARBALL.format(repo=spec['repo'], ref=spec['ref']))
    archive = tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz')

    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True)

    for skill, prefix in spec['skills'].items():
        found = False
        for member, relative in members_for(archive, prefix):
            target = dest_root / skill / relative
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
            fail(f'{name}/{skill}', f'nothing found at {prefix} in {spec["ref"][:12]}')

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
            (dest_root / out_name).write_bytes(extracted.read())

    (dest_root / 'PROVENANCE.json').write_text(json.dumps({
        'source': spec['repo'],
        'url': f'https://github.com/{spec["repo"]}',
        'ref': spec['ref'],
        'license': spec['license'],
        'vendoredBy': 'tools/vendor-sync.py',
        'note': 'Third-party content, not authored in this repository. Do not edit here; '
                'change the pin in vendor/sources.json and re-run --sync.',
        'skills': {s: digest_tree(dest_root / s) for s in spec['skills']
                   if (dest_root / s).is_dir()},
        'upstreamPaths': dict(spec['skills']),
    }, indent=2, sort_keys=True) + '\n')
    total = sum(len(v) for v in json.loads((dest_root / 'PROVENANCE.json').read_text())['skills'].values())
    print(f'    {len(spec["skills"])} skills, {total} files, {spec["license"]}')


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


def main() -> int:
    argv = sys.argv[1:]
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
        print(f'\n{len(problems)} problem(s):\n', file=sys.stderr)
        for problem in problems:
            print(f'  {problem}', file=sys.stderr)
        return 1
    total = sum(len(s['skills']) for s in sources.values())
    print(f'ok: {total} vendored skills across {len(sources)} sources '
          f'{"synced" if sync else "verified"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
