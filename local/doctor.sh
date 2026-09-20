#!/usr/bin/env bash
# doctor.sh — verify this toolkit's local installation. Read-only: changes nothing.
#
#   ./local/doctor.sh              the toolkit only
#   ./local/doctor.sh --profile    also check the machine-specific material in profile/
#
# Exit 0 when everything the manifest claims is actually true, 1 otherwise.
# Every check reports PASS, WARN or FAIL with the reason, and nothing is inferred:
# a check that cannot run reports SKIP rather than passing quietly.
#
# The profile checks are OFF by default and a default run never mentions them. A machine
# with no rtk, no srt and no plugins is a correct machine as far as this toolkit is
# concerned -- warning about them unprompted is the same defect the binary tiers fixed,
# one level up.

set -uo pipefail

PROFILE=0
for arg in "$@"; do
  case "$arg" in
    --profile) PROFILE=1 ;;
    -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'unrecognised argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

TOOLKIT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
fails=0; warns=0

pass() { printf '  PASS  %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*"; warns=$((warns + 1)); }
fail() { printf '  FAIL  %s\n' "$*"; fails=$((fails + 1)); }
skip() { printf '  SKIP  %s\n' "$*"; }
head_() { printf '\n%s\n' "$*"; }

head_ "toolkit integrity"
if command -v python3 >/dev/null 2>&1; then
  if out="$(cd "$TOOLKIT_ROOT" && python3 tools/check.py 2>&1)"; then pass "$out"
  else fail "tools/check.py: $out"; fi
else skip "python3 not found — cannot run tools/check.py"; fi

head_ "agent links"
for f in "$TOOLKIT_ROOT"/.claude/agents/*.md; do
  [ -e "$f" ] || continue
  name="$(basename -- "$f")"; dest="$CLAUDE_DIR/agents/$name"
  if [ ! -e "$dest" ] && [ ! -L "$dest" ]; then fail "$name not installed"
  elif [ -L "$dest" ] && [ "$(readlink -f -- "$dest" 2>/dev/null)" = "$(readlink -f -- "$f")" ]; then pass "$name"
  elif [ -L "$dest" ]; then fail "$name links elsewhere: $(readlink -- "$dest")"
  else warn "$name is a real file, not a link to this toolkit (local copy wins)"; fi
done

head_ "skill links"
for d in "$TOOLKIT_ROOT"/skills/*/; do
  [ -d "$d" ] || continue
  name="$(basename -- "$d")"; dest="$CLAUDE_DIR/skills/$name"
  if [ ! -e "$dest" ] && [ ! -L "$dest" ]; then fail "$name not installed"
  elif [ -L "$dest" ] && [ "$(readlink -f -- "$dest" 2>/dev/null)" = "$(readlink -f -- "${d%/}")" ]; then pass "$name"
  elif [ -L "$dest" ]; then fail "$name links elsewhere: $(readlink -- "$dest")"
  else warn "$name is a real directory, not a link to this toolkit"; fi
done

head_ "binaries"
# Only `core` can FAIL. `feature` degrades a flag, `reference` is recorded data that
# nothing here depends on -- a machine without gh, uv, node or rg is a correct machine,
# and reporting that as a failed install is what this check used to get wrong.
if command -v jq >/dev/null 2>&1; then
  while IFS=$'\t' read -r bin tier; do
    [ -n "$bin" ] || continue
    if command -v "$bin" >/dev/null 2>&1; then pass "$bin ($tier) -> $(command -v "$bin")"
    else
      case "$tier" in
        core)      fail "$bin missing — core dependency, the toolkit cannot work without it" ;;
        feature)   warn "$bin missing — optional flags degrade; see manifest/binaries.json" ;;
        *)         printf '  INFO  %s not on PATH — nothing here depends on it\n' "$bin" ;;
      esac
    fi
  done < <(jq -r '.required | to_entries[] | [.key, (.value.tier // "core")] | @tsv' \
             "$TOOLKIT_ROOT/manifest/binaries.json")
else
  # jq is itself `feature`, so its absence must not fail the run.
  warn "jq missing — cannot read manifest/binaries.json; binary check skipped"
  for bin in git python3; do
    if command -v "$bin" >/dev/null 2>&1; then pass "$bin (core, fallback check)"
    else fail "$bin missing — core dependency"; fi
  done
