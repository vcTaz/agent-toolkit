#!/usr/bin/env bash
# test.sh — behavioural tests for the host layer.
#
# Each test names the defect it guards. A test that cannot run reports SKIP rather than
# passing quietly, which is the same rule local/doctor.sh follows.
#
# Dependencies: bash and python3 (3.9+, stdlib). No framework, no network, no CI config.
# Nothing here writes outside its own mktemp directory.
#
#   bash tools/test.sh
#
# SCOPE. These cover the host layer: the pack builder, the install scripts, the
# host-layer invariant and basic hygiene. They are not a full suite for the toolkit.
# Nothing here reaches the network, so the pack tests exercise the builder against
# synthetic archives rather than building a real pack -- `--pack` plus `--verify-pack`
# against a real upstream is a manual step, and the two pack repositories are verified
# offline from their own PROVENANCE.json.

set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
passed=0; failed=0; skipped=0
TMPROOT="$(mktemp -d)"
trap 'rm -rf "$TMPROOT"' EXIT

ok()   { printf '  ok    %s\n' "$*"; passed=$((passed + 1)); }
no()   { printf '  FAIL  %s\n' "$*"; failed=$((failed + 1)); }
skip() { printf '  skip  %s\n' "$*"; skipped=$((skipped + 1)); }
group() { printf '\n%s\n' "$*"; }

# ---------------------------------------------------------------------------------------
group "pack builder: path traversal (guards a tarball escaping the destination)"

if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent — pack builder tests cannot run"
else
  out="$(cd "$ROOT" && python3 - <<'PY' 2>&1
import importlib.util, pathlib, sys, tempfile

spec = importlib.util.spec_from_file_location('vs', 'tools/vendor-sync.py')
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)

base = pathlib.Path(tempfile.mkdtemp()) / 'dest'
base.mkdir()
hostile = ['../escaped', '../../etc/passwd', 'a/../../../etc/x', '/etc/absolute']
for name in hostile:
    try:
        vs.safe_join(base, name)
    except ValueError:
        print(f'REFUSED {name}')
    else:
        print(f'ACCEPTED {name}')
# a legitimate nested path must still resolve, inside the base
good = vs.safe_join(base, 'skill/nested/SKILL.md')
print('INSIDE' if base.resolve() in good.parents else 'OUTSIDE', 'skill/nested/SKILL.md')
PY
)"
  for bad in '../escaped' '../../etc/passwd' 'a/../../../etc/x' '/etc/absolute'; do
    if printf '%s' "$out" | grep -qF "REFUSED $bad"; then ok "safe_join refuses $bad"
    else no "safe_join ACCEPTED $bad"; fi
  done
  if printf '%s' "$out" | grep -q '^INSIDE'; then ok "safe_join still allows a legitimate nested path"
  else no "safe_join rejected a legitimate nested path"; fi
fi

# ---------------------------------------------------------------------------------------
group "pack builder: a hostile archive cannot destroy the existing tree"

if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent"
else
  out="$(cd "$ROOT" && python3 - <<'PY' 2>&1
import importlib.util, io as _io, json, pathlib, tarfile, tempfile

spec = importlib.util.spec_from_file_location('vs', 'tools/vendor-sync.py')
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)

# Everything happens inside `isolated`. The hostile member below traverses exactly three
# levels, which lands inside `isolated` and never above it. An earlier version of this
# test used a deeper traversal, and running it against the vulnerable code wrote a real
# file to the filesystem root -- a test must not be able to do that even when it fails.
isolated = pathlib.Path(tempfile.mkdtemp())
pack_dir = isolated / 'lvl1' / 'lvl2' / 'pack'
pack_dir.mkdir(parents=True)

spec_dict = {'pack': 'demo', 'packRepo': 'x/demo',
             'upstream': {'repo': 'x/y', 'url': 'https://example.invalid', 'ref': 'a' * 40,
                          'license': 'MIT', 'licenseFile': 'LICENSE', 'noticeFile': None},
             'skills': {'demo': 'skills/demo'}, 'layout': {'claudeEntries': True}}
vs.load_pack = lambda name: spec_dict


def tarball(members):
    buf = _io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for path, body in members:
            info = tarfile.TarInfo(path); data = body.encode()
            info.size = len(data); tar.addfile(info, _io.BytesIO(data))
    return buf.getvalue()


# An existing, GENUINE pack that must survive a failed rebuild byte for byte. It has to
# be a real one: the destination guard refuses a rebuild into anything else, so a
# hand-made directory would never reach the extraction this test is about.
benign = tarball([('up-abc/skills/demo/SKILL.md',
                   '---\nname: demo\ndescription: d\n---\nORIGINAL CONTENT\n'),
                  ('up-abc/LICENSE', 'MIT\n')])
vs.fetch_tree = lambda repo, ref: benign
vs.build_pack('demo', pack_dir)
original = (pack_dir / 'skills' / 'demo' / 'SKILL.md').read_text()

# Now a tarball whose member escapes the destination.
hostile = tarball([
    ('up-abc/skills/demo/SKILL.md', '---\nname: demo\ndescription: d\n---\nlegitimate\n'),
    # relative to <pack>/.demo.staging/skills/demo this stays inside lvl1/lvl2
    ('up-abc/skills/demo/../../../escaped.md', 'HOSTILE\n'),
    ('up-abc/LICENSE', 'MIT\n')])
vs.fetch_tree = lambda repo, ref: hostile
try:
    vs.build_pack('demo', pack_dir)
    print('BUILD-RETURNED-OK')
except ValueError:
    print('BUILD-RAISED')
except Exception as exc:
    print('BUILD-RAISED', type(exc).__name__)

print('PRESERVED' if (pack_dir / 'skills' / 'demo' / 'SKILL.md').read_text()
      == original else 'CLOBBERED')
# `.claude` and `.agents` are a real pack's own directories, so match this builder's own
# scratch names rather than every dotfile.
leftovers = [p.name for p in pack_dir.iterdir() if p.name.startswith('.demo.')]
print('NO-STAGING' if not leftovers else f'STAGING-LEFT {leftovers}')
# Nothing anywhere under the isolated root may sit outside the pack directory.
strays = [str(p.relative_to(isolated)) for p in isolated.rglob('*')
          if p.is_file() and pack_dir not in p.parents and p.parent != pack_dir]
print('NO-ESCAPE' if not strays else f'ESCAPED {strays}')
PY
)"
  printf '%s' "$out" | grep -q 'BUILD-RAISED' && ok "a traversal member aborts the build loudly" \
                                             || no "traversal member did not raise: $out"
  printf '%s' "$out" | grep -q 'PRESERVED'    && ok "the previous pack survives byte-identical" \
                                             || no "the previous pack was clobbered"
  printf '%s' "$out" | grep -q 'NO-STAGING'   && ok "no staging directory is left behind" \
                                             || no "staging directory left behind"
  printf '%s' "$out" | grep -q 'NO-ESCAPE'    && ok "nothing was written outside the destination" \
                                             || no "a file escaped the destination: $out"
fi

# ---------------------------------------------------------------------------------------
group "pack builder: refuses a destination that is not a pack (guards data loss)"

# Before this guard, `--pack --into <dir>` promoted every PACK_MANAGED name into the
# destination and then DELETED what it displaced. Pointed at somebody's project it
# removed their README, LICENSE and .claude/ directory, returned 0 and printed success.
# The documented invocation uses a RELATIVE --into, so a wrong working directory was the
# whole distance to that outcome. These cases are the guard, in both directions: the
# legitimate destinations must still build.

if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent — destination-guard tests cannot run"
else
  out="$(cd "$ROOT" && python3 - <<'PY' 2>&1
import hashlib, importlib.util, io, pathlib, tarfile, tempfile

spec = importlib.util.spec_from_file_location('vs', 'tools/vendor-sync.py')
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)

buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode='w:gz') as tar:
    for name, body, mode in (
            ('up/skills/demo/SKILL.md', '---\nname: demo\ndescription: d\n---\nbody\n', 0o644),
            ('up/skills/demo/run.sh', '#!/bin/sh\necho hi\n', 0o755),
            ('up/LICENSE', 'MIT\n', 0o644)):
        info = tarfile.TarInfo(name); data = body.encode()
        info.size, info.mode = len(data), mode
        tar.addfile(info, io.BytesIO(data))
vs.fetch_tree = lambda repo, ref: buf.getvalue()
vs.load_pack = lambda name: {
    'pack': 'demo', 'packRepo': 'x/demo',
    'upstream': {'repo': 'x/y', 'url': 'https://example.invalid', 'ref': 'a' * 40,
                 'license': 'MIT', 'licenseFile': 'LICENSE', 'noticeFile': None},
    'skills': {'demo': 'skills/demo'}, 'layout': {'claudeEntries': True}}

root = pathlib.Path(tempfile.mkdtemp())
snapshot = lambda d: {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(d.rglob('*')) if p.is_file()}


def build(dest):
    vs.problems.clear()
    try:
        vs.build_pack('demo', dest)
        return 'BUILT'
    except SystemExit:
        return 'REFUSED'
    except Exception as exc:
        return f'ERROR-{type(exc).__name__}'


empty = root / 'empty'; empty.mkdir()
print('EMPTY', build(empty))

onlygit = root / 'onlygit'; (onlygit / '.git').mkdir(parents=True)
(onlygit / '.git' / 'HEAD').write_text('ref: refs/heads/main\n')
print('ONLYGIT', build(onlygit))
print('REBUILD', build(onlygit))                      # now a real pack: must update

victim = root / 'victim'; (victim / '.claude' / 'agents').mkdir(parents=True)
(victim / '.claude' / 'agents' / 'mine.md').write_text('MY AGENT\n')
(victim / 'README.md').write_text('# my project\n')
(victim / 'LICENSE').write_text('my licence\n')
(victim / 'src').mkdir(); (victim / 'src' / 'main.py').write_text('print(1)\n')
before = snapshot(victim)
print('ARBITRARY', build(victim))
print('UNCHANGED' if snapshot(victim) == before else 'MUTATED',
      'agent-survived' if (victim / '.claude' / 'agents' / 'mine.md').is_file() else 'AGENT-LOST')

other = root / 'otherpack'; other.mkdir()
build(other)                                          # a real 'demo' pack
vs.load_pack = lambda name: {
    'pack': 'notdemo', 'packRepo': 'x/notdemo',
    'upstream': {'repo': 'x/y', 'url': 'https://example.invalid', 'ref': 'b' * 40,
                 'license': 'MIT', 'licenseFile': 'LICENSE', 'noticeFile': None},
    'skills': {'demo': 'skills/demo'}, 'layout': {'claudeEntries': True}}
vs.problems.clear()
try:
    vs.build_pack('notdemo', other); print('CROSSPACK BUILT')
except SystemExit:
    print('CROSSPACK REFUSED')

# The guard read the ignore list by NAME. A directory holding nothing but a SYMLINK at
# `.demo.staging` therefore read as empty, rmtree could not remove a link and
# ignore_errors hid it, and the build happened inside the link's TARGET -- the original
# defect's outcome, at exit status 0, through the one door the guard left open.
vs.load_pack = lambda name: {
    'pack': 'demo', 'packRepo': 'x/demo',
    'upstream': {'repo': 'x/y', 'url': 'https://example.invalid', 'ref': 'a' * 40,
                 'license': 'MIT', 'licenseFile': 'LICENSE', 'noticeFile': None},
    'skills': {'demo': 'skills/demo'}, 'layout': {'claudeEntries': True}}


def make_victim(where):
    (where / '.claude' / 'agents').mkdir(parents=True)
    (where / '.claude' / 'agents' / 'mine.md').write_text('MY AGENT\n')
    (where / 'README.md').write_text('# my project\n')
    (where / 'LICENSE').write_text('my licence\n')
    (where / 'src').mkdir(); (where / 'src' / 'main.py').write_text('print(1)\n')


linkvictim = root / 'linkvictim'; linkvictim.mkdir(); make_victim(linkvictim)
linkbait = root / 'linkbait'; linkbait.mkdir()
(linkbait / '.demo.staging').symlink_to(linkvictim)
vbefore = snapshot(linkvictim)
print('STAGINGLINK', build(linkbait))
print('LINKVICTIM',
      'UNCHANGED' if snapshot(linkvictim) == vbefore else 'MUTATED',
      'agent-kept' if (linkvictim / '.claude' / 'agents' / 'mine.md').is_file()
      else 'AGENT-LOST')

# A plain FILE at the scratch name was accepted the same way, and previous.mkdir() then
# raised uncaught, leaving the whole extracted pack behind as an orphan.
filebait = root / 'filebait'; filebait.mkdir()
(filebait / '.demo.previous').write_text('stale\n')
print('PREVIOUSFILE', build(filebait))
print('NOORPHAN' if not (filebait / '.demo.staging').exists() else 'ORPHAN-LEFT')

# The same shapes inside a GENUINE pack, where the metadata check accepts the destination
# and the emptiness test never runs. Only clear_scratch() protects this one.
packvictim = root / 'packvictim'; packvictim.mkdir(); make_victim(packvictim)
realpack = root / 'realpack'; realpack.mkdir()
build(realpack)
(realpack / '.demo.staging').symlink_to(packvictim)
pbefore = snapshot(packvictim)
print('PACKRELINK', build(realpack))
print('PACKVICTIM',
      'UNCHANGED' if snapshot(packvictim) == pbefore else 'MUTATED',
      'agent-kept' if (packvictim / '.claude' / 'agents' / 'mine.md').is_file()
      else 'AGENT-LOST')
vs.problems.clear(); print(f'PACKRELINKVERIFIES rc={vs.verify_pack(realpack)}')

# An interrupt is a BaseException. `except Exception` did not see it, so Ctrl-C during
# extraction left a part-built staging tree in a destination that started empty.
interrupted = root / 'interrupted'; interrupted.mkdir()
real_extract = vs.extract_skills
vs.extract_skills = lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt())
try:
    vs.problems.clear(); vs.build_pack('demo', interrupted)
    print('INTERRUPT BUILT')
except KeyboardInterrupt:
    print('INTERRUPT RAISED')
except BaseException as exc:
    print(f'INTERRUPT OTHER-{type(exc).__name__}')
vs.extract_skills = real_extract
print('INTERRUPTCLEAN' if not any(interrupted.iterdir()) else
      f'INTERRUPT-ORPHAN {[p.name for p in interrupted.iterdir()]}')
print('INTERRUPTRETRY', build(interrupted))
PY
)"
  for case in 'EMPTY BUILT:an empty destination still builds' \
              'ONLYGIT BUILT:a destination holding only .git still builds' \
              'REBUILD BUILT:an existing pack still rebuilds in place' \
              'ARBITRARY REFUSED:an arbitrary directory is refused' \
              'UNCHANGED:the refused directory is left content-identical' \
              'agent-survived:the refusal left .claude/agents/mine.md in place' \
              'CROSSPACK REFUSED:building one pack over a different pack is refused' \
              'STAGINGLINK REFUSED:a directory holding only a symlink at the staging name is refused' \
              'LINKVICTIM UNCHANGED agent-kept:and the directory that symlink pointed at is untouched' \
              'PREVIOUSFILE REFUSED:a directory holding only a file at the scratch name is refused' \
              'NOORPHAN:and no orphan staging tree is left behind' \
              'PACKRELINK BUILT:a genuine pack rebuilds through a symlink left at its scratch name' \
              'PACKVICTIM UNCHANGED agent-kept:without writing into what that symlink pointed at' \
              'PACKRELINKVERIFIES rc=0:and the rebuilt pack verifies' \
              'INTERRUPT RAISED:an interrupt propagates rather than being swallowed' \
              'INTERRUPTCLEAN:and leaves no staging tree in a destination that started empty' \
              'INTERRUPTRETRY BUILT:so the next build succeeds'; do
    token="${case%%:*}"; label="${case#*:}"
    if printf '%s' "$out" | grep -qF "$token"; then ok "${label:-$token}"
    else no "${label:-$token} — got: $out"; fi
  done
fi

# ---------------------------------------------------------------------------------------
group "pack builder: a mode that does not take a flag refuses rather than ignoring it"

# `main` dispatches on argv[0] alone. Before reject_stray, this line BUILT:
#   vendor-sync.py --pack cloudflare --verify-pack --into <dir>
# The --verify-pack was dropped on the floor and the destination was rebuilt. Someone who
# meant to check a pack got it overwritten instead, and the exit status said success. The
# destination guard above keeps that from destroying a non-pack directory; this keeps the
# tool from doing the opposite of what it was asked.

