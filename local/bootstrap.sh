#!/usr/bin/env bash
# bootstrap.sh — install this toolkit into a local Claude Code configuration.
#
# Idempotent: running it twice changes nothing the second time.
# Additive: it never deletes your content. Anything it would replace is backed up first.
# Reversible: --uninstall removes only the links this script created.
#
#   ./local/bootstrap.sh              link agents + skills, then report
#   ./local/bootstrap.sh --dry-run    show every action, change nothing
#   ./local/bootstrap.sh --check      verify only (alias for doctor.sh)
#   ./local/bootstrap.sh --uninstall  remove links this toolkit owns
#   ./local/bootstrap.sh --with-plugins    also install marketplaces/plugins from profile/
#   ./local/bootstrap.sh --with-packs      also link skills from checked-out skill packs
#
# --with-packs is OPT-IN, and so is every pack. A pack lives in its own repository (see
# packs/ for the specifications); point this script at a checkout with
# PACK_<NAME>_DIR, upper-cased with dashes as underscores:
#
#   PACK_CLOUDFLARE_DIR=~/src/claude-skills-cloudflare ./local/bootstrap.sh --with-packs
#
# A pack with no directory set is reported and skipped, not failed on: not having a pack
# checked out is the normal case, which is the whole point of moving them out of here.
#
# Machine-specific paths are discovered, never hard-coded: the toolkit root comes from
# this script's own location, and the Claude config directory from CLAUDE_CONFIG_DIR
# (falling back to ~/.claude), which is the same variable Claude Code itself honours.

set -euo pipefail

TOOLKIT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${CLAUDE_DIR}/backups/toolkit-bootstrap-${STAMP}"

DRY_RUN=0; UNINSTALL=0; WITH_PLUGINS=0; CHECK_ONLY=0; WITH_PACKS=0
for arg in "$@"; do
  case "$arg" in
    --dry-run)      DRY_RUN=1 ;;
    --uninstall)    UNINSTALL=1 ;;
    --with-plugins)  WITH_PLUGINS=1 ;;
    --with-packs)   WITH_PACKS=1 ;;
    --check)        CHECK_ONLY=1 ;;
    -h|--help)      sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

linked=0; skipped=0; backed_up=0; removed=0; problems=0

say()  { printf '%s\n' "$*"; }
act()  { if [ "$DRY_RUN" -eq 1 ]; then printf '  would %s\n' "$*"; else printf '  %s\n' "$*"; fi; }
warn() { printf '  ! %s\n' "$*" >&2; problems=$((problems + 1)); }

# --- link one path, preserving anything already there -------------------------------
link_one() {
  local src="$1" dest="$2" label="$3"

  if [ -L "$dest" ]; then
    if [ "$(readlink -- "$dest")" = "$src" ]; then
      skipped=$((skipped + 1)); return 0            # already correct — idempotent no-op
    fi
    # A symlink we do not own. Only replace it if it points inside this toolkit.
    case "$(readlink -f -- "$dest" 2>/dev/null || echo)" in
      "$TOOLKIT_ROOT"/*) : ;;
      *) warn "$label: symlink points outside this toolkit ($(readlink -- "$dest")) — left alone"; return 0 ;;
    esac
  elif [ -e "$dest" ]; then
    # A real file or directory. Never clobber it silently.
    act "back up $label -> ${BACKUP_DIR#"$HOME"/}/"
    if [ "$DRY_RUN" -eq 0 ]; then
      mkdir -p "$BACKUP_DIR"
      mv -- "$dest" "$BACKUP_DIR/"
    fi
    backed_up=$((backed_up + 1))
  fi

  act "link $label"
  if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p -- "$(dirname -- "$dest")"
    ln -sfn -- "$src" "$dest"
  fi
  linked=$((linked + 1))
}

unlink_one() {
  local dest="$1" label="$2"
  [ -L "$dest" ] || return 0
  case "$(readlink -f -- "$dest" 2>/dev/null || echo)" in
    "$TOOLKIT_ROOT"/*) act "remove $label"; [ "$DRY_RUN" -eq 0 ] && rm -- "$dest"; removed=$((removed + 1)) ;;
    *) : ;;                                          # not ours; leave it
  esac
  return 0
}

# --- the two content surfaces --------------------------------------------------------
do_agents() {
  say "agents -> ${CLAUDE_DIR#"$HOME"/}/agents/"
  local f name
  for f in "$TOOLKIT_ROOT"/.claude/agents/*.md; do
    [ -e "$f" ] || continue
    name="$(basename -- "$f")"
    if [ "$UNINSTALL" -eq 1 ]; then unlink_one "$CLAUDE_DIR/agents/$name" "$name"
    else link_one "$f" "$CLAUDE_DIR/agents/$name" "$name"; fi
  done
}

do_skills() {
  say "skills -> ${CLAUDE_DIR#"$HOME"/}/skills/"
  local d name
  for d in "$TOOLKIT_ROOT"/skills/*/; do
    [ -d "$d" ] || continue
    name="$(basename -- "$d")"
    if [ "$UNINSTALL" -eq 1 ]; then unlink_one "$CLAUDE_DIR/skills/$name" "$name"
    else link_one "${d%/}" "$CLAUDE_DIR/skills/$name" "$name"; fi
  done
}

