#!/usr/bin/env bash
# setup.sh — cloud environment setup for Claude Code sessions.
#
# Paste this as the setup script in the cloud environment UI (Claude Code does not read a
# devcontainer.json; a bash setup script plus environment variables is the supported
# mechanism as of 2026-09-19).
#
# It does two things:
#   1. Installs the tools that cloud images do not ship but this toolkit's skills assume.
#   2. Optionally clones the private toolkit and installs its agents and skills into the
#      session, so they are available when the checked-out repo is NOT the toolkit itself.
#
# Step 2 is OPT-IN and does nothing unless both variables below are set in the environment:
#
#   TOOLKIT_REPO   e.g. vcTaz/agent-toolkit-private
#   TOOLKIT_TOKEN  a GitHub PAT, fine-grained, READ-ONLY 'Contents', scoped to that ONE repo
#
# The token is never written to disk, never placed in a URL, never passed as an argument,
# and never printed. It reaches git only through GIT_ASKPASS on a single fd.

set -euo pipefail          # never add -x here; it would echo the token

log() { printf '[setup] %s\n' "$*"; }

# --- 1. tools the cloud image does not ship -----------------------------------------
# Present by default: git, curl, jq, python3, node, go, rust. Absent: ripgrep, uv.
install_tools() {
  if command -v rg >/dev/null 2>&1; then
    log "ripgrep present"
  elif command -v apt-get >/dev/null 2>&1; then
    log "installing ripgrep"
    sudo apt-get update -qq && sudo apt-get install -y -qq ripgrep
  else
    log "WARN ripgrep missing and no apt-get; skills that shell out to rg will degrade"
  fi

  if command -v uv >/dev/null 2>&1; then
    log "uv present"
  else
    log "installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || \
      log "WARN uv install failed; uvx-based MCP servers are unavailable (they are stdio-only anyway, so cloud cannot use them)"
  fi
}

# --- 2. optional private toolkit install --------------------------------------------
install_toolkit() {
  if [ -z "${TOOLKIT_REPO:-}" ] || [ -z "${TOOLKIT_TOKEN:-}" ]; then
    log "TOOLKIT_REPO/TOOLKIT_TOKEN not set — skipping toolkit install (this is fine when the checked-out repo IS the toolkit)"
    return 0
  fi

  local dest="${HOME}/.claude-toolkit"
  local askpass; askpass="$(mktemp)"
  # chmod BEFORE writing, so the token is never briefly world-readable.
  chmod 700 "$askpass"
  printf '#!/bin/sh\nexec printf %%s "$TOOLKIT_TOKEN"\n' > "$askpass"
  # shellcheck disable=SC2064
  trap "rm -f '$askpass'" EXIT INT TERM

  log "cloning ${TOOLKIT_REPO}"
  if GIT_ASKPASS="$askpass" GIT_TERMINAL_PROMPT=0 \
     git clone --depth 1 --quiet \
       "https://x-access-token@github.com/${TOOLKIT_REPO}.git" "$dest" 2>/dev/null
  then
    log "cloned to ${dest}"
  else
    log "ERROR clone failed — check that TOOLKIT_TOKEN has read access to ${TOOLKIT_REPO}"
    return 1
  fi

  rm -f "$askpass"; trap - EXIT INT TERM

  # Install as real copies, not symlinks: symlink handling in cloud sessions is
  # undocumented, and agents are the surface we least want to gamble on.
  mkdir -p "${HOME}/.claude/agents" "${HOME}/.claude/skills"
  if [ -d "${dest}/.claude/agents" ]; then
    cp -f "${dest}"/.claude/agents/*.md "${HOME}/.claude/agents/" 2>/dev/null || true
    log "installed $(find "${dest}/.claude/agents" -name '*.md' | wc -l) agent(s)"
  fi
  if [ -d "${dest}/skills" ]; then
    cp -rf "${dest}"/skills/*/ "${HOME}/.claude/skills/" 2>/dev/null || true
    log "installed $(find "${dest}/skills" -mindepth 1 -maxdepth 1 -type d | wc -l) skill(s)"
  fi
}

install_tools
install_toolkit
log "done"