if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent — argument-strictness tests cannot run"
else
  dest="$TMPROOT/strict-dest"; mkdir -p "$dest"
  # A REAL pack name, deliberately: with a made-up one the pre-fix code refuses for the
  # wrong reason ("no pack spec") and the test passes without detecting anything. With a
  # real one the pre-fix code builds, which is the behaviour being guarded against.
  for case in '--pack cloudflare --verify-pack --into:a build line carrying --verify-pack is refused' \
              '--verify-pack --into@--pack cloudflare:a verify line carrying --pack is refused' \
              '--pack cloudflare --into@--dry-run:an unrecognised flag is refused'; do
    args="${case%%:*}"; label="${case#*:}"
    # `@` separates arguments that must land after the --into value.
    before="${args%%@*}"; after=""
    [ "$args" = "$before" ] || after="${args#*@}"
    # shellcheck disable=SC2086
    rc=0
    out="$(cd "$ROOT" && python3 tools/vendor-sync.py $before "$dest" $after 2>&1)" || rc=$?
    if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -qi 'does not take'; then
      ok "$label (rc=$rc)"
    else
      no "$label — rc=$rc, got: $out"
    fi
  done
  if [ -z "$(ls -A "$dest")" ]; then ok "a refused invocation wrote nothing to the destination"
  else no "a refused invocation left files behind: $(ls -A "$dest")"; fi
fi

# ---------------------------------------------------------------------------------------
group "pack builder: --verify-pack REJECTS a tampered pack (the production code path)"

# The suite used to call verify_pack zero times. Every case below runs the real
# implementation and asserts its EXIT STATUS, not its wording.

if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent — verification tests cannot run"
else
  out="$(cd "$ROOT" && python3 - <<'PY' 2>&1
import importlib.util, io, json, pathlib, shutil, tarfile, tempfile

spec = importlib.util.spec_from_file_location('vs', 'tools/vendor-sync.py')
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)

buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode='w:gz') as tar:
    for name, body, mode in (
            ('up/skills/demo/SKILL.md', '---\nname: demo\ndescription: d\n---\nbody\n', 0o644),
            ('up/skills/demo/run.sh', '#!/bin/sh\necho hi\n', 0o755),
            ('up/LICENSE', 'MIT\n', 0o644)):
        info = tarfile.TarInfo(name); data = body.encode()
        info.size, info.mode = len(data), mode
        tar.addfile(info, io.BytesIO(data))
vs.fetch_tree = lambda repo, ref: buf.getvalue()
vs.load_pack = lambda name: {
    'pack': 'demo', 'packRepo': 'x/demo',
    'upstream': {'repo': 'x/y', 'url': 'https://example.invalid', 'ref': 'a' * 40,
                 'license': 'MIT', 'licenseFile': 'LICENSE', 'noticeFile': None},
    'skills': {'demo': 'skills/demo'}, 'layout': {'claudeEntries': True}}

root = pathlib.Path(tempfile.mkdtemp())
pristine = root / 'pristine'
vs.problems.clear(); vs.build_pack('demo', pristine)

n = [0]
def case(label, mutate):
    n[0] += 1
    copy = root / f'case{n[0]}'
    shutil.copytree(pristine, copy, symlinks=True)
    mutate(copy)
    vs.problems.clear()
    print(f'{label} rc={vs.verify_pack(copy)}')

case('BASELINE', lambda p: None)
case('CONTENT', lambda p: (p / 'skills' / 'demo' / 'SKILL.md').write_text('tampered\n'))
case('EXTRA', lambda p: (p / 'skills' / 'demo' / 'sneaked.md').write_text('x\n'))
case('CHMOD', lambda p: (p / 'skills' / 'demo' / 'run.sh').chmod(0o644))
case('ENTRY', lambda p: (p / '.claude' / 'skills' / 'demo').unlink())
case('LICENCE', lambda p: (p / 'LICENSE').unlink())
case('LOOP', lambda p: ((p / '.agents' / 'skills').unlink(),
                        (p / '.agents' / 'skills').symlink_to('skills')))
def old_schema(p):
    prov = json.loads((p / 'PROVENANCE.json').read_text())
    prov['schemaVersion'] = 1
    prov['skills']['demo'] = {k: v['sha256'] for k, v in prov['skills']['demo'].items()}
    (p / 'PROVENANCE.json').write_text(json.dumps(prov, indent=2))
case('SCHEMA1', old_schema)

# Everything below guards a hole found AFTER the cases above were written, each one
# measured verifying `ok` on the code they were written against.
case('NOTICEFILE', lambda p: (p / 'NOTICE').write_text('not from upstream\n'))
def notice_dir(p):
    (p / 'NOTICE' / 'payload').mkdir(parents=True)
    (p / 'NOTICE' / 'payload' / 'evil.md').write_text('unrecorded\n')
case('NOTICEDIR', notice_dir)
def gitattr_dir(p):
    (p / '.gitattributes' / 'x').mkdir(parents=True)
    (p / '.gitattributes' / 'x' / 'a.md').write_text('unrecorded\n')
case('GITATTRDIR', gitattr_dir)
# The other direction: git's own files are not content and must still pass.
case('GITIGNORE', lambda p: (p / '.gitignore').write_text('*.pyc\n'))
def sym_dir_in_skill(p):
    (p / 'NOTICE').mkdir()
    (p / 'NOTICE' / 'reference.md').write_text('unrecorded\n')
    (p / 'skills' / 'demo' / 'ref').symlink_to(pathlib.Path('..') / '..' / 'NOTICE')
case('SYMDIR', sym_dir_in_skill)
case('SYMSKILL', lambda p: (p / 'skills' / 'aliased').symlink_to(pathlib.Path('demo')))
def files_empty(p):
    prov = json.loads((p / 'PROVENANCE.json').read_text())
    prov['files'] = {}
    (p / 'PROVENANCE.json').write_text(json.dumps(prov, indent=2))
    (p / 'LICENSE').write_text('All rights reserved. No licence granted.\n')
case('FILESEMPTY', files_empty)
def files_pop(p):
    prov = json.loads((p / 'PROVENANCE.json').read_text())
    prov['files'].pop('LICENSE')
    (p / 'PROVENANCE.json').write_text(json.dumps(prov, indent=2))
    (p / 'LICENSE').write_text('All rights reserved. No licence granted.\n')
case('FILESPOP', files_pop)
def files_stray(p):
    prov = json.loads((p / 'PROVENANCE.json').read_text())
    prov['files']['skills/demo/SKILL.md'] = {'sha256': 'x' * 64, 'mode': '0644'}
    (p / 'PROVENANCE.json').write_text(json.dumps(prov, indent=2))
case('FILESSTRAY', files_stray)
case('BADJSON', lambda p: (p / 'PROVENANCE.json').write_text('not json\n'))
def schema_ahead(p):
    prov = json.loads((p / 'PROVENANCE.json').read_text())
    prov['schemaVersion'] = 3
    (p / 'PROVENANCE.json').write_text(json.dumps(prov, indent=2))
case('SCHEMA3', schema_ahead)
def prov_fields(p):
    prov = json.loads((p / 'PROVENANCE.json').read_text())
    prov['license'], prov['pack'] = 'Proprietary', 'somethingelse'
    (p / 'PROVENANCE.json').write_text(json.dumps(prov, indent=2))
case('PROVFIELDS', prov_fields)
def prov_paths(p):
    prov = json.loads((p / 'PROVENANCE.json').read_text())
    prov['upstreamPaths'] = {}
    (p / 'PROVENANCE.json').write_text(json.dumps(prov, indent=2))
case('PROVPATHS', prov_paths)

# A pack that legitimately SHIPS a NOTICE: the rejections above must not come from
# refusing the name, and a tampered one must still be caught by its recorded hash.
nbuf = io.BytesIO()
with tarfile.open(fileobj=nbuf, mode='w:gz') as tar:
    for name, body, mode in (
            ('up/skills/demo/SKILL.md', '---\nname: demo\ndescription: d\n---\nbody\n', 0o644),
            ('up/LICENSE', 'Apache-2.0\n', 0o644),
            ('up/NOTICE', 'Copyright someone\n', 0o644)):
        info = tarfile.TarInfo(name); data = body.encode()
        info.size, info.mode = len(data), mode
        tar.addfile(info, io.BytesIO(data))
vs.fetch_tree = lambda repo, ref: nbuf.getvalue()
vs.load_pack = lambda name: {
    'pack': 'demo', 'packRepo': 'x/demo',
    'upstream': {'repo': 'x/y', 'url': 'https://example.invalid', 'ref': 'a' * 40,
                 'license': 'Apache-2.0', 'licenseFile': 'LICENSE', 'noticeFile': 'NOTICE'},
    'skills': {'demo': 'skills/demo'}, 'layout': {'claudeEntries': True}}
withnotice = root / 'withnotice'
vs.problems.clear(); vs.build_pack('demo', withnotice)
print('NOTICERECORDED',
      'NOTICE' in json.loads((withnotice / 'PROVENANCE.json').read_text())['files'])
pristine = withnotice
case('NOTICEPACK', lambda p: None)
case('NOTICETAMPER', lambda p: (p / 'NOTICE').write_text('Copyright somebody else\n'))

# A rebuild must not leave behind a PACK_MANAGED entry this spec does not produce. The
# builder promoted only what it had built, so a NOTICE from an older spec stayed in the
# pack -- under no hash, because `files` records what the build wrote.
vs.fetch_tree = lambda repo, ref: buf.getvalue()
vs.load_pack = lambda name: {
    'pack': 'demo', 'packRepo': 'x/demo',
    'upstream': {'repo': 'x/y', 'url': 'https://example.invalid', 'ref': 'a' * 40,
                 'license': 'MIT', 'licenseFile': 'LICENSE', 'noticeFile': None},
    'skills': {'demo': 'skills/demo'}, 'layout': {'claudeEntries': True}}
stale = root / 'stale'
vs.problems.clear(); vs.build_pack('demo', stale)
(stale / 'NOTICE').mkdir()
(stale / 'NOTICE' / 'evil.md').write_text('unrecorded\n')
vs.problems.clear(); vs.build_pack('demo', stale)
print('STALEGONE', not (stale / 'NOTICE').exists())
vs.problems.clear(); print(f'STALEVERIFIES rc={vs.verify_pack(stale)}')
PY
)"
  printf '%s' "$out" | grep -q 'BASELINE rc=0' \
      && ok "an untampered pack verifies (exit 0)" \
      || no "an untampered pack did not verify: $out"
  for case in 'CONTENT:edited file content' 'EXTRA:an added file' \
              'CHMOD:a chmod-only change' 'ENTRY:a removed .claude/skills entry' \
              'LICENCE:a deleted LICENSE' 'LOOP:a self-looping .agents/skills' \
              'SCHEMA1:a pack predating file-mode provenance' \
              'NOTICEFILE:a NOTICE this pack does not record' \
              'NOTICEDIR:a directory of content named NOTICE' \
              'GITATTRDIR:a directory of content named .gitattributes' \
              'SYMDIR:a symlink to a directory inside a declared skill' \
              'SYMSKILL:a symlink directly under skills/' \
              'FILESEMPTY:a replaced LICENSE with files emptied to {}' \
              'FILESPOP:a replaced LICENSE with its files entry deleted' \
              'FILESSTRAY:a files entry outside LICENSE/NOTICE/PACK.json/README.md' \
              'BADJSON:an unparseable PROVENANCE.json' \
              'SCHEMA3:a provenance schema newer than this tool' \
              'PROVFIELDS:a rewritten provenance pack name and licence' \
              'PROVPATHS:provenance upstreamPaths disagreeing with PACK.json' \
              'NOTICETAMPER:a tampered NOTICE in a pack that ships one'; do
    token="${case%%:*}"; label="${case#*:}"
    if printf '%s' "$out" | grep -q "$token rc=1"; then ok "--verify-pack rejects $label"
    else no "--verify-pack did NOT reject $label: $out"; fi
  done
  printf '%s' "$out" | grep -q 'GITIGNORE rc=0' \
      && ok "a real .gitignore is not treated as pack content" \
      || no "--verify-pack rejected git's own .gitignore: $out"
  printf '%s' "$out" | grep -q 'NOTICERECORDED True' \
      && ok "a pack whose spec declares a NOTICE records its hash" \
      || no "a declared NOTICE was not recorded under files: $out"
  printf '%s' "$out" | grep -q 'NOTICEPACK rc=0' \
      && ok "a pack that ships a NOTICE still verifies" \
      || no "a pack shipping a NOTICE did not verify: $out"
  printf '%s' "$out" | grep -q 'STALEGONE True' \
      && ok "a rebuild drops an entry this spec no longer produces" \
      || no "a rebuild left a stale NOTICE behind: $out"
  printf '%s' "$out" | grep -q 'STALEVERIFIES rc=0' \
      && ok "and the rebuilt pack verifies afterwards" \
      || no "the rebuilt pack did not verify: $out"
  printf '%s' "$out" | grep -qi 'Traceback' \
      && no "verify_pack raised instead of reporting: $out" \
      || ok "no case raised a traceback out of verify_pack"
fi

# ---------------------------------------------------------------------------------------
group "check.py: a corrupted pack spec is rejected, and the EXIT STATUS is asserted"

# The old pack test re-implemented check_packs' rules in its own inline Python, so it
# passed whatever check_packs did -- including nothing. These run tools/check.py itself
# and look at $?, which is the only thing a caller acts on.

if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent — check.py exit-status tests cannot run"
else
  specfix="$TMPROOT/specfix"
  rm -rf "$specfix"; mkdir -p "$specfix"
  ( cd "$ROOT" && tar -c --exclude=./.git . ) | ( cd "$specfix" && tar -x )
  onespec="$(find "$specfix/packs" -name '*.json' | sort | head -1)"

  python3 "$ROOT/tools/check.py" --root "$specfix" >/dev/null 2>&1
  [ $? -eq 0 ] && ok "check.py exits 0 on an unmodified tree" \
               || no "check.py exits non-zero on an unmodified tree"

  spec_case() {
    local label="$1" script="$2"
    cp "$onespec" "$TMPROOT/spec.bak"
    python3 -c "$script" "$onespec"
    python3 "$ROOT/tools/check.py" --root "$specfix" >/dev/null 2>&1
    local rc=$?
    cp "$TMPROOT/spec.bak" "$onespec"
    [ "$rc" -ne 0 ] && ok "check.py exits non-zero: $label" \
                    || no "check.py exited 0 despite $label"
  }

  spec_case "a branch name where a full commit sha must be" '
import json,sys
p=sys.argv[1]; s=json.load(open(p)); s["upstream"]["ref"]="main"; json.dump(s,open(p,"w"))'
  spec_case "an abbreviated sha where a full one must be" '
import json,sys
p=sys.argv[1]; s=json.load(open(p)); s["upstream"]["ref"]=s["upstream"]["ref"][:12]; json.dump(s,open(p,"w"))'
  spec_case "no layout.claudeEntries, so the pack would deliver nothing" '
import json,sys
p=sys.argv[1]; s=json.load(open(p)); s["layout"].pop("claudeEntries",None); json.dump(s,open(p,"w"))'
  spec_case "a pack skill shadowing a canonical one" '
import json,sys
p=sys.argv[1]; s=json.load(open(p)); s["skills"]["adversarial-review"]="skills/x"; json.dump(s,open(p,"w"))'
  spec_case "a missing upstream licence file, so the pack is not reproducible" '
import json,sys
p=sys.argv[1]; s=json.load(open(p)); s["upstream"]["licenseFile"]=""; json.dump(s,open(p,"w"))'
  spec_case "a spec that is not valid JSON at all" '
import sys
open(sys.argv[1],"w").write("{ not json")'
fi

# ---------------------------------------------------------------------------------------
group "pack builder: a failed promotion rolls back completely"

# The rollback restored entries that had DISPLACED something and forgot entries it had
# newly created, so a failure left a half-promoted pack behind. Here NOTICE does not
# exist in the destination, the promote fails after it lands, and NOTICE must not survive.

if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent — rollback test cannot run"
else
  out="$(cd "$ROOT" && python3 - <<'PY' 2>&1
import importlib.util, io, pathlib, tarfile, tempfile

spec = importlib.util.spec_from_file_location('vs', 'tools/vendor-sync.py')
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)


def archive(notice):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        members = [('up/skills/demo/SKILL.md',
                    '---\nname: demo\ndescription: d\n---\nbody\n'),
                   ('up/LICENSE', 'MIT\n')]
        if notice:
            members.append(('up/NOTICE', 'notice text\n'))
        for name, body in members:
            info = tarfile.TarInfo(name); data = body.encode()
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def spec_for(notice):
    return {'pack': 'demo', 'packRepo': 'x/demo',
            'upstream': {'repo': 'x/y', 'url': 'https://example.invalid', 'ref': 'a' * 40,
                         'license': 'MIT', 'licenseFile': 'LICENSE',
                         'noticeFile': 'NOTICE' if notice else None},
            'skills': {'demo': 'skills/demo'}, 'layout': {'claudeEntries': True}}