# --- optional: link skills from a checked-out skill pack ------------------------------
# A pack is a separate repository built from packs/<name>.json. Nothing here is linked
# unless --with-packs is given AND that pack's directory is set, because an optional
# pack that links itself is not optional.
do_packs() {
  local specs="$TOOLKIT_ROOT/packs"
  [ -d "$specs" ] || { warn "no packs/ directory"; return 0; }
  command -v jq >/dev/null 2>&1 || { warn "jq not found — cannot read the pack specs"; return 0; }
  say "pack skills -> ${CLAUDE_DIR#"$HOME"/}/skills/"

  local spec name var dir skill
  for spec in "$specs"/*.json; do
    [ -e "$spec" ] || continue
    name="$(basename "$spec" .json)"
    var="PACK_$(printf '%s' "$name" | tr '[:lower:]-' '[:upper:]_')_DIR"
    dir="${!var-}"
    if [ -z "$dir" ]; then
      [ "$UNINSTALL" -eq 1 ] || say "  $name: not checked out — set $var to link it"
    elif [ ! -d "$dir/skills" ]; then
      warn "$name: $var=$dir has no skills/ — build it with tools/vendor-sync.py --pack"
      continue
    fi
    while IFS= read -r skill; do
      [ -n "$skill" ] || continue
      if [ "$UNINSTALL" -eq 1 ]; then
        unlink_one "$CLAUDE_DIR/skills/$skill" "$skill"
      elif [ -n "$dir" ] && [ -d "$dir/skills/$skill" ]; then
        link_one "$dir/skills/$skill" "$CLAUDE_DIR/skills/$skill" "$skill"
      fi
    done < <(jq -r '.skills | keys[]' "$spec")
  done
}


# --- optional: reconstruct the plugin composition from the profile -------------------
# Machine/account composition, not toolkit content. It moved out of manifest/ and out
# of the repository's own .claude/settings.json on 2026-09-20: those two settings keys
# were measured that day not to deliver plugins in cloud, so declaring them there
# stated a capability that does not exist. They work locally, so they live here.
do_plugins() {
  local mf="$TOOLKIT_ROOT/profile/plugins.json"
  say "plugins (from ${mf#"$TOOLKIT_ROOT"/})"
  command -v jq >/dev/null 2>&1    || { warn "jq not found — cannot read the manifest"; return 0; }
  command -v claude >/dev/null 2>&1 || { warn "claude not found on PATH — skipping"; return 0; }

  local name src repo url
  while IFS=$'\t' read -r name src repo url; do
    [ -n "$name" ] || continue
    case "$src" in
      github) act "marketplace add $repo";  [ "$DRY_RUN" -eq 0 ] && claude plugin marketplace add "$repo" || true ;;
      git)    act "marketplace add $url";   [ "$DRY_RUN" -eq 0 ] && claude plugin marketplace add "$url"  || true ;;
      *)      warn "marketplace $name is '$src' scope — machine-specific, cannot be reconstructed here" ;;
    esac
  done < <(jq -r '.marketplaces | to_entries[]
                  | select(.value.scope == "portable")
                  | [.key, .value.source.source, (.value.source.repo // ""), (.value.source.url // "")]
                  | @tsv' "$mf")

  # Install every plugin whose marketplace is reachable. That is a LOCAL decision and is
  # deliberately broader than `cloud`: claude-mem and clangd-lsp are useful on a machine
  # and simply cannot follow to a cloud session.
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    act "plugin install $name"
    [ "$DRY_RUN" -eq 0 ] && claude plugin install "$name" || true
  done < <(jq -r --slurpfile m "$mf" '
             .plugins | to_entries[]
             | .key as $k
             | ($k | split("@")[1]) as $mk
             | select($m[0].marketplaces[$mk].scope == "portable")
             | $k' "$mf")
}

# --- main ----------------------------------------------------------------------------
if [ "$CHECK_ONLY" -eq 1 ]; then exec "$TOOLKIT_ROOT/local/doctor.sh"; fi

say "toolkit : $TOOLKIT_ROOT"
say "config  : $CLAUDE_DIR"
[ "$DRY_RUN" -eq 1 ] && say "mode    : DRY RUN — nothing will be changed"
[ "$UNINSTALL" -eq 1 ] && say "mode    : UNINSTALL"
say ""

# A dry run must work on a machine that has never run Claude Code -- that is exactly the
# machine someone points this at to see what it would do. Only a real run needs the
# directory, and a real run creates it rather than refusing.
if [ ! -d "$CLAUDE_DIR" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    act "create $CLAUDE_DIR"
  elif [ "$UNINSTALL" -eq 1 ]; then
    say "no Claude config directory at $CLAUDE_DIR — nothing installed, nothing to remove"
    exit 0
  else
    mkdir -p "$CLAUDE_DIR" || { printf 'cannot create %s\n' "$CLAUDE_DIR" >&2; exit 1; }
    say "created $CLAUDE_DIR"
  fi
fi

do_agents; say ""
do_skills
if [ "$WITH_PACKS" -eq 1 ] || [ "$UNINSTALL" -eq 1 ]; then say ""; do_packs; fi
if [ "$WITH_PLUGINS" -eq 1 ] && [ "$UNINSTALL" -eq 0 ]; then say ""; do_plugins; fi

say ""
if [ "$UNINSTALL" -eq 1 ]; then
  say "removed $removed link(s). Nothing else was touched."
else
  say "linked $linked, already correct $skipped, backed up $backed_up, problems $problems"
  [ "$backed_up" -gt 0 ] && say "backups: $BACKUP_DIR"
  [ "$WITH_PACKS" -eq 0 ] && say "pack skills not linked — add --with-packs (see packs/README.md)"
  [ "$WITH_PLUGINS" -eq 0 ] && say "plugins not touched — add --with-plugins to install them from the manifest"
fi
[ "$problems" -eq 0 ] || exit 1
