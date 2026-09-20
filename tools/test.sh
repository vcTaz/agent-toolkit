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

# An existing, good pack that must survive a failed rebuild byte for byte.
(pack_dir / 'skills' / 'demo').mkdir(parents=True)
(pack_dir / 'skills' / 'demo' / 'SKILL.md').write_text('ORIGINAL CONTENT\n')

# A tarball whose member escapes the destination.
buf = _io.BytesIO()
with tarfile.open(fileobj=buf, mode='w:gz') as tar:
    def add(path, body):
        info = tarfile.TarInfo(path); data = body.encode()
        info.size = len(data); tar.addfile(info, _io.BytesIO(data))
    add('up-abc/skills/demo/SKILL.md', 'legitimate\n')
    # relative to <pack>/.demo.staging/skills/demo this stays inside lvl1/lvl2
    add('up-abc/skills/demo/../../../escaped.md', 'HOSTILE\n')
vs.fetch_tree = lambda repo, ref: buf.getvalue()

spec_dict = {'pack': 'demo', 'packRepo': 'x/demo',
             'upstream': {'repo': 'x/y', 'url': 'https://example.invalid', 'ref': 'a' * 40,
                          'license': 'MIT', 'licenseFile': None, 'noticeFile': None},
             'skills': {'demo': 'skills/demo'}, 'layout': {}}
vs.load_pack = lambda name: spec_dict
try:
    vs.build_pack('demo', pack_dir)
    print('BUILD-RETURNED-OK')
except ValueError:
    print('BUILD-RAISED')
except Exception as exc:
    print('BUILD-OTHER', type(exc).__name__)

print('PRESERVED' if (pack_dir / 'skills' / 'demo' / 'SKILL.md').read_text()
      == 'ORIGINAL CONTENT\n' else 'CLOBBERED')
leftovers = [p.name for p in pack_dir.iterdir() if p.name.startswith('.')]
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