dest = pathlib.Path(tempfile.mkdtemp()) / 'pack'
vs.fetch_tree = lambda repo, ref: archive(False)
vs.load_pack = lambda name: spec_for(False)
vs.problems.clear(); vs.build_pack('demo', dest)          # a good pack, with no NOTICE
original = (dest / 'skills' / 'demo' / 'SKILL.md').read_text()

vs.fetch_tree = lambda repo, ref: archive(True)
vs.load_pack = lambda name: spec_for(True)
real_rename = pathlib.Path.rename


def explode(self, target):
    if pathlib.Path(target).name == 'PROVENANCE.json' and '.staging' in str(self):
        raise OSError('simulated failure part-way through the promote')
    return real_rename(self, target)


pathlib.Path.rename = explode
try:
    vs.problems.clear(); vs.build_pack('demo', dest)
    print('BUILD-SUCCEEDED')
except Exception as exc:
    print('BUILD-RAISED', type(exc).__name__)
finally:
    pathlib.Path.rename = real_rename

print('NOTICE-LEFT' if (dest / 'NOTICE').exists() else 'NO-ORPHAN')
print('RESTORED' if (dest / 'skills' / 'demo' / 'SKILL.md').read_text() == original
      else 'LOST')
leftovers = [p.name for p in dest.iterdir() if p.name.startswith('.demo.')]
print('CLEAN' if not leftovers else f'LEFTOVERS {leftovers}')
PY
)"
  printf '%s' "$out" | grep -q 'BUILD-RAISED' \
      && ok "a failed promotion raises rather than reporting success" \
      || no "a failed promotion did not raise: $out"
  printf '%s' "$out" | grep -q 'NO-ORPHAN' \
      && ok "rollback removes an entry it newly created" \
      || no "rollback left a newly created entry behind: $out"
  printf '%s' "$out" | grep -q 'RESTORED' \
      && ok "rollback restores the entry it displaced" \
      || no "rollback lost the previous content: $out"
  printf '%s' "$out" | grep -q 'CLEAN' \
      && ok "rollback leaves no staging or previous directory" \
      || no "rollback left its own scratch directories: $out"
fi

# ---------------------------------------------------------------------------------------
group "bootstrap.sh: --uninstall removes pack links it created, and only those"

# unlink_one only removed links resolving inside the toolkit, so a pack link -- which by
# definition points elsewhere -- survived every uninstall silently. The fix records what
# was linked; these run the real install and the real uninstall against that record, with
# PACK_*_DIR UNSET at uninstall time, which is the normal case and the one a fix that
# guesses the pack directory would miss.

if [ ! -x "$ROOT/local/bootstrap.sh" ]; then
  skip "local/bootstrap.sh not executable"
elif ! command -v jq >/dev/null 2>&1; then
  skip "jq absent — --with-packs cannot read the pack specs"
else
  cfg="$TMPROOT/cfg-cycle"
  packdir="$TMPROOT/cycle-pack"
  first="$(jq -r '.skills | keys[0]' "$ROOT/packs/cloudflare.json" 2>/dev/null)"
  second="$(jq -r '.skills | keys[1]' "$ROOT/packs/cloudflare.json" 2>/dev/null)"
  if [ -z "$first" ] || [ -z "$second" ]; then
    skip "could not read two skill names from packs/cloudflare.json"
  else
    for s in "$first" "$second"; do
      mkdir -p "$packdir/skills/$s"
      printf -- '---\nname: %s\ndescription: fixture\n---\n' "$s" \
        > "$packdir/skills/$s/SKILL.md"
    done
    # A fixture pack must carry real pack metadata from the start: do_packs refuses to
    # link out of a directory --uninstall could not recognise afterwards. Written here
    # rather than after the first install, which is where these two lines used to be.
    printf '{"pack":"cycle"}\n' > "$packdir/PACK.json"
    printf '{"vendoredBy":"tools/vendor-sync.py","pack":"cycle"}\n' > "$packdir/PROVENANCE.json"

    CLAUDE_CONFIG_DIR="$cfg" PACK_CLOUDFLARE_DIR="$packdir" \
      "$ROOT/local/bootstrap.sh" --with-packs >/dev/null 2>&1
    rc=$?
    [ "$rc" -eq 0 ] && ok "install with --with-packs exits 0" \
                    || no "install with --with-packs exited $rc"
    [ -L "$cfg/skills/$first" ] && ok "a pack skill is linked" \
                                || no "the pack skill was not linked"
    [ -f "$cfg/.toolkit-install-state.tsv" ] \
        && ok "the install is recorded in .toolkit-install-state.tsv" \
        || no "no install record was written"

    # The user takes one of them over. It must survive, because it is no longer ours.
    rm -f "$cfg/skills/$second"; printf 'MY OWN SKILL\n' > "$cfg/skills/$second"

    ( unset PACK_CLOUDFLARE_DIR
      CLAUDE_CONFIG_DIR="$cfg" "$ROOT/local/bootstrap.sh" --uninstall >/dev/null 2>&1 )
    rc=$?
    [ "$rc" -eq 0 ] && ok "--uninstall exits 0 with PACK_CLOUDFLARE_DIR unset" \
                    || no "--uninstall exited $rc"
    [ -e "$cfg/skills/$first" ] || [ -L "$cfg/skills/$first" ] \
        && no "a toolkit-created pack link survived --uninstall" \
        || ok "no toolkit-created pack link survives --uninstall"
    [ -f "$cfg/skills/$second" ] \
        && ok "a skill the user replaced with their own file is left alone" \
        || no "--uninstall destroyed the user's own file"
    [ -L "$cfg/skills/adversarial-review" ] \
        && no "a canonical skill link survived --uninstall" \
        || ok "canonical skill links are removed too"

    # THE UPGRADE PATH, which is every install that exists while this is unmerged:
    # linked by a bootstrap.sh that wrote no record, then uninstalled by this one. The
    # fallback used to cover only links resolving inside $TOOLKIT_ROOT, so all 26 pack
    # links survived AND the summary still said "Nothing else was touched". A pack is
    # now recognised at the far end of the link by its own PACK.json + PROVENANCE.json,
    # and a toolkit checkout by its AGENTS.md + tools/check.py -- which also catches a
    # link made by a DIFFERENT checkout, where $TOOLKIT_ROOT cannot help.
    cfg2="$TMPROOT/cfg-norecord"
    mkdir -p "$cfg2/skills" "$cfg2/agents" "$TMPROOT/elsewhere/my-skill"
    printf -- '---\nname: mine\ndescription: not yours\n---\n' \
      > "$TMPROOT/elsewhere/my-skill/SKILL.md"
    ln -s "$packdir/skills/$first"          "$cfg2/skills/$first"
    ln -s "$ROOT/skills/adversarial-review" "$cfg2/skills/adversarial-review"
    ln -s "$ROOT/.claude/agents/critic.md"  "$cfg2/agents/critic.md"
    ln -s "$TMPROOT/elsewhere/my-skill"     "$cfg2/skills/my-own-skill"
    # A link made by a DIFFERENT checkout of this toolkit. $TOOLKIT_ROOT cannot recognise
    # it, which is why the pre-fix fallback left it -- and why a checkout is identified by
    # its own AGENTS.md + tools/check.py rather than by a path comparison.
    # Two links into it, because the answer differs and both answers matter. A checkout of
    # this toolkit installs THIS toolkit's skill names, so a link at one of those names is
    # plausibly one of ours and is removed. A link at a name no version of this toolkit
    # installs is the user's own, wherever it points, and is left alone.
    mine="$(basename -- "$(find "$ROOT/skills" -mindepth 1 -maxdepth 1 -type d | sort | head -1)")"
    mkdir -p "$TMPROOT/other-checkout/tools" \
             "$TMPROOT/other-checkout/skills/$mine" \
             "$TMPROOT/other-checkout/skills/other-skill"
    printf '# AGENTS.md\n' > "$TMPROOT/other-checkout/AGENTS.md"
    # A real checkout, so the marker must really be there: empty files are what the
    # foreign-link cases below use, and they must NOT be recognised.
    cp "$ROOT/tools/check.py" "$TMPROOT/other-checkout/tools/check.py"
    for s in "$mine" other-skill; do
      printf -- '---\nname: %s\ndescription: fixture\n---\n' "$s" \
        > "$TMPROOT/other-checkout/skills/$s/SKILL.md"
    done
    rm -f "$cfg2/skills/$mine"
    ln -s "$TMPROOT/other-checkout/skills/$mine"        "$cfg2/skills/$mine"
    ln -s "$TMPROOT/other-checkout/skills/other-skill"  "$cfg2/skills/other-skill"
    [ -f "$cfg2/.toolkit-install-state.tsv" ] && rm -f "$cfg2/.toolkit-install-state.tsv"

    out="$( unset PACK_CLOUDFLARE_DIR
            CLAUDE_CONFIG_DIR="$cfg2" "$ROOT/local/bootstrap.sh" --uninstall 2>&1 )"
    [ -L "$cfg2/skills/$first" ] \
        && no "no record: a pack link survived --uninstall" \
        || ok "no record: the pack link is removed, recognised by the pack's own metadata"
    [ -L "$cfg2/skills/adversarial-review" ] || [ -L "$cfg2/agents/critic.md" ] \
        && no "no record: a toolkit link survived --uninstall" \
        || ok "no record: toolkit links are removed too"
    [ -L "$cfg2/skills/$mine" ] \
        && no "no record: a link into another checkout of this toolkit survived" \
        || ok "no record: a link into another toolkit checkout is removed too"
    [ -L "$cfg2/skills/other-skill" ] \
        && ok "no record: a link at a name we never install is left alone, even inside a checkout" \
        || no "no record: --uninstall removed a link at a name this toolkit does not install"
    [ -L "$cfg2/skills/my-own-skill" ] \
        && ok "no record: a link of the user's own, into neither, is left alone" \
        || no "no record: --uninstall removed the user's own unrelated symlink"
    # The `other-skill` link above is attributable (it points into a toolkit checkout) and
    # was correctly NOT removed, because its name is not one this toolkit installs. The
    # closing sweep is deliberately broader than the remover, so it reports that link and
    # withholds the claim rather than staying silent about something it declined to touch.
    # That is the trade made after a name-gate failure stranded 13 pack links in silence.
    printf '%s' "$out" | grep -q 'not a name this toolkit installs' \
        && ok "no record: a link it declined to remove is named, not passed over in silence" \
        || no "no record: the declined link was not reported — got: $out"
    printf '%s' "$out" | grep -q 'Nothing else was touched' \
        && no "no record: the summary claimed a clean undo over a link it left behind" \
        || ok "no record: and the clean-undo claim is withheld while it is there"

    # --dry-run must remove nothing and must not count a path twice. It reported
    # "removed 41 link(s)" over a 27-link install, because the record pass and the
    # fallback both counted every path when neither deleted anything.
    cfg3="$TMPROOT/cfg-dry"
    CLAUDE_CONFIG_DIR="$cfg3" PACK_CLOUDFLARE_DIR="$packdir" \
      "$ROOT/local/bootstrap.sh" --with-packs >/dev/null 2>&1
    live="$(find "$cfg3/skills" "$cfg3/agents" -maxdepth 1 -type l 2>/dev/null | wc -l)"
    out="$( unset PACK_CLOUDFLARE_DIR
            CLAUDE_CONFIG_DIR="$cfg3" "$ROOT/local/bootstrap.sh" --uninstall --dry-run 2>&1 )"
    claimed="$(printf '%s' "$out" | sed -n 's/^removed \([0-9]*\) link(s).*/\1/p')"
    still="$(find "$cfg3/skills" "$cfg3/agents" -maxdepth 1 -type l 2>/dev/null | wc -l)"
    [ "$still" -eq "$live" ] \
        && ok "--dry-run --uninstall removes nothing ($still links before and after)" \
        || no "--dry-run --uninstall removed links: $live -> $still"
    [ -n "$claimed" ] && [ "$claimed" -le "$live" ] \
        && ok "--dry-run --uninstall counts no path twice ($claimed <= $live)" \
        || no "--dry-run --uninstall claimed $claimed of $live links"

    # A BROKEN link -- the pack checkout was moved or deleted after install. link_owner
    # reads the far end, so there is nothing to read and nothing to attribute it by. It
    # used to be invisible to the remover AND to the counter added to keep the summary
    # honest, so the run printed a clean undo over links it had created itself.
    cfg4="$TMPROOT/cfg-broken"; pk4="$TMPROOT/pack-that-vanishes"
    mkdir -p "$pk4/skills/$first"
    printf -- '---\nname: %s\ndescription: fixture\n---\n' "$first" \
      > "$pk4/skills/$first/SKILL.md"
    printf '{"pack":"cycle"}\n' > "$pk4/PACK.json"
    printf '{"vendoredBy":"tools/vendor-sync.py","pack":"cycle"}\n' > "$pk4/PROVENANCE.json"
    CLAUDE_CONFIG_DIR="$cfg4" PACK_CLOUDFLARE_DIR="$pk4" \
      "$ROOT/local/bootstrap.sh" --with-packs >/dev/null 2>&1
    rm -f "$cfg4/.toolkit-install-state.tsv"
    rm -rf "$pk4"
    rc=0
    out="$( unset PACK_CLOUDFLARE_DIR
            CLAUDE_CONFIG_DIR="$cfg4" "$ROOT/local/bootstrap.sh" --uninstall 2>&1 )" || rc=$?
    printf '%s' "$out" | grep -q 'Nothing else was touched' \
        && no "a broken link remains and the summary still claims a clean undo" \
        || ok "a broken link withholds the clean-undo claim"
    printf '%s' "$out" | grep -q 'no longer exists' \
        && ok "the broken link is named, with the target that is gone" \
        || no "the broken link was not reported — got: $out"
    [ "$rc" -ne 0 ] \
        && ok "--uninstall exits non-zero when it could not undo cleanly (rc=$rc)" \
        || no "--uninstall reported success although it did not undo cleanly"
    [ -L "$cfg4/skills/$first" ] \
        && ok "the broken link is left alone, not guessed at and deleted" \
        || no "--uninstall deleted a link it could not attribute"

    # The SAME directory, spelled differently. Every recorded destination and every path
    # compared later is built from $CLAUDE_DIR, so a trailing slash used to make the two
    # passes disagree: a link reported "left alone" was then deleted, and --dry-run
    # claimed 27 removals over 14 links.
    cfg5="$TMPROOT/cfg-spelling"
    CLAUDE_CONFIG_DIR="$cfg5" "$ROOT/local/bootstrap.sh" >/dev/null 2>&1
    live5="$(find "$cfg5/skills" "$cfg5/agents" -maxdepth 1 -type l 2>/dev/null | wc -l)"
    rm -f "$cfg5/skills/adversarial-review"
    ln -s "$ROOT/skills/evidence-verification" "$cfg5/skills/adversarial-review"
    out="$(CLAUDE_CONFIG_DIR="$cfg5/" "$ROOT/local/bootstrap.sh" --uninstall --dry-run 2>&1)"
    claimed="$(printf '%s' "$out" | sed -n 's/^removed \([0-9]*\) link(s).*/\1/p')"
    [ -n "$claimed" ] && [ "$claimed" -le "$live5" ] \
        && ok "a trailing slash does not double-count ($claimed <= $live5)" \
        || no "a trailing slash made --dry-run claim $claimed of $live5 links"
    CLAUDE_CONFIG_DIR="$cfg5/" "$ROOT/local/bootstrap.sh" --uninstall >/dev/null 2>&1
    [ -L "$cfg5/skills/adversarial-review" ] \
        && ok "a trailing slash still leaves a repointed link alone" \
        || no "a trailing slash deleted a link that was reported left alone"

    # FALSE POSITIVE. Two EMPTY files named PACK.json and PROVENANCE.json, and an empty
    # AGENTS.md beside an empty tools/check.py, used to be enough to delete somebody
    # else's symlink. The markers are read now, not counted.
    cfg6="$TMPROOT/cfg-foreign"; mkdir -p "$cfg6/skills"
    theirs="$TMPROOT/their-pack"; mkdir -p "$theirs/skills/theirskill"
    : > "$theirs/PACK.json"; : > "$theirs/PROVENANCE.json"
    printf -- '---\nname: theirskill\ndescription: not ours\n---\n' \
      > "$theirs/skills/theirskill/SKILL.md"
    lint="$TMPROOT/their-repo"; mkdir -p "$lint/tools" "$lint/skills/lint"
    : > "$lint/AGENTS.md"; : > "$lint/tools/check.py"
    printf -- '---\nname: lint\ndescription: not ours\n---\n' > "$lint/skills/lint/SKILL.md"
    ln -s "$theirs/skills/theirskill" "$cfg6/skills/theirs"
    ln -s "$lint/skills/lint"         "$cfg6/skills/my-linter"
    CLAUDE_CONFIG_DIR="$cfg6" "$ROOT/local/bootstrap.sh" --uninstall >/dev/null 2>&1
    [ -L "$cfg6/skills/theirs" ] \
        && ok "an empty PACK.json + PROVENANCE.json is not a pack" \
        || no "--uninstall deleted a foreign link on two empty marker files"
    [ -L "$cfg6/skills/my-linter" ] \
        && ok "an empty AGENTS.md + tools/check.py is not this toolkit" \
        || no "--uninstall deleted a foreign link on two empty marker files"

    # The toolkit marker is a token in tools/check.py. Renaming it there would silently
    # stop uninstall recognising a checkout, so assert the contract from both ends.
    # THE FIRST INSTALL is the run that creates the config directory, and canonicalisation
    # used to be skipped exactly then -- `cd` was guarded by `[ -d ]`. Every recorded
    # destination then carried the raw spelling while every later run canonicalised, which
    # is the same disagreement the trailing-slash case above covers. Six spellings, each
    # installing into a directory that does not yet exist.
    spellings_bad=0
    for spell in 'cfg-sp/x' 'cfg-sp/x/' 'cfg-sp/x//' 'cfg-sp/./x' 'cfg-sp/../cfg-sp/x' 'cfg-sp//x'; do
      rm -rf "$TMPROOT/cfg-sp"; mkdir -p "$TMPROOT/cfg-sp"
      ( cd "$TMPROOT" && CLAUDE_CONFIG_DIR="$spell" "$ROOT/local/bootstrap.sh" >/dev/null 2>&1 )
      n="$(find "$TMPROOT/cfg-sp/x/skills" "$TMPROOT/cfg-sp/x/agents" -maxdepth 1 -type l 2>/dev/null | wc -l)"
      c="$( cd "$TMPROOT" && CLAUDE_CONFIG_DIR="$spell" "$ROOT/local/bootstrap.sh" \
              --uninstall --dry-run 2>&1 | sed -n 's/^removed \([0-9]*\) link(s).*/\1/p' )"
      # -eq, not -le: `removed 0` is the pre-fix failure mode this test exists to
      # catch, and -le admitted it. The preview must name every link installed.
      if [ "$n" -gt 0 ] && [ -n "$c" ] && [ "$c" -eq "$n" ]; then :
      else spellings_bad=$((spellings_bad + 1)); fi
    done
    [ "$spellings_bad" -eq 0 ] \
        && ok "a first install canonicalises its path, in all six spellings" \
        || no "$spellings_bad of 6 spellings double-counted at uninstall"
    rm -rf "$TMPROOT/cfg-sp"

    # A link the USER made, at a name of their own, into their own pack checkout. Every
    # link this script creates is NAME -> .../NAME, so a link whose two ends disagree is
    # not one of ours whatever it points into. It used to be deleted by a run whose
    # record was complete and never mentioned it -- while the header promised the
    # opposite in three places.
    cfg7="$TMPROOT/cfg-theirname"
    CLAUDE_CONFIG_DIR="$cfg7" "$ROOT/local/bootstrap.sh" >/dev/null 2>&1
    ln -s "$packdir/skills/$first" "$cfg7/skills/a-name-of-my-own"
    rc=0
    out="$(CLAUDE_CONFIG_DIR="$cfg7" "$ROOT/local/bootstrap.sh" --uninstall 2>&1)" || rc=$?
    [ -L "$cfg7/skills/a-name-of-my-own" ] \
        && ok "a link at the user's own name is not ours, whatever it points into" \
        || no "--uninstall deleted a link whose name it never assigned"
    # Three conditions, because the summary line alone carries no information: it
    # prints just as happily over a run that removed nothing. The run must have
    # exited 0, removed the links it owns, and still claimed a clean undo.
    n7="$(printf '%s' "$out" | sed -n 's/^removed \([0-9]*\) link(s).*/\1/p')"
    [ "$rc" -eq 0 ] && [ -n "$n7" ] && [ "$n7" -gt 0 ] \
      && printf '%s' "$out" | grep -q 'Nothing else was touched' \
        && ok "and it is not counted against the clean-undo claim either" \
        || no "the user's own link was counted as one we failed to remove (rc=$rc removed=${n7:-?}) — got: $out"

    # A dead symlink of the USER's own must not make a clean uninstall report failure.
    cfg8="$TMPROOT/cfg-theirdead"; mkdir -p "$cfg8/skills"
    ln -s /nowhere/at/all "$cfg8/skills/their-dead-link"
    CLAUDE_CONFIG_DIR="$cfg8" "$ROOT/local/bootstrap.sh" >/dev/null 2>&1
    rc=0
    out="$(CLAUDE_CONFIG_DIR="$cfg8" "$ROOT/local/bootstrap.sh" --uninstall 2>&1)" || rc=$?
    [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q 'Nothing else was touched' \
        && ok "a foreign dead symlink does not make a clean undo report failure" \
        || no "a foreign dead symlink made --uninstall report failure (rc=$rc)"
    [ -L "$cfg8/skills/their-dead-link" ] \
        && ok "and it is left alone" || no "--uninstall removed a foreign dead symlink"

    # --dry-run must PREVIEW the broken-link outcome, not promise a clean undo the real
    # run will not deliver.
    cfg9="$TMPROOT/cfg-drybroken"; pk9="$TMPROOT/pack-vanishes-2"
    mkdir -p "$pk9/skills/$first"
    printf -- '---\nname: %s\ndescription: fixture\n---\n' "$first" > "$pk9/skills/$first/SKILL.md"
    printf '{"pack":"cycle"}\n' > "$pk9/PACK.json"
    printf '{"vendoredBy":"tools/vendor-sync.py","pack":"cycle"}\n' > "$pk9/PROVENANCE.json"
    CLAUDE_CONFIG_DIR="$cfg9" PACK_CLOUDFLARE_DIR="$pk9" \
      "$ROOT/local/bootstrap.sh" --with-packs >/dev/null 2>&1
    rm -f "$cfg9/.toolkit-install-state.tsv"; rm -rf "$pk9"
    out="$( unset PACK_CLOUDFLARE_DIR
            CLAUDE_CONFIG_DIR="$cfg9" "$ROOT/local/bootstrap.sh" --uninstall --dry-run 2>&1 )"
    printf '%s' "$out" | grep -q 'Nothing else was touched' \
        && no "--dry-run promised a clean undo the real run will not deliver" \
        || ok "--dry-run previews the broken-link outcome instead of promising a clean undo"

    marker="$(sed -n "s/^TOOLKIT_MARKER='\(.*\)'$/\1/p" "$ROOT/local/bootstrap.sh")"
    [ -n "$marker" ] && grep -q "$marker" "$ROOT/tools/check.py" \
        && ok "bootstrap.sh's toolkit marker ($marker) is still in tools/check.py" \
        || no "bootstrap.sh looks for '$marker' in tools/check.py and it is not there"
  fi