fi

if [ "$PROFILE" -eq 0 ]; then
  printf '\nprofile checks skipped — pass --profile for the machine-specific ones\n'
  profile_checks() { :; }
else
  profile_checks() { profile_body; }
fi

profile_body() {

head_ "machine-local binaries (profile, informational)"
for bin in rtk srt bwrap socat; do
  if command -v "$bin" >/dev/null 2>&1; then pass "$bin -> $(command -v "$bin")"
  else warn "$bin not on PATH — see profile/machine-binaries.json"; fi
done

head_ "rtk version guard"
if command -v rtk >/dev/null 2>&1; then
  v="$(rtk --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
  if [ -z "$v" ]; then warn "could not parse rtk version"
  else
    minor="$(printf '%s' "$v" | cut -d. -f2)"; major="$(printf '%s' "$v" | cut -d. -f1)"
    if [ "$major" -eq 0 ] && [ "$minor" -lt 23 ]; then
      fail "rtk $v is below the 0.23.0 the hook requires. Reinstall with the upstream installer — NOT 'cargo install rtk', which is a different project."
    else pass "rtk $v (>= 0.23.0)"; fi
  fi
else skip "rtk not installed"; fi

head_ "rtk hook integrity (regression guard)"
# The upstream hook once advised `cargo install rtk` on the version-too-old path. That
# crate is a DIFFERENT project (reachingforthejack/rtk, "Rust Type Kit"); installing it
# replaces a working rtk with one that has no `rewrite` subcommand and silently disables
# the PreToolUse hook on every Bash call. This guard fails if the advice comes back --
# for example after an rtk reinstall overwrites the hook.
rtk_hook="${CLAUDE_DIR}/hooks/rtk-rewrite.sh"
if [ -f "$rtk_hook" ]; then
  # Comment lines are excluded: the fix itself documents the trap by naming it.
  if grep -vE '^[[:space:]]*#' "$rtk_hook" | grep -qE '\bcargo[[:space:]]+install[[:space:]]+rtk\b'; then
    warn "rtk-rewrite.sh advises 'cargo install rtk' on the version-too-old path. That crate is a DIFFERENT project (Rust Type Kit); following it replaces rtk with a binary that has no 'rewrite' subcommand and silently disables this hook. Latent only: it fires below 0.23.0. The file is integrity-protected by rtk (.rtk-hook.sha256), so editing it makes rtk refuse to run until the baseline is updated too -- see profile/known-discrepancies.md before changing anything"
  elif grep -q 'rtk-ai/rtk' "$rtk_hook"; then
    pass "rtk-rewrite.sh points at the correct upstream installer"
  else
    warn "rtk-rewrite.sh names no installer; a stale binary would give no recovery path"
  fi
else
  skip "no rtk-rewrite.sh at $rtk_hook"
fi

head_ "plugins"
if command -v jq >/dev/null 2>&1 && [ -f "$CLAUDE_DIR/plugins/installed_plugins.json" ]; then
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    if jq -e --arg n "$name" '.plugins | has($n)' "$CLAUDE_DIR/plugins/installed_plugins.json" >/dev/null 2>&1
    then pass "$name"
    else warn "$name in manifest but not installed — run bootstrap.sh --with-plugins"; fi
  done < <(jq -r '.plugins | to_entries[]
                  | .key as $k | ($k | split("@")[1]) as $mk
                  | select(.value.installedLocally != null) | $k' \
             "$TOOLKIT_ROOT/profile/plugins.json")
else skip "cannot read installed_plugins.json"; fi

}

profile_checks

head_ "secret hygiene (this repository)"
if git -C "$TOOLKIT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  pat='sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
  if hits="$(git -C "$TOOLKIT_ROOT" grep -IlE "$pat" -- . 2>/dev/null)" && [ -n "$hits" ]; then
    fail "possible secrets in tracked files:"; printf '        %s\n' $hits
  else pass "no secret patterns in tracked files"; fi
else skip "not a git repository"; fi

printf '\n'
if [ "$fails" -gt 0 ]; then printf '%d failure(s), %d warning(s)\n' "$fails" "$warns"; exit 1; fi
printf 'ok — %d warning(s)\n' "$warns"
