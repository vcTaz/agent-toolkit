#!/usr/bin/env bash
# setup.sh — optional cloud environment setup script.
#
# YOU PROBABLY DO NOT NEED THIS. The supported way to get this toolkit into cloud
# sessions is to add this repository to the project: every thread clones every project
# repository and loads `.claude/skills/`, `.claude/agents/`, `.claude/commands/` and
# `CLAUDE.md` from each one. See cloud/README.md.
#
# This script exists for the one case that does not cover: a single-repository cloud
# session started on some OTHER repository (`claude --cloud` from an app repo), where
# you still want the toolkit present.
#
# Contract this script is written against (docs verified 2026-09-19;
# binaries re-checked against a live cloud session 2026-09-20):
#   - runs as root on Ubuntu 24.04, before Claude Code launches
#   - MUST exit zero, or the session fails to start
#   - must finish well inside five minutes
#   - github.com is on the default Trusted allowlist
#   - ripgrep, jq, git, uv, node, python3 are ALREADY installed; do not reinstall
#   - gh is NOT installed, despite the official installed-tools list naming it. This
#     script does not install it either: nothing here needs it, and the supported route
#     for GitHub work in a cloud session is the GitHub MCP tools or plain git.
#
# Because a non-zero exit breaks the session, every step below is best-effort and the
# script ends with an unconditional `exit 0`.

set -uo pipefail          # deliberately NOT -e; and never -x, which would echo the token

log() { printf '[toolkit-setup] %s\n' "$*"; }

# --- 1. report the tools we rely on, install only what is genuinely absent -----------
check_tools() {
  # The COMMAND and the DEBIAN PACKAGE are not the same string for every tool, and the
  # previous version passed the command name straight to apt: `apt-get install rg node`
  # fails, because those packages are `ripgrep` and `nodejs`. It failed silently, too,
  # since every step here swallows errors.
  pkg_for() {
    case "$1" in
      rg)   printf 'ripgrep' ;;
      node) printf 'nodejs'  ;;
      *)    printf '%s' "$1" ;;
    esac
  }
  local missing="" packages=""
  for t in git jq python3; do          # the tools this toolkit actually uses
    if ! command -v "$t" >/dev/null 2>&1; then
      missing="$missing $t"
      packages="$packages $(pkg_for "$t")"
    fi
  done
  if [ -n "$missing" ]; then
    log "not pre-installed:$missing — attempting apt as:$packages (root, no sudo needed)"
    apt-get update -qq >/dev/null 2>&1 || log "apt update failed; continuing"
    # shellcheck disable=SC2086
    apt-get install -y -qq $packages >/dev/null 2>&1 || log "apt install failed; continuing"
    for t in $missing; do
      command -v "$t" >/dev/null 2>&1 || log "STILL MISSING after apt: $t"
    done
  else
    log "all required tools pre-installed"
  fi
}

# --- 2. optional: clone this toolkit into a single-repo session ----------------------
# Preferred: leave TOOLKIT_TOKEN unset. Cloud sessions authenticate GitHub through a
# proxy, so a plain clone often succeeds for a repository the Claude GitHub App is
# installed on, with no credential in the environment at all. The token path is a
# fallback for when it does not.
install_toolkit() {
  [ -n "${TOOLKIT_REPO:-}" ] || { log "TOOLKIT_REPO unset — nothing to clone (normal when the toolkit is a project repository)"; return 0; }

  local dest="${HOME}/.claude-toolkit"
  [ -d "$dest/.git" ] && { log "toolkit already present at $dest"; return 0; }   # idempotent

  local ok=1
  if [ -z "${TOOLKIT_TOKEN:-}" ]; then
    log "cloning ${TOOLKIT_REPO} via the session's GitHub proxy (no token in the environment)"
    git clone --depth 1 --quiet "https://github.com/${TOOLKIT_REPO}.git" "$dest" 2>/dev/null && ok=0
  else
    log "cloning ${TOOLKIT_REPO} with TOOLKIT_TOKEN"
    local askpass; askpass="$(mktemp)"; chmod 700 "$askpass"
    printf '#!/bin/sh\nexec printf %%s "$TOOLKIT_TOKEN"\n' > "$askpass"
    GIT_ASKPASS="$askpass" GIT_TERMINAL_PROMPT=0 \
      git clone --depth 1 --quiet \
        "https://x-access-token@github.com/${TOOLKIT_REPO}.git" "$dest" 2>/dev/null && ok=0
    rm -f "$askpass"
  fi

  if [ "$ok" -ne 0 ]; then
    log "WARN clone failed — the session will start WITHOUT the toolkit."
    log "     Check: the Claude GitHub App is installed on ${TOOLKIT_REPO}, or"
    log "     TOOLKIT_TOKEN has read access to it. Not failing the session."
    return 0
  fi

  # Copies, not symlinks: only a <skill-name> ENTRY is documented as symlinkable, and a
  # copy needs no such guarantee.
  mkdir -p "${HOME}/.claude/agents" "${HOME}/.claude/skills"
  cp -f "${dest}"/.claude/agents/*.md "${HOME}/.claude/agents/" 2>/dev/null
  log "agents installed: $(find "${HOME}/.claude/agents" -name '*.md' 2>/dev/null | wc -l)"
  cp -rLf "${dest}"/skills/. "${HOME}/.claude/skills/" 2>/dev/null
  log "skills installed: $(find "${HOME}/.claude/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)"
  # This note used to assert that ~/.claude/skills is NOT read by cloud sessions. That is
  # stronger than anything this repository has established: what is documented is that a
  # cloud session does not receive the USER'S OWN ~/.claude from their machine, which says
  # nothing about a directory this script writes inside the session's own container before
  # Claude Code launches. Neither copy below is verified to be discovered. They are kept
  # because they are cheap and harmless, and labelled honestly.
  log "NOTE neither copy above is verified to be discovered by a cloud session."
  log "     What IS measured: a repository added to the project delivers its .claude/skills/"
  log "     and .claude/agents/. That is the reliable route. See cloud/README.md."
}

check_tools
install_toolkit
log "done"
exit 0                      # never fail the session