fi

# ---------------------------------------------------------------------------------------
group "bootstrap.sh: canonical_path normalises a path that does not exist yet"

# The install record stores an absolute destination per link, and --uninstall matches on
# that string. So two runs that spell CLAUDE_CONFIG_DIR differently must canonicalise to
# the SAME string or the record is useless. The function is extracted from the production
# script and executed, not reimplemented here: a copy would stop testing the real one.
cp_fn="$TMPROOT/canonical_path.sh"
sed -n '/^canonical_path() {/,/^}/p' "$ROOT/local/bootstrap.sh" > "$cp_fn"
if ! grep -q '^canonical_path() {' "$cp_fn"; then
  no "could not extract canonical_path() from local/bootstrap.sh"
else
  ok "canonical_path() extracted from the production script"

  # Every row below is a spelling the previous implementation got WRONG, measured against
  # b5181f7: it returned '//', '//ztk', '//ztk/./x' and '/tmp/a/../b' respectively. A
  # doubled leading slash and a literal '.' or '..' component are different STRINGS from
  # the one a later run produces once the directory exists, which is the whole failure.
  cp_bad=0
  while IFS='|' read -r inp want; do
    [ -n "$inp" ] || continue
    got="$(bash -c ". '$cp_fn'; canonical_path '$inp'" 2>/dev/null)"
    [ "$got" = "$want" ] || { cp_bad=$((cp_bad + 1)); printf '        %s -> %s, wanted %s\n' "$inp" "$got" "$want"; }
  done <<'ROWS'
//|/
///|/
/ztk|/ztk
/ztk/./x|/ztk/x
/tmp/a/../b|/tmp/b
/tmp//x//y|/tmp/x/y
/tmp/|/tmp
ROWS
  [ "$cp_bad" -eq 0 ] \
      && ok "7 spellings of a not-yet-existing path each canonicalise to one form" \
      || no "$cp_bad of 7 spellings canonicalised wrongly"

  # bootstrap.sh runs under `set -euo pipefail`, while the one call site sits on the
  # left of an `||`, where errexit is suppressed. So nothing else in this suite would
  # notice if the function started returning non-zero on an ordinary path -- the next
  # caller added would be the one to find out. This pins it.
  #
  # Honest about what it is: this is NOT a regression test for a defect that was here.
  # The `[ ... ] && resolved=""` it replaced was checked against this same assertion and
  # PASSED, because bash does not abort on a failing `&&` list mid-body. It would abort
  # if that list were the function's last command.
  cp_rc=0
  cp_out="$(bash -euo pipefail -c ". '$cp_fn'; canonical_path /tmp/a/../b; :" 2>&1)" || cp_rc=$?
  [ "$cp_rc" -eq 0 ] && [ "$cp_out" = "/tmp/b" ] \
      && ok "canonical_path succeeds when called under set -e outside a condition" \
      || no "canonical_path aborted under set -e (rc=$cp_rc, out='$cp_out')"

  # An ancestor it cannot enter. The previous version let the failed `cd` substitute an
  # EMPTY prefix and returned 0, so the suffix alone became the answer: measured at
  # b5181f7, CLAUDE_CONFIG_DIR under an unreadable directory resolved to a path rooted at
  # / that had nothing to do with the one asked for, and the script would have installed
  # there.
  #
  # The guard below is about THIS SUITE'S OWN uid, not about whether the machine has an
  # unprivileged account. The case needs a process that cannot traverse the directory, and
  # the way it gets one is `setpriv --reuid=65534`, which drops privileges -- an operation
  # only root may perform. So the three conditions are: the suite is running as root, so it
  # can drop; `setpriv` exists; and `nobody` exists to drop to. Any non-root runner fails
  # the first condition and skips, even though it is itself unprivileged and `nobody` is
  # present. That is why a GitHub-hosted `ubuntu-latest` job, which runs as an ordinary
  # user, reports one skip here while a root container reports none. The skip is a
  # statement about the suite's privileges, not about the machine's accounts.
  if [ "$(id -u)" -eq 0 ] && command -v setpriv >/dev/null 2>&1 \
     && getent passwd nobody >/dev/null 2>&1; then
    locked="$TMPROOT/locked"; mkdir -p "$locked/inner"; chmod 755 "$TMPROOT"; chmod 000 "$locked"
    cp_out="$(setpriv --reuid=65534 --regid=65534 --clear-groups \
                bash -c ". '$cp_fn'; canonical_path '$locked/inner/x'" 2>/dev/null)"; cp_rc=$?
    chmod 755 "$locked"
    [ "$cp_rc" -ne 0 ] && [ -z "$cp_out" ] \
        && ok "an ancestor it cannot enter is a failure, not a path rooted at /" \
        || no "an unenterable ancestor returned rc=$cp_rc and '$cp_out' instead of failing"
  else
    skip "this suite is not running as root, or setpriv/nobody is missing — it cannot drop privileges to make an ancestor unenterable"
  fi
fi

# ---------------------------------------------------------------------------------------
group "bootstrap.sh: --with-packs refuses a PACK_*_DIR that is not a pack"

# The installer's acceptance rule and the uninstaller's recognition rule have to be the
# SAME rule. Linking out of a directory carrying no PACK.json + PROVENANCE.json creates
# links --uninstall cannot attribute afterwards -- links that would then be counted as a
# failed undo forever. Refuse at install time instead.
if [ ! -x "$ROOT/local/bootstrap.sh" ]; then
  skip "local/bootstrap.sh not executable"
elif ! command -v jq >/dev/null 2>&1; then
  skip "jq absent — --with-packs cannot read the pack specs"
else
  notpack="$TMPROOT/not-a-pack"; cfgnp="$TMPROOT/cfg-notpack"
  npfirst="$(jq -r '.skills | keys[0]' "$ROOT/packs/cloudflare.json" 2>/dev/null)"
  if [ -z "$npfirst" ]; then
    skip "could not read a skill name from packs/cloudflare.json"
  else
    mkdir -p "$notpack/skills/$npfirst"
    printf -- '---\nname: %s\ndescription: fixture\n---\n' "$npfirst" \
      > "$notpack/skills/$npfirst/SKILL.md"
    # Real content of somebody's own, so a wrong answer here is a real loss.
    printf 'my own notes\n' > "$notpack/README.md"

    rc=0
    out="$(CLAUDE_CONFIG_DIR="$cfgnp" PACK_CLOUDFLARE_DIR="$notpack" \
           "$ROOT/local/bootstrap.sh" --with-packs 2>&1)" || rc=$?
    [ "$rc" -ne 0 ] && ok "--with-packs exits non-zero on a PACK_*_DIR that is not a pack" \
                    || no "--with-packs accepted a directory with no pack metadata (rc=$rc)"
    printf '%s' "$out" | grep -q 'is not a pack this tooling built' \
        && ok "and it says which variable and why" \
        || no "the refusal did not name the variable: $out"
    [ -e "$cfgnp/skills/$npfirst" ] || [ -L "$cfgnp/skills/$npfirst" ] \
        && no "it linked out of a directory --uninstall could not recognise" \
        || ok "nothing was linked out of it"
    [ -f "$notpack/README.md" ] \
        && ok "the refused directory is untouched" \
        || no "the refused directory lost content"
  fi
fi

# ---------------------------------------------------------------------------------------
group "bootstrap.sh: a broken link is judged by name as well as by shape"

# A BROKEN link cannot be judged at the far end -- the target is gone. Shape alone was not
# enough: `ln -s <target>` with no second argument creates NAME -> .../NAME, so ANY dead
# symlink of the user's own passed that test and made a clean uninstall report a failed
# undo. It must also be a name this toolkit installs.
if [ ! -x "$ROOT/local/bootstrap.sh" ]; then
  skip "local/bootstrap.sh not executable"
