#!/usr/bin/env bash
# doctor.sh — verify this toolkit's local installation. Read-only: changes nothing.
#
# Exit 0 when everything the manifest claims is actually true, 1 otherwise.
# Every check reports PASS, WARN or FAIL with the reason, and nothing is inferred:
# a check that cannot run reports SKIP rather than passing quietly.

set -uo pipefail

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

head_ "required binaries"
if command -v jq >/dev/null 2>&1; then
  while IFS= read -r bin; do
    [ -n "$bin" ] || continue
    if command -v "$bin" >/dev/null 2>&1; then pass "$bin -> $(command -v "$bin")"
    else fail "$bin missing (manifest/binaries.json lists it as required)"; fi
  done < <(jq -r '.required | keys[]' "$TOOLKIT_ROOT/manifest/binaries.json")
else fail "jq missing — it is a hard dependency of the rtk PreToolUse hook"; fi

head_ "machine-local binaries (informational)"
for bin in rtk srt bwrap socat; do
  if command -v "$bin" >/dev/null 2>&1; then pass "$bin -> $(command -v "$bin")"
  else warn "$bin not on PATH — see manifest/binaries.json"; fi
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

head_ "plugins"
if command -v jq >/dev/null 2>&1 && [ -f "$CLAUDE_DIR/plugins/installed_plugins.json" ]; then
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    if jq -e --arg n "$name" '.plugins | has($n)' "$CLAUDE_DIR/plugins/installed_plugins.json" >/dev/null 2>&1
    then pass "$name"
    else warn "$name in manifest but not installed — run bootstrap.sh --with-plugins"; fi
  done < <(jq -r '.plugins | to_entries[] | select(.value.scope=="portable") | .key' \
             "$TOOLKIT_ROOT/manifest/plugins.json")
else skip "cannot read installed_plugins.json"; fi

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
