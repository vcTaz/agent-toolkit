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
PY
)"
  for case in 'EMPTY BUILT:an empty destination still builds' \
              'ONLYGIT BUILT:a destination holding only .git still builds' \
              'REBUILD BUILT:an existing pack still rebuilds in place' \
              'ARBITRARY REFUSED:an arbitrary directory is refused' \
              'UNCHANGED:the refused directory is left content-identical' \
              'agent-survived:the refusal left .claude/agents/mine.md in place' \
              'CROSSPACK REFUSED:building one pack over a different pack is refused'; do
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
PY
)"
  printf '%s' "$out" | grep -q 'BASELINE rc=0' \
      && ok "an untampered pack verifies (exit 0)" \
      || no "an untampered pack did not verify: $out"
  for case in 'CONTENT:edited file content' 'EXTRA:an added file' \
              'CHMOD:a chmod-only change' 'ENTRY:a removed .claude/skills entry' \
              'LICENCE:a deleted LICENSE' 'LOOP:a self-looping .agents/skills' \
              'SCHEMA1:a pack predating file-mode provenance'; do
    token="${case%%:*}"; label="${case#*:}"
    if printf '%s' "$out" | grep -q "$token rc=1"; then ok "--verify-pack rejects $label"
    else no "--verify-pack did NOT reject $label: $out"; fi
  done
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
    printf '{"pack":"cycle"}\n' > "$packdir/PACK.json"
    printf '{"vendoredBy":"tools/vendor-sync.py","pack":"cycle"}\n' > "$packdir/PROVENANCE.json"
    ln -s "$packdir/skills/$first"          "$cfg2/skills/$first"
    ln -s "$ROOT/skills/adversarial-review" "$cfg2/skills/adversarial-review"
    ln -s "$ROOT/.claude/agents/critic.md"  "$cfg2/agents/critic.md"
    ln -s "$TMPROOT/elsewhere/my-skill"     "$cfg2/skills/my-own-skill"
    # A link made by a DIFFERENT checkout of this toolkit. $TOOLKIT_ROOT cannot recognise
    # it, which is why the pre-fix fallback left it -- and why a checkout is identified by
    # its own AGENTS.md + tools/check.py rather than by a path comparison.
    mkdir -p "$TMPROOT/other-checkout/tools" "$TMPROOT/other-checkout/skills/other-skill"
    printf '# AGENTS.md\n' > "$TMPROOT/other-checkout/AGENTS.md"
    # A real checkout, so the marker must really be there: empty files are what the
    # foreign-link cases below use, and they must NOT be recognised.
    cp "$ROOT/tools/check.py" "$TMPROOT/other-checkout/tools/check.py"
    printf -- '---\nname: other-skill\ndescription: fixture\n---\n' \
      > "$TMPROOT/other-checkout/skills/other-skill/SKILL.md"
    ln -s "$TMPROOT/other-checkout/skills/other-skill" "$cfg2/skills/other-skill"
    [ -f "$cfg2/.toolkit-install-state.tsv" ] && rm -f "$cfg2/.toolkit-install-state.tsv"

    out="$( unset PACK_CLOUDFLARE_DIR
            CLAUDE_CONFIG_DIR="$cfg2" "$ROOT/local/bootstrap.sh" --uninstall 2>&1 )"
    [ -L "$cfg2/skills/$first" ] \
        && no "no record: a pack link survived --uninstall" \
        || ok "no record: the pack link is removed, recognised by the pack's own metadata"
    [ -L "$cfg2/skills/adversarial-review" ] || [ -L "$cfg2/agents/critic.md" ] \
        && no "no record: a toolkit link survived --uninstall" \
        || ok "no record: toolkit links are removed too"
    [ -L "$cfg2/skills/other-skill" ] \
        && no "no record: a link into another checkout of this toolkit survived" \
        || ok "no record: a link into another toolkit checkout is removed too"
    [ -L "$cfg2/skills/my-own-skill" ] \
        && ok "no record: a link of the user's own, into neither, is left alone" \
        || no "no record: --uninstall removed the user's own unrelated symlink"
    printf '%s' "$out" | grep -q 'Nothing else was touched' \
        && ok "no record: the summary may claim a clean undo, because it achieved one" \
        || no "no record: the summary withheld the claim although nothing was stranded — got: $out"

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
      if [ "$n" -gt 0 ] && [ -n "$c" ] && [ "$c" -le "$n" ]; then :
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
    printf '%s' "$out" | grep -q 'Nothing else was touched' \
        && ok "and it is not counted against the clean-undo claim either" \
        || no "the user's own link was counted as one we failed to remove — got: $out"

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

  # The six canonical skills are the ones this toolkit exists to deliver. Anything else
  # in .claude/skills/ means third-party content has crept back into core.
  entries="$(ls "$ROOT/.claude/skills" 2>/dev/null | tr '\n' ' ')"
  expected="adversarial-review bounded-context-handoff evidence-backed-synthesis evidence-verification final-verification independent-validation "
  [ "$entries" = "$expected" ] \
      && ok ".claude/skills carries exactly the six canonical entries" \
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
  [ "$rc" -eq 0 ] && ok "the settings-claim scan ran to completion" \
                  || no "the settings-claim scan exited $rc"
  if printf '%s' "$out" | grep -qx 'PROBLEMS 0'; then
    ok "no file claims settings.json declares a plugin, structurally or in prose"
  else
    no "$(printf '%s' "$out" | grep '^CLAIM ' | head -6)"
  fi
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