else
  # Theirs: correct shape, a name this toolkit never installs.
  cfgbn="$TMPROOT/cfg-brokenname"; mkdir -p "$cfgbn/skills"
  ln -s "$TMPROOT/gone-away/my-notes" "$cfgbn/skills/my-notes"
  CLAUDE_CONFIG_DIR="$cfgbn" "$ROOT/local/bootstrap.sh" >/dev/null 2>&1
  rc=0
  out="$(CLAUDE_CONFIG_DIR="$cfgbn" "$ROOT/local/bootstrap.sh" --uninstall 2>&1)" || rc=$?
  [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q 'Nothing else was touched' \
      && ok "a dead link at a name this toolkit never installs is not its failed undo" \
      || no "a foreign dead link at our shape was counted against the undo (rc=$rc): $out"
  [ -L "$cfgbn/skills/my-notes" ] \
      && ok "and it is left alone" || no "--uninstall removed a foreign dead link"

  # Ours: same shape, a name this toolkit DOES install. This one must still be counted,
  # or the name gate would have turned the F5 fix into a way of hiding real leftovers.
  cfgbo="$TMPROOT/cfg-brokenours"; mkdir -p "$cfgbo/skills"
  ln -s "$TMPROOT/gone-away/adversarial-review" "$cfgbo/skills/adversarial-review"
  rc=0
  out="$(CLAUDE_CONFIG_DIR="$cfgbo" "$ROOT/local/bootstrap.sh" --uninstall 2>&1)" || rc=$?
  printf '%s' "$out" | grep -q 'Nothing else was touched' \
      && no "a dead link at one of our own names was passed off as a clean undo" \
      || ok "a dead link at one of our own names still withholds the clean-undo claim"
  [ "$rc" -ne 0 ] \
      && ok "and the run exits non-zero" \
      || no "the run reported success over a leftover it created"
fi

# ---------------------------------------------------------------------------------------
group "bootstrap.sh: install and uninstall ask ONE question of ONE input"

# link_owner_of_dir walks a bounded number of levels. The installer used to ask it about
# "$dir" and the uninstaller about "$dir/skills/<skill>", two levels deeper, so the two
# windows differed by two: a PACK_*_DIR three levels below the pack root was ACCEPTED on
# install and unattributable on uninstall. Measured at 46d94d8: 13 links left behind under
# "removed 14 link(s), left 0 alone. Nothing else was touched." -- the original MAJOR 1
# output verbatim, exit 0 included.
if [ ! -x "$ROOT/local/bootstrap.sh" ]; then
  skip "local/bootstrap.sh not executable"
elif ! command -v jq >/dev/null 2>&1; then
  skip "jq absent — --with-packs cannot read the pack specs"
else
  d1first="$(jq -r '.skills | keys[0]' "$ROOT/packs/cloudflare.json" 2>/dev/null)"
  if [ -z "$d1first" ]; then
    skip "could not read a skill name from packs/cloudflare.json"
  else
    depth_bad=0; depth_detail=""
    for depth in 0 1 2 3 4; do
      pkd="$TMPROOT/depth$depth"; rm -rf "$pkd"; mkdir -p "$pkd/skills/$d1first"
      printf -- '---\nname: %s\ndescription: fixture\n---\n' "$d1first" \
        > "$pkd/skills/$d1first/SKILL.md"
      printf '{"pack":"cloudflare"}\n' > "$pkd/PACK.json"
      printf '{"vendoredBy":"tools/vendor-sync.py","pack":"cloudflare"}\n' > "$pkd/PROVENANCE.json"
      sub="$pkd"; i=0
      while [ "$i" -lt "$depth" ]; do sub="$sub/n$i"; i=$((i + 1)); done
      if [ "$depth" -gt 0 ]; then mkdir -p "$sub"; cp -a "$pkd/skills" "$sub/skills"; fi
      cfgd="$TMPROOT/cfg-depth$depth"; rm -rf "$cfgd"
      PACK_CLOUDFLARE_DIR="$sub" CLAUDE_CONFIG_DIR="$cfgd" \
        "$ROOT/local/bootstrap.sh" --with-packs >/dev/null 2>&1
      # The no-record case is the one the fallback exists for, and the one that failed.
      rm -f "$cfgd/.toolkit-install-state.tsv"
      ( unset PACK_CLOUDFLARE_DIR
        CLAUDE_CONFIG_DIR="$cfgd" "$ROOT/local/bootstrap.sh" --uninstall >/dev/null 2>&1 )
      left="$(find "$cfgd/skills" "$cfgd/agents" -maxdepth 1 -type l 2>/dev/null | wc -l | tr -d ' ')"
      if [ "$left" -ne 0 ]; then
        depth_bad=$((depth_bad + 1)); depth_detail="$depth_detail depth=$depth:$left"
      fi
      rm -rf "$pkd" "$cfgd"
    done
    [ "$depth_bad" -eq 0 ] \
        && ok "no PACK_*_DIR depth leaves a link --uninstall cannot attribute (0-4)" \
        || no "links survived --uninstall at$depth_detail"
  fi
fi

# ---------------------------------------------------------------------------------------
group "bootstrap.sh: the remover applies the same three-way gate it documents"

# Shape plus owner was not enough. A skill directory of the USER's own, inside their own
# pack checkout, linked at its own matching name, satisfied both -- and was deleted under
# "Nothing else was touched". local/README.md promised a name gate the remover never
# applied; only the broken-link counter did.
if [ ! -x "$ROOT/local/bootstrap.sh" ]; then
  skip "local/bootstrap.sh not executable"
else
  pk3="$TMPROOT/pack-with-mine"; cfg3g="$TMPROOT/cfg-gate"; rm -rf "$pk3" "$cfg3g"
  mkdir -p "$pk3/skills/my-private-skill"
  printf -- '---\nname: my-private-skill\ndescription: mine\n---\n' \
    > "$pk3/skills/my-private-skill/SKILL.md"
  printf '{"pack":"cloudflare"}\n' > "$pk3/PACK.json"
  printf '{"vendoredBy":"tools/vendor-sync.py","pack":"cloudflare"}\n' > "$pk3/PROVENANCE.json"
  CLAUDE_CONFIG_DIR="$cfg3g" "$ROOT/local/bootstrap.sh" >/dev/null 2>&1
  ln -s "$pk3/skills/my-private-skill" "$cfg3g/skills/my-private-skill"
  rm -f "$cfg3g/.toolkit-install-state.tsv"
  rc=0
  out="$(CLAUDE_CONFIG_DIR="$cfg3g" "$ROOT/local/bootstrap.sh" --uninstall 2>&1)" || rc=$?
  [ -L "$cfg3g/skills/my-private-skill" ] \
      && ok "a link at a name this toolkit does not install survives, whatever it points into" \
      || no "--uninstall deleted the user's own skill link inside their pack checkout"
  n3g="$(printf '%s' "$out" | sed -n 's/^removed \([0-9]*\) link(s).*/\1/p')"
  [ -n "$n3g" ] && [ "$n3g" -gt 0 ] \
      && ok "and the toolkit's own links are still removed around it" \
      || no "the preserved link stopped the run removing its own (removed=${n3g:-?})"
  # It is REPORTED rather than silently skipped. The remover declines it on the name gate;
  # the closing sweep sees a superset of what the remover acts on, precisely so that a
  # gate failure cannot be silent -- which is how a reformatted pack spec stranded 13
  # links under "Nothing else was touched" at a91ec08.
  printf '%s' "$out" | grep -q 'not a name this toolkit installs' \
      && ok "and it is named in the summary rather than passed over" \
      || no "the preserved link was not reported (rc=$rc) — got: $out"
fi

# ---------------------------------------------------------------------------------------
group "the claim scan covers the undo family as well as the plugin family"

# This started as a shell grep in this file, and the critic walked past it nine ways:
# "inside this checkout", "inside the repository", "never ... outside", a sentence with no
# word "uninstall" at all, a full stop inside the match window, a second file named
# test.sh (--exclude is a basename glob), a .toml adapter and an extensionless file
# (neither in the --include list), and the word "said" anywhere on the line retiring the
# hit. It is now a rule in tools/_claim_scan.py, which walks every text file by relative
# path and scans by paragraph. These ten plants prove the rule fires; the suite's own
# PROBLEMS 0 assertion proves the tree is clean.
if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent — cannot run the claim scan"
else
  undo_tree="$TMPROOT/undo-scan"; rm -rf "$undo_tree"; mkdir -p "$undo_tree"
  ( cd "$ROOT" && tar -c --exclude=./.git . ) | ( cd "$undo_tree" && tar -x )
  undo_missed=0; undo_n=0; undo_hard=0
  while IFS='|' read -r target text; do
    [ -n "$target" ] || continue
    undo_n=$((undo_n + 1))
    mkdir -p "$undo_tree/$(dirname "$target")"
    cp -- "$undo_tree/$target" "$undo_tree/$target.bak" 2>/dev/null || : > "$undo_tree/$target.bak"
    printf '\n%s\n' "$text" >> "$undo_tree/$target"
    scanout="$( cd "$undo_tree" && python3 tools/_claim_scan.py 2>/dev/null )"
    got="$(printf '%s' "$scanout" | sed -n 's/^ADVISORIES //p')"
    hard="$(printf '%s' "$scanout" | sed -n 's/^PROBLEMS //p')"
    [ "${got:-0}" -gt 0 ] || { undo_missed=$((undo_missed + 1)); printf '        missed: %s\n' "$text"; }
    [ "${hard:-0}" -eq 0 ] || { undo_hard=$((undo_hard + 1)); printf '        gated: %s\n' "$text"; }
    mv -- "$undo_tree/$target.bak" "$undo_tree/$target" 2>/dev/null || rm -f -- "$undo_tree/$target"
  done <<'PLANTS'
docs/host-integration.md|`--uninstall` removes only links resolving inside this checkout.
docs/host-integration.md|`--uninstall` removes only links resolving inside the repository.
docs/host-integration.md|`--uninstall` never touches anything outside this repository.
docs/host-integration.md|The undo removes only links resolving inside this repository.
docs/host-integration.md|`--uninstall` is safe. It removes only links resolving inside this repository.
docs/host-integration.md|As said above, `--uninstall` removes only links resolving inside this repository.
local/test.sh|# --uninstall removes only links resolving inside this repository.
.codex/agents/critic.toml|# --uninstall removes only links resolving inside this repository.
local/INSTALL|--uninstall removes only links resolving inside this repository.
local/README.md|`--uninstall` removes only links resolving inside this repository.
PLANTS
  [ "$undo_missed" -eq 0 ] \
      && ok "$undo_n phrasings and locations of the undo claim are all reported" \
      || no "$undo_missed of $undo_n phrasings of the undo claim were missed"
  # This family lives in the same free-form prose pass as the plugin one and is demoted
  # with it: it REPORTS all ten and gates on none. Its own record is better -- 10 of 10
  # here, 10 of 10 missed at eda2da4 -- but a prose regex is not a thing to fail a suite on.
  [ "$undo_hard" -eq 0 ] \
      && ok "and none of them is counted as a hard problem" \
      || no "$undo_hard of $undo_n undo plants still gate the suite"
  rm -rf "$undo_tree"
fi

# ---------------------------------------------------------------------------------------
group "vendor-sync.py: --verify-pack is exact in BOTH directions"

# Everything else walks PACK.json's skill list and asks whether each declared skill is
# intact -- which says nothing about a skill that is present and NOT declared. A 14th
# skill directory plus its own .claude/skills entry verified CLEAN, and packs/README.md
# calls those entries the only route by which a pack delivers anything to a Project.
if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent"
else
  vpd="$TMPROOT/exact-pack"; rm -rf "$vpd"
  ( cd "$ROOT" && python3 - "$vpd" <<'PY'
import importlib.util, io, json, pathlib, sys, tarfile

spec = importlib.util.spec_from_file_location('vs', 'tools/vendor-sync.py')
vs = importlib.util.module_from_spec(spec); spec.loader.exec_module(vs)

def archive():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for name, body in [('up/skills/demo/SKILL.md',
                            '---\nname: demo\ndescription: d\n---\nbody\n'),
                           ('up/LICENSE', 'MIT\n')]:
            info = tarfile.TarInfo(name); data = body.encode()
            info.size = len(data); info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()

pack = {'pack': 'demo', 'packRepo': 'x/demo',
        'upstream': {'repo': 'x/y', 'url': 'https://example.invalid', 'ref': 'a' * 40,
                     'license': 'MIT', 'licenseFile': 'LICENSE', 'noticeFile': None},
        'skills': {'demo': 'skills/demo'}, 'layout': {'claudeEntries': True}}
vs.fetch_tree = lambda repo, ref: archive()
vs.load_pack = lambda name: pack
vs.problems.clear()
vs.build_pack('demo', pathlib.Path(sys.argv[1]))
PY
  ) >/dev/null 2>&1
  if [ ! -f "$vpd/PACK.json" ]; then
    skip "could not build the fixture pack"
  else
    ( cd "$ROOT" && python3 tools/vendor-sync.py --verify-pack --into "$vpd" ) >/dev/null 2>&1
    [ $? -eq 0 ] && ok "the fixture pack verifies clean" \
                 || no "the fixture pack does not verify clean to begin with"

    mkdir -p "$vpd/skills/undeclared"
    printf -- '---\nname: undeclared\ndescription: not in the spec\n---\nbody\n' \
      > "$vpd/skills/undeclared/SKILL.md"
    ( cd "$ROOT" && python3 tools/vendor-sync.py --verify-pack --into "$vpd" ) >/dev/null 2>&1
    [ $? -ne 0 ] && ok "a skill present but not declared in PACK.json is rejected" \
                 || no "--verify-pack passed a pack carrying an undeclared skill"

    ln -s ../../skills/undeclared "$vpd/.claude/skills/undeclared"
    vpout="$( cd "$ROOT" && python3 tools/vendor-sync.py --verify-pack --into "$vpd" 2>&1 )"
    vprc=$?
    [ "$vprc" -ne 0 ] && printf '%s' "$vpout" | grep -q 'harness entry' \
        && ok "and its harness entry is named separately, as the delivery route" \
        || no "the undeclared .claude/skills entry was not reported (rc=$vprc)"
    rm -rf "$vpd"
  fi
fi

# ---------------------------------------------------------------------------------------
group "bootstrap.sh: a gate failure is loud, never a silent leftover"

# The name gate added to the remover was a REGRESSION until this. Three ways it went wrong,
# all measured at a91ec08, all producing the original MAJOR 1 output -- "removed 14 link(s),
# left 0 alone. Nothing else was touched.", exit 0 -- over links this script had created.
if [ ! -x "$ROOT/local/bootstrap.sh" ]; then
  skip "local/bootstrap.sh not executable"
elif ! command -v jq >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
  skip "jq or python3 absent — the gate's own fixtures need them"
else
  g6first="$(jq -r '.skills | keys[0]' "$ROOT/packs/cloudflare.json" 2>/dev/null)"
  g6second="$(jq -r '.skills | keys[1]' "$ROOT/packs/cloudflare.json" 2>/dev/null)"
  g6pack="$TMPROOT/g6-pack"; rm -rf "$g6pack"
  mkdir -p "$g6pack/skills/$g6first"
  printf -- '---\nname: %s\ndescription: fixture\n---\n' "$g6first" \
    > "$g6pack/skills/$g6first/SKILL.md"
  printf '{"pack":"cloudflare"}\n' > "$g6pack/PACK.json"
  printf '{"vendoredBy":"tools/vendor-sync.py","pack":"cloudflare"}\n' > "$g6pack/PROVENANCE.json"

  # (a) A pack spec reformatted with json.dumps. Valid JSON, accepted by check.py, and the
  #     line-oriented sed that used to read the names finds none in it.
  g6tree="$TMPROOT/g6-tree"; rm -rf "$g6tree"; mkdir -p "$g6tree"
  ( cd "$ROOT" && tar -c --exclude=./.git . ) | ( cd "$g6tree" && tar -x )
  python3 -c 'import json,sys;p=sys.argv[1];b=json.load(open(p));open(p,"w").write(json.dumps(b))' \
    "$g6tree/packs/cloudflare.json"
  python3 "$g6tree/tools/check.py" --root "$g6tree" >/dev/null 2>&1 \
      && ok "a compactly-reformatted pack spec is still accepted by check.py" \
      || no "the fixture is wrong: check.py rejects the reformatted spec"
  g6cfg="$TMPROOT/g6-cfg-a"; rm -rf "$g6cfg"
  PACK_CLOUDFLARE_DIR="$g6pack" CLAUDE_CONFIG_DIR="$g6cfg" \
    "$g6tree/local/bootstrap.sh" --with-packs >/dev/null 2>&1
  rm -f "$g6cfg/.toolkit-install-state.tsv"
  ( unset PACK_CLOUDFLARE_DIR
    CLAUDE_CONFIG_DIR="$g6cfg" "$g6tree/local/bootstrap.sh" --uninstall >/dev/null 2>&1 )
  g6left="$(find "$g6cfg/skills" "$g6cfg/agents" -maxdepth 1 -type l 2>/dev/null | wc -l | tr -d ' ')"
  [ "$g6left" -eq 0 ] \
      && ok "the name gate reads JSON, not formatting: nothing is stranded" \
      || no "$g6left link(s) stranded by a reformatted pack spec"

  # (b) No jq and no python3, on a spec the sed fallback cannot read. It must fall back to
  #     the broader rule and SAY SO, not narrow the gate to nothing in silence.
  g6bin="$TMPROOT/g6-nobin"; rm -rf "$g6bin"; mkdir -p "$g6bin"
  for b in jq python3; do printf '#!/bin/sh\nexit 127\n' > "$g6bin/$b"; chmod +x "$g6bin/$b"; done
  g6cfg="$TMPROOT/g6-cfg-b"; rm -rf "$g6cfg"
  PACK_CLOUDFLARE_DIR="$g6pack" CLAUDE_CONFIG_DIR="$g6cfg" \
    "$g6tree/local/bootstrap.sh" --with-packs >/dev/null 2>&1
  rm -f "$g6cfg/.toolkit-install-state.tsv"
  g6out="$( unset PACK_CLOUDFLARE_DIR
            PATH="$g6bin:$PATH" CLAUDE_CONFIG_DIR="$g6cfg" \
              "$g6tree/local/bootstrap.sh" --uninstall 2>&1 )"
  g6left="$(find "$g6cfg/skills" "$g6cfg/agents" -maxdepth 1 -type l 2>/dev/null | wc -l | tr -d ' ')"
  printf '%s' "$g6out" | grep -q 'could not read the skill names' \
      && ok "an unreadable spec says so instead of narrowing the gate silently" \
      || no "the gate failed without a word — got: $g6out"
  [ "$g6left" -eq 0 ] \
      && ok "and it falls back to the broader rule, so nothing is stranded" \
      || no "$g6left link(s) stranded when the gate could not be computed"
  rm -rf "$g6tree" "$g6bin"

  # (c) The spec drops a skill between install and uninstall -- the upgrade path the
  #     no-record fallback exists for. The link cannot be removed on the name gate, so it
  #     must at least be NAMED and the clean-undo claim withheld.
  g6after="$TMPROOT/g6-after"; rm -rf "$g6after"; mkdir -p "$g6after"
  ( cd "$ROOT" && tar -c --exclude=./.git . ) | ( cd "$g6after" && tar -x )
  python3 -c 'import json,sys
p=sys.argv[1]; b=json.load(open(p)); b["skills"].pop(sys.argv[2], None)
open(p,"w").write(json.dumps(b, indent=2) + "\n")' "$g6after/packs/cloudflare.json" "$g6first"
  g6cfg="$TMPROOT/g6-cfg-c"; rm -rf "$g6cfg"
  PACK_CLOUDFLARE_DIR="$g6pack" CLAUDE_CONFIG_DIR="$g6cfg" \
    "$ROOT/local/bootstrap.sh" --with-packs >/dev/null 2>&1
  rm -f "$g6cfg/.toolkit-install-state.tsv"
  rc=0
  g6out="$( unset PACK_CLOUDFLARE_DIR
            CLAUDE_CONFIG_DIR="$g6cfg" "$g6after/local/bootstrap.sh" --uninstall 2>&1 )" || rc=$?
  printf '%s' "$g6out" | grep -q "$g6first" \
      && ok "a link the current specs no longer name is reported, not skipped in silence" \
      || no "the dropped skill's link vanished from the summary — got: $g6out"
  [ "$rc" -ne 0 ] && ! printf '%s' "$g6out" | grep -q 'Nothing else was touched' \
      && ok "and the clean-undo claim is withheld, exit non-zero" \
      || no "the run claimed a clean undo over a link it left behind (rc=$rc)"
  rm -rf "$g6after"

  # (d) The installer probes ONE skill and must not generalise the answer to the others.
  #     A per-skill symlink resolving further from the pack root than the probe does was
  #     linked here and unattributable at uninstall. Tested as the INVARIANT rather than at
  #     one magic depth: at every depth, whatever the installer chose to link must come
  #     back out.
  deep_bad=0; deep_detail=""
  for deep in 1 2 3 4 5 6; do
    g6deep="$TMPROOT/g6-deep$deep"; rm -rf "$g6deep"
    inner="$g6deep/store"; i=0
    while [ "$i" -lt "$deep" ]; do inner="$inner/n$i"; i=$((i + 1)); done
    mkdir -p "$g6deep/skills/$g6first" "$inner/deep-skill"
    printf -- '---\nname: %s\ndescription: fixture\n---\n' "$g6first" \
      > "$g6deep/skills/$g6first/SKILL.md"
    printf -- '---\nname: %s\ndescription: fixture\n---\n' "$g6second" \
      > "$inner/deep-skill/SKILL.md"
    ln -s "$inner/deep-skill" "$g6deep/skills/$g6second"
    printf '{"pack":"cloudflare"}\n' > "$g6deep/PACK.json"
    printf '{"vendoredBy":"tools/vendor-sync.py","pack":"cloudflare"}\n' > "$g6deep/PROVENANCE.json"
    g6cfg="$TMPROOT/g6-cfg-d$deep"; rm -rf "$g6cfg"
    PACK_CLOUDFLARE_DIR="$g6deep" CLAUDE_CONFIG_DIR="$g6cfg" \
      "$ROOT/local/bootstrap.sh" --with-packs >/dev/null 2>&1
    rm -f "$g6cfg/.toolkit-install-state.tsv"
    ( unset PACK_CLOUDFLARE_DIR
      CLAUDE_CONFIG_DIR="$g6cfg" "$ROOT/local/bootstrap.sh" --uninstall >/dev/null 2>&1 )
    g6left="$(find "$g6cfg/skills" "$g6cfg/agents" -maxdepth 1 -type l 2>/dev/null | wc -l | tr -d ' ')"
    [ "$g6left" -eq 0 ] || { deep_bad=$((deep_bad + 1)); deep_detail="$deep_detail depth=$deep:$g6left"; }
    rm -rf "$g6deep" "$g6cfg"
  done
  [ "$deep_bad" -eq 0 ] \
      && ok "whatever the installer links comes back out, at every skill-target depth" \
      || no "links survived at$deep_detail"
  rm -rf "$g6deep" "$g6pack"
fi

# ---------------------------------------------------------------------------------------
group "vendor-sync.py: a built pack carries only what the build writes"

# --verify-pack walked PACK.json's skill list and asked nothing about the rest of the tree.
# Four routes carried undeclared content past it, and the licence -- fetched from upstream
# rather than trusted from a metadata field -- was checked only for existence, so replacing
# its text with "All rights reserved" verified clean.
if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent"
else
  vpx="$TMPROOT/inventory-pack"; rm -rf "$vpx"
  ( cd "$ROOT" && python3 - "$vpx" <<'PY'
import importlib.util, io, pathlib, sys, tarfile
spec = importlib.util.spec_from_file_location('vs', 'tools/vendor-sync.py')
vs = importlib.util.module_from_spec(spec); spec.loader.exec_module(vs)

def archive():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for name, body in [('up/skills/demo/SKILL.md',
                            '---\nname: demo\ndescription: d\n---\nbody\n'),
                           ('up/LICENSE', 'MIT\n')]:
            info = tarfile.TarInfo(name); data = body.encode()
            info.size = len(data); info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()

pack = {'pack': 'demo', 'packRepo': 'x/demo',
        'upstream': {'repo': 'x/y', 'url': 'https://example.invalid', 'ref': 'a' * 40,
                     'license': 'MIT', 'licenseFile': 'LICENSE', 'noticeFile': None},
        'skills': {'demo': 'skills/demo'}, 'layout': {'claudeEntries': True}}
vs.fetch_tree = lambda repo, ref: archive()
vs.load_pack = lambda name: pack
vs.problems.clear(); vs.build_pack('demo', pathlib.Path(sys.argv[1]))
PY
  ) >/dev/null 2>&1
  if [ ! -f "$vpx/PACK.json" ]; then
    skip "could not build the inventory fixture pack"
  else
    ( cd "$ROOT" && python3 tools/vendor-sync.py --verify-pack --into "$vpx" ) >/dev/null 2>&1
    [ $? -eq 0 ] && ok "the fixture pack verifies clean" \
                 || no "the inventory fixture does not verify clean to begin with"

    printf 'All rights reserved. No licence granted.\n' > "$vpx/LICENSE.tampered"
    cp "$vpx/LICENSE" "$vpx/LICENSE.orig"; mv "$vpx/LICENSE.tampered" "$vpx/LICENSE"
    ( cd "$ROOT" && python3 tools/vendor-sync.py --verify-pack --into "$vpx" ) >/dev/null 2>&1
    [ $? -ne 0 ] && ok "a rewritten LICENSE is rejected, not merely counted as present" \
                 || no "--verify-pack passed a pack whose licence had been replaced"
    mv "$vpx/LICENSE.orig" "$vpx/LICENSE"

    inv_bad=0
    for probe in '.claude/agents/evil.md' 'CLAUDE.md' 'skills/LOOSE.md' '.agents/AGENTS.md'; do
      mkdir -p "$vpx/$(dirname "$probe")"; printf 'x\n' > "$vpx/$probe"
      ( cd "$ROOT" && python3 tools/vendor-sync.py --verify-pack --into "$vpx" ) >/dev/null 2>&1
      [ $? -ne 0 ] || { inv_bad=$((inv_bad + 1)); printf '        passed: %s\n' "$probe"; }
      rm -f "$vpx/$probe"
    done
    [ "$inv_bad" -eq 0 ] \
        && ok "4 routes for undeclared content into a Project are all rejected" \
        || no "$inv_bad of 4 undeclared-content routes verified clean"
    rm -rf "$vpx"
  fi
fi

# ---------------------------------------------------------------------------------------
group "doctor.sh: a machine without gh/uv/node/rg is a correct machine"

if [ ! -x "$ROOT/local/doctor.sh" ]; then
  skip "local/doctor.sh not executable"
else
  # A PATH carrying only the core and feature tools. If doctor.sh FAILs here it has
  # reintroduced the defect where a correct install exits 1 over reference binaries.
  minimal="$TMPROOT/minimal-bin"; mkdir -p "$minimal"
  for t in bash git python3 jq find basename dirname readlink printf grep sed cut sort; do
    src="$(command -v "$t" 2>/dev/null)" && ln -sf "$src" "$minimal/$t"
  done
  out="$(CLAUDE_CONFIG_DIR="$TMPROOT/cfg-doctor" PATH="$minimal" \
         "$ROOT/local/doctor.sh" 2>&1)"
  for bin in gh uv node rg; do
    if printf '%s' "$out" | grep -qE "FAIL +$bin missing"; then
      no "doctor.sh FAILs on $bin, which nothing here depends on"
    else
      ok "doctor.sh does not FAIL on $bin"
    fi
  done
  if printf '%s' "$out" | grep -qE 'FAIL +(git|python3) missing'; then
    no "doctor.sh failed on a core binary that is present"
  else
    ok "doctor.sh does not spuriously fail a present core binary"
  fi
fi

# ---------------------------------------------------------------------------------------
group "bootstrap.sh: --dry-run works on a machine that never ran Claude Code"

if [ ! -x "$ROOT/local/bootstrap.sh" ]; then
  skip "local/bootstrap.sh not executable"
else
  absent="$TMPROOT/never-existed/.claude"
  out="$(CLAUDE_CONFIG_DIR="$absent" "$ROOT/local/bootstrap.sh" --dry-run 2>&1)"; rc=$?
  [ "$rc" -eq 0 ] && ok "--dry-run exits 0 with no config directory" \
                  || no "--dry-run exited $rc with no config directory"
  printf '%s' "$out" | grep -q "would create" \
      && ok "--dry-run says it would create the directory" \
      || no "--dry-run did not say it would create the directory"
  [ ! -e "$absent" ] && ok "--dry-run created nothing on disk" \
                     || no "--dry-run CREATED $absent — a dry run must not write"

  out="$(CLAUDE_CONFIG_DIR="$TMPROOT/also-absent/.claude" \
         "$ROOT/local/bootstrap.sh" --uninstall 2>&1)"; rc=$?
  [ "$rc" -eq 0 ] && ok "--uninstall on an absent config directory is a no-op, exit 0" \
                  || no "--uninstall exited $rc on an absent config directory"
fi

# ---------------------------------------------------------------------------------------
group "cloud/setup.sh: apt is given package names, not command names"

if ! grep -q 'pkg_for' "$ROOT/cloud/setup.sh"; then
  no "cloud/setup.sh has no command-to-package mapping"
else
  # shellcheck disable=SC1090
  mapping="$(bash -c '
    pkg_for() { case "$1" in rg) printf ripgrep ;; node) printf nodejs ;; *) printf "%s" "$1" ;; esac; }
    printf "%s %s %s" "$(pkg_for rg)" "$(pkg_for node)" "$(pkg_for git)"')"
  [ "$mapping" = "ripgrep nodejs git" ] \
      && ok "rg->ripgrep, node->nodejs, git->git" \
      || no "mapping wrong: $mapping"
  grep -q 'apt-get install -y -qq \$packages' "$ROOT/cloud/setup.sh" \
      && ok "apt is invoked with the mapped package list" \
      || no "apt is still invoked with raw command names"
fi

# ---------------------------------------------------------------------------------------
group "host-layer invariant: canonical text may not reference the HOST layer"

# AGENTS.md states the rule; these assert the checker computes it. Each case plants one
# violation in a COPY of this repository and requires check.py to reject it. The copy
# matters: a fixture tree invented from nothing would fail a dozen unrelated checks, and
# a finding lost in that noise proves nothing.
#
# The control case is not decoration. "vendor" appears in roles/README.md line 8 -- "may
# require a particular harness, vendor, model or language" -- which is the invariant
# being STATED. A keyword matcher would flag the sentence that defines the rule. That is
# why the check matches path-shaped tokens and why the control is a required test.

if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent — host-invariant tests cannot run"
else
  fixture="$TMPROOT/fixture"
  mkdir -p "$fixture"
  ( cd "$ROOT" && tar -c --exclude=./.git . ) | ( cd "$fixture" && tar -x )

  run_checker() { python3 "$ROOT/tools/check.py" --root "$fixture" 2>&1; }
  saved="$TMPROOT/saved-canonical-file"

  # file | planted line | what it is
  plant_and_check() {
    local file="$1" line="$2" label="$3" expect="$4"
    cp "$fixture/$file" "$saved"
    printf '\n%s\n' "$line" >> "$fixture/$file"
    local out; out="$(run_checker)"
    cp "$saved" "$fixture/$file"
    if printf '%s' "$out" | grep -q 'references the host layer'; then
      if [ "$expect" = reject ]; then ok "$label"
      else no "FALSE POSITIVE: $label"; fi
    else
      if [ "$expect" = reject ]; then no "not rejected: $label"
      else ok "$label"; fi
    fi
  }

  plant_and_check roles/README.md \
    'A role may consult `local/bootstrap.sh` before starting.' \
    'roles/ naming local/bootstrap.sh is rejected' reject
  plant_and_check skills/adversarial-review/SKILL.md \
    'Read `.claude/settings.json` first.' \
    'skills/ naming .claude/settings.json is rejected' reject
  plant_and_check workflows/README.md \
    'Dependencies are listed in `manifest/binaries.json`.' \
    'workflows/ naming manifest/binaries.json is rejected' reject
  plant_and_check agents/README.md \
    'The orchestrator reads `packs/frontend.json` to decide.' \
    'agents/ naming packs/frontend.json is rejected' reject
  plant_and_check roles/README.md \
    'Run `cloud/setup.sh` before assuming this role.' \
    'roles/ naming cloud/setup.sh is rejected' reject
  plant_and_check skills/README.md \
    'Machine specifics live in `profile/plugins.json`.' \
    'skills/ naming profile/plugins.json is rejected' reject
  plant_and_check workflows/README.md \
    'Install the plugin from `.claude-plugin/marketplace.json` first.' \
    'workflows/ naming .claude-plugin/marketplace.json is rejected' reject

  plant_and_check roles/README.md \
    'A local decision, made in the cloud, by a vendor, matching a profile and a manifest.' \
    'ordinary prose using local/cloud/vendor/profile/manifest is NOT flagged' allow

  # The adapter trees and tools/ are NOT the host layer, and canonical READMEs name them
  # today. If this fails, the token set has been widened past what AGENTS.md asserts.
  out="$(run_checker)"
  if printf '%s' "$out" | grep -q 'references the host layer'; then
    no "the unmodified repository is reported as violating its own invariant"
  else
    ok "the unmodified repository passes the invariant it asserts"
  fi
fi

# ---------------------------------------------------------------------------------------
group "packs: specifications, and no third-party content in core"

if [ ! -d "$ROOT/packs" ]; then
  no "packs/ is missing; the external-pack architecture has no specifications"
else
  [ -d "$ROOT/vendor" ] && no "vendor/ is back — third-party content belongs in a pack repo" \
                        || ok "no vendor/ directory in core"
  if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    n="$(git -C "$ROOT" ls-files vendor | wc -l)"
    [ "$n" -eq 0 ] && ok "no tracked vendor/ files" || no "$n vendor/ files still tracked"
  else
    skip "not a git repository — cannot check tracked vendor/ files"
  fi

  # The canonical skills are the ones this toolkit exists to deliver. Anything else in
  # .claude/skills/ means third-party content has crept back into core. The expected list
  # is spelled out rather than derived from skills/, so that adding a skill is a decision
  # recorded here and not something a stray directory can do by itself.
  entries="$(ls "$ROOT/.claude/skills" 2>/dev/null | tr '\n' ' ')"
  expected="adversarial-review bounded-context-handoff checkable-findings evidence-backed-synthesis evidence-verification final-verification independent-validation "
  n_expected=7
  [ "$entries" = "$expected" ] \
      && ok ".claude/skills carries exactly the $n_expected canonical entries" \
      || no ".claude/skills is [$entries], expected [$expected]"

  if command -v python3 >/dev/null 2>&1; then
    out="$(cd "$ROOT" && python3 - <<'PY' 2>&1
import json, pathlib, re
bad = []
for path in sorted(pathlib.Path('packs').glob('*.json')):
    spec = json.loads(path.read_text())
    ref = spec.get('upstream', {}).get('ref', '')
    if not re.fullmatch(r'[0-9a-f]{40}', ref):
        bad.append(f'{path}: ref {ref!r} is not a 40-char sha')
    if not spec.get('layout', {}).get('claudeEntries'):
        bad.append(f'{path}: no layout.claudeEntries')
    if not spec.get('skills'):
        bad.append(f'{path}: no skills')
print('SPECS-OK' if not bad else 'SPEC-PROBLEMS ' + '; '.join(bad))
PY
)"
    printf '%s' "$out" | grep -q 'SPECS-OK' \
        && ok "every pack spec pins a full sha and declares .claude/skills entries" \
        || no "$out"
  else
    skip "python3 absent — pack spec validation"
  fi

  # A pack must be opt-in, and the override must actually work. Both are exercised
  # rather than grepped for: a script can contain the right variable name and still
  # never read it.
  fake="$TMPROOT/fake-pack/skills/wrangler"; mkdir -p "$fake"
  printf -- '---\nname: wrangler\ndescription: fixture\n---\n' > "$fake/SKILL.md"
  printf '{"pack":"cloudflare"}\n' > "$TMPROOT/fake-pack/PACK.json"
  printf '{"vendoredBy":"tools/vendor-sync.py","pack":"cloudflare"}\n' \
    > "$TMPROOT/fake-pack/PROVENANCE.json"

  out="$(CLAUDE_CONFIG_DIR="$TMPROOT/cfg-packs" "$ROOT/local/bootstrap.sh" --dry-run 2>&1)"
  printf '%s' "$out" | grep -q 'wrangler' \
      && no "a default run links pack skills; packs must be opt-in" \
      || ok "a default bootstrap run links no pack skills"

  out="$(CLAUDE_CONFIG_DIR="$TMPROOT/cfg-packs" "$ROOT/local/bootstrap.sh" \
         --with-packs --dry-run 2>&1)"
  printf '%s' "$out" | grep -q 'not checked out' \
      && ok "--with-packs reports an unbuilt pack rather than failing on it" \
      || no "--with-packs did not report the missing pack: $out"

  out="$(CLAUDE_CONFIG_DIR="$TMPROOT/cfg-packs" PACK_CLOUDFLARE_DIR="$TMPROOT/fake-pack" \
         "$ROOT/local/bootstrap.sh" --with-packs --dry-run 2>&1)"
  printf '%s' "$out" | grep -q 'wrangler' \
      && ok "PACK_CLOUDFLARE_DIR is read and its skills are linked" \
      || no "PACK_CLOUDFLARE_DIR was ignored: $out"
  [ -e "$TMPROOT/cfg-packs/skills/wrangler" ] \
      && no "--dry-run CREATED a link — a dry run must not write" \
      || ok "--with-packs --dry-run wrote nothing"
fi

# ---------------------------------------------------------------------------------------
group "no file may claim .claude/settings.json declares plugins"

# The settings file declared three plugins until 2026-09-20; the keys moved to
# profile/plugins.json, and the same day a cloud session measured zero of them installed.
# The false sentence then survived in three more places: twice in
# manifest/external-skills.json, where the two `reason` fields are the recorded
# justification for NOT packaging ui-ux-pro-max and the 181 ecc skills, and once as a
# JSON boolean in profile/plugins.json -- the very file those reasons redirect the reader
# to. Three separate discoveries of one statement is why this is a check and not a fix.
#
# It is deliberately NOT gated on what settings.json currently holds: the "installs in
# cloud" half is falsified by the cloud measurement, not by the declaration, so gating on
# the declaration would let the sentence back in the moment a plugin key returned.

if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent — settings-claim check cannot run"
else
  out="$(cd "$ROOT" && python3 tools/_claim_scan.py 2>&1)"
  rc=$?
  # Require the positive line, not merely the absence of the negative one: if the scan
  # dies before printing anything, "no UNREADABLE" would otherwise read as success.
  if printf '%s' "$out" | grep -q '^SETTINGS-KEYS '; then
    ok "the settings file is readable: $(printf '%s' "$out" | sed -n 's/^SETTINGS-KEYS /keys /p')"
  else
    no "the settings file could not be read — $(printf '%s' "$out" | head -1)"
  fi
  if printf '%s' "$out" | grep -qx 'PROBLEMS 0'; then
    ok "no file claims settings.json declares a plugin, structurally or by heading"
  else
    no "$(printf '%s' "$out" | grep '^CLAIM ' | head -6)"
  fi
  # The exit status agrees with PROBLEMS, so it is asserted AFTER the line it mirrors --
  # this scan used to exit 0 whatever it found, which made an rc-based probe of it read
  # every plant as a pass.
  [ "$rc" -eq 0 ] && ok "and the scan's exit status agrees with that" \
                  || no "the settings-claim scan exited $rc"
  # ADVISORY, NOT A GATE. The free-form prose heuristic caught 1 of 7 restatements of the
  # claim it looks for and flagged 4 of 4 correct, scoped sentences (measured 2026-09-21),
  # so it reports and this suite does not fail on it. Reported here so a hit is still seen.
  advn="$(printf '%s' "$out" | sed -n 's/^ADVISORIES //p')"
  if [ "${advn:-0}" -gt 0 ]; then
    printf '  note  %s prose-heuristic advisory/ies (not a failure):\n' "$advn"
    printf '%s' "$out" | grep '^ADVISORY ' | head -6 | sed 's/^/          /'
  fi
  ok "the prose heuristic is advisory: it reports ${advn:-0} and gates nothing"
fi

# ---------------------------------------------------------------------------------------
group "plugin packaging: every adapter is delivered, and nothing Claude Code runs is"

# The repository root is the plugin root, so a manifest that forgets an adapter, or a
# file that lands in one of Claude Code's default plugin locations, changes what every
# installed session gets with no error from Claude Code at all. Each case plants one such
# change in a FRESH copy and requires check.py to exit non-zero NAMING the plugin; an
# exit for some unrelated reason would prove nothing. The fixture path is stripped from
# the output before matching, so a temporary directory whose name happens to contain
# "claude-plugin" cannot satisfy a case.
#
# The skill and adapter-name cases were added after an independent critic defeated the
# first version: a hook in a skill's frontmatter and inline shell in its body each ran
# in an installed session, and validator.md renamed to `name: critic` silently cost the
# plugin an agent -- all three with check.py at rc 0. The next version copied Claude
# Code's patterns, and an independent validator got past it with variations that still
# ran or still cost an agent; those are the cases below the rename_validator helper.
# The check now refuses a superset of what Claude Code parses rather than a copy of it.

if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent — plugin packaging tests cannot run"
else
  plugbase="$TMPROOT/plugbase"
  rm -rf "$plugbase"; mkdir -p "$plugbase"
  ( cd "$ROOT" && tar -c --exclude=./.git . ) | ( cd "$plugbase" && tar -x )
  plugfix="$TMPROOT/plugfix"

  # Not a command substitution: prc has to survive the call.
  plugin_check() {  # sets prc, and pout to check.py's output with the fixture path removed
    python3 "$ROOT/tools/check.py" --root "$plugfix" > "$TMPROOT/plugout" 2>&1; prc=$?
    pout="$(sed "s|$plugfix||g" "$TMPROOT/plugout")"
  }

  rm -rf "$plugfix"; cp -a "$plugbase" "$plugfix"
  plugin_check
  if [ "$prc" -eq 0 ] && ! printf '%s' "$pout" | grep -q 'claude-plugin\|plugin root'; then
    ok "the unmodified tree passes the plugin check"
  else
    no "the unmodified tree fails the plugin check (rc $prc)"
  fi

  # label | shell that plants the change, run inside a fresh copy
  plugin_case() {
    local label="$1" plant="$2"
    rm -rf "$plugfix"; cp -a "$plugbase" "$plugfix"
    ( cd "$plugfix" && eval "$plant" )
    plugin_check
    if [ "$prc" -ne 0 ] && printf '%s' "$pout" | grep -q 'claude-plugin\|plugin root'; then
      ok "rejected: $label"
    else
      no "not rejected: $label (rc $prc)"
    fi
  }
  edit_json() {  # file | python statement over d
    python3 -c "import json,sys;p=sys.argv[1];d=json.load(open(p));$2;json.dump(d,open(p,'w'))" "$1"
  }
  pj=.claude-plugin/plugin.json
  mj=.claude-plugin/marketplace.json
  skill=skills/checkable-findings/SKILL.md

  plugin_case "an adapter missing from agents" \
    "edit_json $pj 'd[\"agents\"].remove(\"./.claude/agents/critic.md\")'"
  plugin_case "an adapter listed twice" \
    "edit_json $pj 'd[\"agents\"].append(\"./.claude/agents/critic.md\")'"
  plugin_case "an adapter file the manifest does not list" \
    "cp .claude/agents/critic.md .claude/agents/planted.md"
  plugin_case "an adapter whose frontmatter name clashes with another's" \
    "sed -i '0,/^name: validator\$/s//name: critic/' .claude/agents/validator.md"
  plugin_case "agents given as a directory" \
    "edit_json $pj 'd[\"agents\"]=\"./.claude/agents/\"'"
  plugin_case "a plugin name that is not kebab-case, in both manifests alike" \
    "edit_json $pj 'd[\"name\"]=\"Agent Toolkit\"'; edit_json $mj 'd[\"plugins\"][0][\"name\"]=\"Agent Toolkit\"'"
  plugin_case "a skills key, which would replace the skills/ scan" \
    "edit_json $pj 'd[\"skills\"]=[\"./skills/critic\"]'"
  plugin_case "a hooks key in plugin.json" \
    "edit_json $pj 'd[\"hooks\"]={}'"
  plugin_case "a component in the marketplace entry" \
    "edit_json $mj 'd[\"plugins\"][0][\"mcpServers\"]={}'"
  plugin_case "strict: false in the marketplace entry" \
    "edit_json $mj 'd[\"plugins\"][0][\"strict\"]=False'"
  plugin_case "a marketplace source that is not the repository root" \
    "edit_json $mj 'd[\"plugins\"][0][\"source\"]=\"./plugin\"'"
  plugin_case "a marketplace entry named differently from the plugin" \
    "edit_json $mj 'd[\"plugins\"][0][\"name\"]=\"other\"'"
  for location in commands hooks output-styles themes monitors bin; do
    plugin_case "$location/ at the repository root" "mkdir -p $location && : > $location/x"
  done
  for location in settings.json .mcp.json .lsp.json package.json; do
    plugin_case "$location at the repository root" "printf '{}' > $location"
  done
  plugin_case "Hooks/ at the root, which a case-insensitive filesystem reads as hooks/" \
    "mkdir -p Hooks && printf '{}' > Hooks/hooks.json"
  plugin_case "a workflow script in workflows/" \
    "printf 'export const meta = {}' > workflows/plant.js"
  plugin_case "hooks in a skill's frontmatter" \
    "sed -i '0,/^name: /s//hooks: {}\nname: /' $skill"
  plugin_case "allowed-tools in a skill's frontmatter" \
    "sed -i '0,/^name: /s//allowed-tools: Bash\nname: /' $skill"
  plugin_case "inline shell in a skill body" \
    "printf '\nState: !\`touch planted\`\n' >> $skill"
  plugin_case "a fenced shell block in a skill body" \
    "printf '\n\`\`\`!\ntouch planted\n\`\`\`\n' >> $skill"

  # The variants an independent validator used to defeat the second version, each of
  # which Claude Code 2.1.282 ran, or read a different name from, with check.py at rc 0.
  # Every one is refused now because the check demands a shape it cannot misread, not
  # because it recognises these particular spellings.
  reindent() {  # file | prefix: indent the whole frontmatter, then add a hooks block
    python3 - "$1" "$2" <<'PY'
import sys
p, pre = sys.argv[1], sys.argv[2]
s = open(p, encoding='utf-8').read()
head, rest = s[4:].split('\n---\n', 1)
lines = [pre + l for l in head.split('\n')]
lines += [pre + 'hooks:', pre + '  Stop:', pre + '    - hooks:',
          pre + '        - type: command', pre + '          command: "true"']
open(p, 'w', encoding='utf-8').write('---\n' + '\n'.join(lines) + '\n---\n' + rest)
PY
  }
  append() {  # file | text, with \n and \t escapes
    python3 -c 'import sys; open(sys.argv[1], "a", encoding="utf-8").write(sys.argv[2].encode().decode("unicode_escape"))' "$1" "$2"
  }
  rename_validator() {  # python statement over s, the text of validator.md
    python3 -c "import sys;p=sys.argv[1];s=open(p,encoding='utf-8').read();$1;open(p,'w',encoding='utf-8').write(s)" \
      .claude/agents/validator.md
  }
  plugin_case "a skill's whole frontmatter indented by spaces, carrying hooks" \
    "reindent $skill '  '"
  plugin_case "a skill's whole frontmatter indented by tabs, carrying hooks" \
    "reindent $skill \"\$(printf '\t')\""
  plugin_case "a shell fence opened mid-line in a skill" \
    "append $skill '\nSee also: \`\`\`!touch planted\`\`\`\n'"
  plugin_case "a shell fence inside a list item in a skill" \
    "append $skill '\n- Environment: \`\`\`!\n  touch planted\n  \`\`\`\n'"
  plugin_case "inline shell after a U+FEFF in a skill" \
    "append $skill '\nState:﻿!\`touch planted\`\n'"
  plugin_case "an adapter named critic at the top with a nested name: validator" \
    "rename_validator 's=s.replace(\"name: validator\n\",\"name: critic\nmetadata:\n  name: validator\n\",1)'"
  plugin_case "an adapter named critic with name: validator inside a block scalar" \
    "rename_validator 's=s.replace(\"name: validator\n\",\"name: critic\nnotes: |\n  name: validator\n\",1)'"
  plugin_case "an adapter whose only name: validator is nested under model" \
    "rename_validator 's=s.replace(\"name: validator\n\",\"\",1).replace(\"model: inherit\n\",\"model: \n  name: validator\n\",1)'"
  plugin_case "an adapter whose frontmatter a mid-line --- ends at name: critic" \
    "rename_validator 's=s.replace(\"name: validator\n\",\"name: critic ---\nname: validator\n\",1)'"
  plugin_case "an adapter declaring name twice" \
    "rename_validator 's=s.replace(\"name: validator\n\",\"name: critic\nname: validator\n\",1)'"
  plugin_case "an adapter whose opening --- Python sees and Claude Code does not" \
    "rename_validator 's=chr(45)*3+chr(28)+s[3:]'"
  plugin_case "an adapter description that YAML does not read as plain text" \
    "rename_validator 's=s.replace(\"description: \",\"description: Note: \",1)'"
  plugin_case "an adapter description holding a U+2028, a line break to YAML 1.1" \
    "rename_validator 's=s.replace(\"description: \",\"description: A\"+chr(0x2028)+\"B \",1)'"
  plugin_case "an adapter carrying a frontmatter key the adapters do not use" \
    "rename_validator 's=s.replace(\"name: validator\n\",\"name: validator\npermissionMode: bypassPermissions\n\",1)'"
  plugin_case "inline shell in an adapter's operating notes" \
    "rename_validator 's=s.replace(\"# Claude Code operating notes\n\",\"# Claude Code operating notes\n\nState: !\"+chr(96)+\"touch planted\"+chr(96)+\"\n\",1)'"

  # Not a plugin case: the plugin lists its files, but the project directory loads a
  # subdirectory's agents too, and no check looked inside one.
  rm -rf "$plugfix"; cp -a "$plugbase" "$plugfix"
  mkdir "$plugfix/.claude/agents/drafts"
  cp "$plugfix/.claude/agents/critic.md" "$plugfix/.claude/agents/drafts/draft.md"
  plugin_check
  if [ "$prc" -ne 0 ] && printf '%s' "$pout" | grep -q 'a directory among the claude adapters'; then
    ok "rejected: an agent file in a subdirectory of .claude/agents/"
  else
    no "not rejected: an agent file in a subdirectory of .claude/agents/ (rc $prc)"
  fi
fi

# ---------------------------------------------------------------------------------------
group "the tracked-file count in the docs is the tree's actual count"

# It read 78, then 81, while the tree was neither. A number in prose that nobody computes
# drifts every time a file is added -- this one drifted twice in two days -- so compute it.
if ! git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  skip "not a git repository — cannot count tracked files"
else
  actual="$(git -C "$ROOT" ls-files | wc -l | tr -d ' ')"
  claimed="$(sed -n 's/.*it is now \([0-9][0-9]*\),.*/\1/p' "$ROOT/docs/host-integration.md")"
  [ -n "$claimed" ] \
      && ok "docs/host-integration.md states a tracked-file count ($claimed)" \
      || no "no tracked-file count found in docs/host-integration.md — did the wording change?"
  [ "$claimed" = "$actual" ] \
      && ok "and it matches the tree ($actual tracked files)" \
      || no "docs say $claimed tracked files; the tree has $actual"
fi

# ---------------------------------------------------------------------------------------
group "bootstrap.sh: a link it cannot attribute is named, never passed over in silence"

# The closing sweep had two branches -- a link whose target identifies itself, and a link
# whose target is GONE -- and no third. A link whose target EXISTS but says nothing about
# itself fell through both, and the remover needs the same attribution, so ONE gate failed
# on both sides and the run said nothing. That is the round-6 defect on the owner axis
# instead of the name axis, and it reproduced on the upgrade path this fallback exists for:
# an install made by a checkout older than the marker link_owner_of_dir reads left 14 of 14
# links in place under "removed 0 link(s), left 0 alone. Nothing else was touched.", exit 0.

if [ ! -x "$ROOT/local/bootstrap.sh" ]; then
  skip "local/bootstrap.sh not executable"
else
  # An "older checkout": a real directory tree holding the skill, identifying itself as
  # neither a pack (PACK.json + PROVENANCE.json) nor a toolkit checkout.
  anon="$TMPROOT/anon"
  mkdir -p "$anon/skills/adversarial-review" "$anon/skills/not-a-toolkit-name"
  printf 'x\n' > "$anon/skills/adversarial-review/SKILL.md"
  printf 'x\n' > "$anon/skills/not-a-toolkit-name/SKILL.md"

  cfg7="$TMPROOT/cfg-unattributable"; mkdir -p "$cfg7/skills"
  ln -s "$anon/skills/adversarial-review" "$cfg7/skills/adversarial-review"
  out7="$(CLAUDE_CONFIG_DIR="$cfg7" "$ROOT/local/bootstrap.sh" --uninstall 2>&1)"; rc=$?
  [ "$rc" -eq 1 ] && ok "an unattributable link at one of our names exits 1" \
                  || no "exited $rc over an unattributable link: $out7"
  printf '%s' "$out7" | grep -q 'cannot attribute' \
      && ok "and is named in the summary" \
      || no "it was not named: $out7"
  printf '%s' "$out7" | grep -q 'Nothing else was touched' \
      && no "the clean-undo claim was still made: $out7" \
      || ok "and the clean-undo claim is withheld"
  [ -L "$cfg7/skills/adversarial-review" ] \
      && ok "and it is left in place rather than guessed at" \
      || no "an unattributable link was deleted"

  # The other direction, or every hand-made link would fail every uninstall: the same
  # shape at a name this toolkit does NOT install is somebody else's arrangement.
  cfg8="$TMPROOT/cfg-foreign"; mkdir -p "$cfg8/skills"
  ln -s "$anon/skills/not-a-toolkit-name" "$cfg8/skills/not-a-toolkit-name"
  out8="$(CLAUDE_CONFIG_DIR="$cfg8" "$ROOT/local/bootstrap.sh" --uninstall 2>&1)"; rc=$?
  [ "$rc" -eq 0 ] && ok "a link at a name this toolkit never installs is not flagged" \
                  || no "exited $rc over a foreign link: $out8"
  [ -L "$cfg8/skills/not-a-toolkit-name" ] \
      && ok "and is left alone" || no "a foreign link was deleted"
fi

# ---------------------------------------------------------------------------------------
group "bootstrap.sh: with a usable record, an unrecorded link is reported, not deleted"

# The fallback remover ran unconditionally, though this file's own header and
# local/README.md both say it is for the case where there is no record. So a link the USER
# made by hand -- their own clone of a published pack, linked at its own name -- was
# deleted by a run whose record was present, complete and silent about it.

if [ ! -x "$ROOT/local/bootstrap.sh" ]; then
  skip "local/bootstrap.sh not executable"
elif ! command -v jq >/dev/null 2>&1; then
  skip "jq absent — the pack skill names cannot be read"
else
  # A PACK skill name: one this toolkit installs, but only with --with-packs. The install
  # below is a plain one, so the record is complete and never mentions this path -- which
  # is exactly what made the old code delete it.
  packname="$(jq -r '.skills | keys[0]' "$ROOT/packs/cloudflare.json" 2>/dev/null)"
  if [ -z "$packname" ]; then
    skip "could not read a pack skill name from packs/cloudflare.json"
  else
    mine="$TMPROOT/my-own-pack"
    mkdir -p "$mine/skills/$packname"
    printf 'x\n' > "$mine/skills/$packname/SKILL.md"
    printf '{"pack":"mine"}\n' > "$mine/PACK.json"
    printf '{"vendoredBy":"tools/vendor-sync.py","pack":"mine"}\n' > "$mine/PROVENANCE.json"

    cfg9="$TMPROOT/cfg-recorded"; mkdir -p "$cfg9/skills"
    # The user's own link, made before the install and never recorded by it.
    ln -s "$mine/skills/$packname" "$cfg9/skills/$packname"
    CLAUDE_CONFIG_DIR="$cfg9" "$ROOT/local/bootstrap.sh" >/dev/null 2>&1
    recorded9=0
    grep -q "/skills/$packname\b" "$cfg9/.toolkit-install-state.tsv" 2>/dev/null \
      && recorded9=1
    [ "$recorded9" -eq 0 ] \
        && ok "a plain install does not record the user's own pack-named link" \
        || no "the fixture is wrong: the install recorded $packname"
    out9="$(CLAUDE_CONFIG_DIR="$cfg9" "$ROOT/local/bootstrap.sh" --uninstall 2>&1)"; rc=$?
    [ -L "$cfg9/skills/$packname" ] \
        && ok "a link the record never named survives --uninstall" \
        || no "--uninstall deleted a link its own complete record never named: $out9"
    [ "$rc" -eq 1 ] && ok "and the run reports it rather than claiming a clean undo" \
                    || no "exited $rc over an unrecorded leftover: $out9"
    printf '%s' "$out9" | grep -q 'this toolkit created are still in place' \
        && no "the summary asserts it created a link it cannot know it created: $out9" \
        || ok "and the summary does not claim it created that link"
  fi
fi

# ---------------------------------------------------------------------------------------
group "bootstrap.sh: a relative PACK_<NAME>_DIR resolves to the same place in both uses"

# The probe resolved it against the CALLER's working directory; the link resolved it
# against $CLAUDE_DIR/skills/. Both accepted it and every link created was dead: measured,
# 13 broken links under "linked 27 ... problems 0", exit 0, doctor.sh reporting no warning.

if [ ! -x "$ROOT/local/bootstrap.sh" ]; then
  skip "local/bootstrap.sh not executable"
elif ! command -v jq >/dev/null 2>&1; then
  skip "jq absent — --with-packs cannot read the pack specs"
else
  relpack="$TMPROOT/relpack"
  relfirst="$(jq -r '.skills | keys[0]' "$ROOT/packs/cloudflare.json" 2>/dev/null)"
  if [ -z "$relfirst" ]; then
    skip "could not read a skill name from packs/cloudflare.json"
  else
    mkdir -p "$relpack/skills/$relfirst"
    printf -- '---\nname: %s\ndescription: fixture\n---\n' "$relfirst" \
      > "$relpack/skills/$relfirst/SKILL.md"
    printf '{"pack":"rel"}\n' > "$relpack/PACK.json"
    printf '{"vendoredBy":"tools/vendor-sync.py","pack":"rel"}\n' > "$relpack/PROVENANCE.json"
    cfg10="$TMPROOT/cfg-relative"
    ( cd "$TMPROOT" && CLAUDE_CONFIG_DIR="$cfg10" PACK_CLOUDFLARE_DIR="relpack" \
        "$ROOT/local/bootstrap.sh" --with-packs >/dev/null 2>&1 )
    if [ -L "$cfg10/skills/$relfirst" ]; then
      [ -e "$cfg10/skills/$relfirst" ] \
          && ok "a link made from a relative PACK_*_DIR resolves" \
          || no "a relative PACK_*_DIR produced a broken link"
    else
      ok "a relative PACK_*_DIR was refused rather than linked blindly"
    fi
    broken10=0
    for l in "$cfg10"/skills/* "$cfg10"/agents/*; do
      [ -L "$l" ] || continue
      [ -e "$l" ] || broken10=$((broken10 + 1))
    done
    [ "$broken10" -eq 0 ] && ok "and the install leaves no broken link behind" \
                          || no "$broken10 broken link(s) after a relative PACK_*_DIR install"
  fi
fi

# ---------------------------------------------------------------------------------------
group "a skill name is a plain directory name, in the spec and at the link"

# A key carrying a path separator passed check.py and put a link at
# $CLAUDE_DIR/skills/<sub>/<name>, one level below where --uninstall's sweep looks: 27
# links installed, one left behind under "removed 26 link(s), left 0 alone."

if ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent — spec validation cannot run"
else
  specroot="$TMPROOT/specname"
  mkdir -p "$specroot"
  ( cd "$ROOT" && tar -c --exclude=.git . ) | tar -x -C "$specroot" 2>/dev/null
  for bad in 'sub/wrangler' '../escape' '.'; do
    python3 - "$specroot" "$bad" <<'PY'
import json, sys
root, bad = sys.argv[1], sys.argv[2]
p = f'{root}/packs/cloudflare.json'
spec = json.loads(open(p).read())
first = next(iter(spec['skills']))
spec['skills'][bad] = spec['skills'].pop(first)
open(p, 'w').write(json.dumps(spec, indent=2) + '\n')
PY
    ( cd "$specroot" && python3 tools/check.py >/dev/null 2>&1 )
    [ $? -eq 1 ] && ok "check.py rejects a skill name of '$bad'" \
                 || no "check.py accepted a skill name of '$bad'"
    ( cd "$ROOT" && git show HEAD:packs/cloudflare.json > "$specroot/packs/cloudflare.json" \
        2>/dev/null ) || cp "$ROOT/packs/cloudflare.json" "$specroot/packs/cloudflare.json"
  done
  ( cd "$specroot" && python3 tools/check.py >/dev/null 2>&1 )
  [ $? -eq 0 ] && ok "and accepts the real specs unchanged" \
               || no "check.py rejected the repository's own pack specs"
fi

# ---------------------------------------------------------------------------------------
group "the claim scan's hard gate is the structural and heading-scoped passes, only"

# The free-form prose heuristic was a hard gate until 2026-09-21, when it was measured:
# 1 of 7 restatements of the false claim caught, 6 missed, and 4 of 4 correct, scoped
# sentences flagged -- so writing a TRUE sentence about this subject failed the suite
# while six false ones passed. It now reports and gates nothing. These four cases are
# that split, asserted rather than described: two that must still fail the whole suite,
# and two that must not.
#
# The last two run `bash tools/test.sh` itself in a planted copy, because "does not make
# tools/test.sh fail" is a claim about this file and nothing smaller proves it.
# CLAIM_GATE_PROOF stops the nested run from recursing into this group.

if [ -n "${CLAIM_GATE_PROOF:-}" ]; then
  :                                  # nested run: this group is what is being measured
elif ! command -v python3 >/dev/null 2>&1; then
  skip "python3 absent — the claim-gate split cannot be measured"
else
  gate_tree() {
    rm -rf "$1"; mkdir -p "$1"
    ( cd "$ROOT" && tar -c --exclude=./.git . ) | ( cd "$1" && tar -x )
  }
  suite_failed() {                   # echoes the nested suite's FAILED count
    ( cd "$1" && CLAIM_GATE_PROOF=1 bash tools/test.sh 2>&1 ) \
      | sed -n 's/^\([0-9]*\) passed, \([0-9]*\) failed.*/\2/p' | tail -1
  }

  # 1. STRUCTURAL false claim -> hard failure.
  gt="$TMPROOT/gate-structural"; gate_tree "$gt"
  python3 - "$gt" <<'PY'
import json, sys
p = f'{sys.argv[1]}/profile/plugins.json'
blob = json.loads(open(p).read())
first = next(iter(blob['plugins']))
blob['plugins'][first]['enabledInRepoSettings'] = True
open(p, 'w').write(json.dumps(blob, indent=2) + '\n')
PY
  gout="$( cd "$gt" && python3 tools/_claim_scan.py 2>&1 )"; grc=$?
  printf '%s' "$gout" | grep -q '^PROBLEMS 0' \
      && no "a structural false claim was not counted as a problem: $gout" \
      || ok "a structural false claim is a hard problem"
  [ "$grc" -eq 1 ] && ok "and the scan exits 1 on it" || no "the scan exited $grc on it"

  # 2. HEADING-SCOPED false claim -> hard failure. A row under "What is here, and why"
  #    naming a key the settings file does not declare; its own words name no file, so
  #    the prose pass cannot see it, and it is Markdown, so the structural pass cannot.
  gt2="$TMPROOT/gate-heading"; gate_tree "$gt2"
  python3 - "$gt2" <<'PY'
import sys
p = f'{sys.argv[1]}/.claude/SETTINGS-NOTES.md'
lines = open(p).read().splitlines()
out, placed = [], False
for line in lines:
    out.append(line)
    if not placed and line.strip().startswith('| `permissions.deny`'):
        out.append('| `extraKnownMarketplaces` | Registers the marketplace for a session. |')
        placed = True
assert placed, 'anchor row not found'
open(p, 'w').write('\n'.join(out) + '\n')
PY
  g2out="$( cd "$gt2" && python3 tools/_claim_scan.py 2>&1 )"; g2rc=$?
  printf '%s' "$g2out" | grep -q '^PROBLEMS 0' \
      && no "a heading-scoped false claim was not counted as a problem: $g2out" \
      || ok "a heading-scoped false claim is a hard problem"
  [ "$g2rc" -eq 1 ] && ok "and the scan exits 1 on it too" \
                    || no "the scan exited $g2rc on the heading-scoped plant"

  # ...and both of those must actually fail the SUITE, not merely the scan.
  gt3="$TMPROOT/gate-hardsuite"; gate_tree "$gt3"
  python3 - "$gt3" <<'PY'
import json, sys
p = f'{sys.argv[1]}/profile/plugins.json'
blob = json.loads(open(p).read())
first = next(iter(blob['plugins']))
blob['plugins'][first]['enabledInRepoSettings'] = True
open(p, 'w').write(json.dumps(blob, indent=2) + '\n')
PY
  hard_failed="$(suite_failed "$gt3")"
  [ "${hard_failed:-0}" -gt 0 ] \
      && ok "and tools/test.sh itself fails on a structural false claim ($hard_failed failed)" \
      || no "tools/test.sh reported no failure over a structural false claim"

  # 3 and 4. A prose-heuristic HIT, and the four correct sentences the heuristic flags,
  #    in ONE tree: the suite must report them and pass.
  gt4="$TMPROOT/gate-advisory"; gate_tree "$gt4"
  {
    printf '\nThe plugin declared in `.claude/settings.json` installs in a cloud session.\n'
    printf '\nThe plugin composition lives in `profile/plugins.json`; `.claude/settings.json` holds permissions.\n'
    printf '\n`.claude/settings.json` is the channel that reaches cloud; it carries permissions and a plugin declaration would be ignored there.\n'
    printf '\nTo declare a plugin you would edit `.claude/settings.json`, and a cloud session would still install nothing.\n'
    printf '\nThe marketplace is reachable from a cloud session; installation is a separate step.\n'
  } >> "$gt4/cloud/README.md"
  g4out="$( cd "$gt4" && python3 tools/_claim_scan.py 2>&1 )"; g4rc=$?
  g4adv="$(printf '%s' "$g4out" | sed -n 's/^ADVISORIES //p')"
  [ "${g4adv:-0}" -ge 5 ] \
      && ok "a prose-heuristic hit is reported ($g4adv advisories)" \
      || no "the prose heuristic reported ${g4adv:-0} advisories over 5 planted sentences"
  printf '%s' "$g4out" | grep -q '^PROBLEMS 0' \
      && ok "and is not counted as a problem" \
      || no "a prose-heuristic hit was counted as a problem: $(printf '%s' "$g4out" | grep '^CLAIM ')"
  [ "$g4rc" -eq 0 ] && ok "and the scan exits 0 over it" \
                    || no "the scan exited $g4rc over an advisory-only hit"
  adv_failed="$(suite_failed "$gt4")"
  [ "${adv_failed:-1}" -eq 0 ] \
      && ok "and tools/test.sh passes with one false and four correct sentences planted" \
      || no "tools/test.sh reported $adv_failed failure(s) over prose-heuristic hits"
  rm -rf "$gt" "$gt2" "$gt3" "$gt4"
fi

# ---------------------------------------------------------------------------------------
group "hygiene"

syntax_bad=0
for f in "$ROOT"/local/*.sh "$ROOT"/cloud/*.sh "$ROOT"/tools/*.sh; do
  [ -e "$f" ] || continue
  bash -n "$f" 2>/dev/null || { no "shell syntax: ${f#"$ROOT"/}"; syntax_bad=1; }
done
[ "$syntax_bad" -eq 0 ] && ok "every shell script parses"

if command -v python3 >/dev/null 2>&1; then
  json_bad=0
  while IFS= read -r f; do
    python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$f" 2>/dev/null \
      || { no "invalid JSON: ${f#"$ROOT"/}"; json_bad=1; }
  done < <(find "$ROOT" -name '*.json' -not -path '*/.git/*')
  [ "$json_bad" -eq 0 ] && ok "every tracked JSON file parses"

  for f in "$ROOT"/tools/*.py; do
    [ -e "$f" ] || continue
    python3 -c "import ast,sys;ast.parse(open(sys.argv[1]).read())" "$f" 2>/dev/null \
      && ok "python parses: ${f#"$ROOT"/}" || no "python syntax: ${f#"$ROOT"/}"
  done
else
  skip "python3 absent — JSON and Python syntax checks"
fi

# ---------------------------------------------------------------------------------------
printf '\n%d passed, %d failed, %d skipped\n' "$passed" "$failed" "$skipped"
[ "$failed" -eq 0 ] || exit 1
