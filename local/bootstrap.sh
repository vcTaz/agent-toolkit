#!/usr/bin/env bash
# bootstrap.sh — install this toolkit into a local Claude Code configuration.
#
# Idempotent: running it twice changes nothing the second time.
# Additive: it never deletes your content. Anything it would replace is backed up first.
# Reversible: --uninstall removes what its own record names, and -- only where there is no
#             record -- links SHAPED like the ones it creates (NAME -> .../NAME) into a
#             pack or a toolkit checkout. Never anything else.
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
#
# WHAT WAS INSTALLED IS RECORDED, not guessed. Every link this script creates is written
# to .toolkit-install-state.tsv in the config directory, as the destination and the exact
# target. --uninstall removes a recorded link only while it is still a symlink pointing
# at the recorded target; a path you have since replaced or repointed is left alone and
# reported.
#
# WITH NO RECORD -- an install made by an older copy of this script, which is every
# install in existence until this lands -- a link is recognised by its shape and its far
# end instead. Shape first: this script only ever creates NAME -> .../NAME, so a link
# whose two ends disagree is somebody else's whatever it points into. Then the far end:
# a skill pack identifies itself by PACK.json + PROVENANCE.json at its root, a checkout
# of this toolkit by AGENTS.md + tools/check.py. That catches a link made by a DIFFERENT
# checkout, which comparing against this script's own location cannot. A link into
# neither is somebody else's and is never touched.
#
# The closing summary is COMPUTED, not asserted: before claiming nothing else was
# touched, the config directory is re-read for links this toolkit demonstrably created
# and still left behind, and for BROKEN links, whose targets are gone and which therefore
# cannot be attributed to anyone -- they are named and left alone, never guessed at. The
# claim is withheld when either count is non-zero, and the run exits 1, because an
# uninstall that did not undo cleanly should not report success.

set -euo pipefail

TOOLKIT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
# Canonicalise it. Every recorded destination and every path compared later is built from
# this string, so "$HOME/.claude", "$HOME/.claude/", "B/base/./cfg" and a symlink to the
# same directory must not be five different keys. They were: uninstalling through a
# different spelling made the record pass and the fallback disagree about one path, which
# deleted a link reported as "left alone" and made --dry-run double its count.
#
# It must work when the directory does NOT yet exist, which is the first install -- the
# run that creates it, and the run that writes every row of the record. A `cd` guarded by
# `[ -d ]` skipped exactly that case, so a first install on a machine whose $HOME is a
# symlink recorded one spelling and every later run compared against another.
canonical_path() {
  local p="$1" suffix="" base resolved skip=0
  case "$p" in /*) ;; *) p="$PWD/$p" ;; esac
  # Walk left to the deepest component that exists, normalising the part that does not.
  # Re-attaching the missing tail VERBATIM was the earlier bug: "$HOME/miss/./cfg" came
  # back with the "./" still in it, so the first install recorded one spelling and every
  # later run -- finding the directory present and normalising it through cd -- compared
  # another. "." is dropped; ".." cancels the component to its left, and any left over
  # when the walk stops is applied to the resolved ancestor.
  while [ ! -d "$p" ] && [ "$p" != "/" ] && [ -n "$p" ]; do
    base="$(basename -- "$p")"
    p="$(dirname -- "$p")"
    case "$base" in
      .)  ;;
      ..) skip=$((skip + 1)) ;;
      *)  if [ "$skip" -gt 0 ]; then skip=$((skip - 1))
          else suffix="/$base$suffix"; fi ;;
    esac
  done
  # An ancestor that cannot be entered must FAIL, not silently yield the empty string --
  # which re-anchored the whole path at the filesystem root.
  resolved="$(cd -- "$p" 2>/dev/null && pwd -P)" || return 1
  [ -n "$resolved" ] || return 1
  while [ "$skip" -gt 0 ]; do resolved="$(dirname -- "$resolved")"; skip=$((skip - 1)); done
  # "/" plus "/x" would be "//x", which no later run reproduces. And the root itself must
  # come back as "/", not as the empty string.
  # An explicit `if`, not `[ ... ] && resolved=""`. Measured: bash does NOT abort on a
  # failing `&&` list in the middle of a body, so the `&&` form was not a live bug here.
  # It becomes one the moment it ends up LAST in a function -- the list's status is then
  # the function's, and this test fails for every path that is not the root, which is
  # almost all of them. That is exactly how this script lost a block once before, so the
  # form is not kept anywhere it could drift to the end.
  if [ "$resolved" = "/" ]; then resolved=""; fi
  # sed does three things here: an empty result is the root; a leading "//" is
  # implementation-defined and POSIX allows pwd -P to return it, so collapse it; and a
  # doubled slash anywhere else is redundant.
  printf '%s\n' "${resolved}${suffix}" | sed -e 's|//*|/|g' -e 's|^$|/|' -e 's|^\(.\)/$|\1|'
}

CLAUDE_DIR="$(canonical_path "$CLAUDE_DIR")" || {
  printf 'cannot resolve %s — is a parent directory readable?\n' \
    "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" >&2
  exit 1
}
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
    -h|--help)      sed -n '2,46p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

linked=0; skipped=0; backed_up=0; removed=0; problems=0; kept=0; stranded=0; broken=0

say()  { printf '%s\n' "$*"; }
act()  { if [ "$DRY_RUN" -eq 1 ]; then printf '  would %s\n' "$*"; else printf '  %s\n' "$*"; fi; }
warn() { printf '  ! %s\n' "$*" >&2; problems=$((problems + 1)); }

# --- the install-state record --------------------------------------------------------
# One TAB-separated line per link: destination, then the exact target it was created
# with. Plain text and read with plain shell, deliberately: uninstall must not depend on
# jq, which manifest/binaries.json classifies as optional.
STATE_FILE="${CLAUDE_DIR}/.toolkit-install-state.tsv"
RUN_STATE=""

record_link() {
  [ "$DRY_RUN" -eq 0 ] || return 0
  [ -n "$RUN_STATE" ] || RUN_STATE="$(mktemp)"
  printf '%s\t%s\n' "$1" "$2" >> "$RUN_STATE"
}

# Merge: what this run linked, plus earlier records whose link is still exactly as
# recorded. A run without --with-packs must not forget the packs an earlier run linked.
write_state() {
  [ "$DRY_RUN" -eq 0 ] || return 0
  local merged; merged="$(mktemp)"
  [ -n "$RUN_STATE" ] && cat "$RUN_STATE" >> "$merged"
  if [ -f "$STATE_FILE" ]; then
    local dest target
    while IFS=$'\t' read -r dest target; do
      [ -n "${dest:-}" ] || continue
      case "$dest" in '#'*) continue ;; esac
      [ -n "$RUN_STATE" ] && cut -f1 "$RUN_STATE" | grep -qxF "$dest" && continue
      [ -L "$dest" ] && [ "$(readlink -- "$dest")" = "$target" ] \
        && printf '%s\t%s\n' "$dest" "$target" >> "$merged"
    done < "$STATE_FILE"
  fi
  if [ -s "$merged" ]; then
    mkdir -p -- "$(dirname -- "$STATE_FILE")"
    sort -u "$merged" > "$STATE_FILE.tmp" && mv -- "$STATE_FILE.tmp" "$STATE_FILE"
  else
    rm -f -- "$STATE_FILE"
  fi
  rm -f -- "$merged"
  [ -n "$RUN_STATE" ] && rm -f -- "$RUN_STATE"
  return 0
}

# --- link one path, preserving anything already there -------------------------------
link_one() {
  local src="$1" dest="$2" label="$3"

  if [ -L "$dest" ]; then
    if [ "$(readlink -- "$dest")" = "$src" ]; then
      record_link "$dest" "$src"                    # already correct, but still ours
      skipped=$((skipped + 1)); return 0            # idempotent no-op
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
  record_link "$dest" "$src"
  linked=$((linked + 1))
}

# Remove one link only if it is still exactly what was recorded. A path the user has
# since replaced with their own file, or repointed somewhere else, is theirs now.
# A token present in this toolkit's tools/check.py and unlikely anywhere else. Renaming it
# there would silently stop uninstall recognising a checkout, so tools/test.sh asserts that
# this exact string is still in that file.
TOOLKIT_MARKER='CANONICAL_TREES'

# Does $1 have the shape of a link this script creates -- NAME -> .../NAME? Compares the
# link's own name with the last component of its target, reading the target as TEXT, so a
# broken link is answered too.
same_name() {
  local dest="$1" target
  target="$(readlink -- "$dest" 2>/dev/null || echo)"
  [ -n "$target" ] || return 1
  [ "${dest##*/}" = "${target%/}" ] || [ "${dest##*/}" = "$(basename -- "$target")" ]
}

# What does $1 point into -- a skill PACK, a checkout of this TOOLKIT, or neither?
# Answered from the far end of the link, by the metadata each kind carries: a pack root
# holds PACK.json and PROVENANCE.json, a toolkit checkout holds AGENTS.md and
# tools/check.py. Nothing is guessed from a path and no PACK_<NAME>_DIR is read -- those
# are unset at uninstall, which is the whole reason guessing fails. This also recognises
# a link made by a DIFFERENT checkout of this toolkit, which $TOOLKIT_ROOT cannot.
# Echoes "pack", "toolkit" or nothing.
# The marker test on a DIRECTORY, so the installer can ask the same question the
# uninstaller will ask later. One implementation, both directions.
link_owner_of_dir() {
  local here="$1" i=0
  while [ "$i" -lt 5 ] && [ "$here" != "/" ] && [ -n "$here" ]; do
    # The markers are READ, not merely counted. Two empty files named PACK.json and
    # PROVENANCE.json used to be enough to delete somebody else's symlink, and an empty
    # AGENTS.md beside an empty tools/check.py was enough to call their repository a
    # checkout of this toolkit. A pack is identified the way tools/vendor-sync.py
    # identifies one -- by PROVENANCE.json naming the tool that wrote it -- and a toolkit
    # checkout by a token that only this checker contains.
    if [ -f "$here/PACK.json" ] && [ -f "$here/PROVENANCE.json" ] \
       && grep -q '"vendoredBy"[[:space:]]*:[[:space:]]*"tools/vendor-sync\.py[ "]' \
                  "$here/PROVENANCE.json" 2>/dev/null; then
      printf 'pack\n'; return 0
    fi
    if [ -f "$here/AGENTS.md" ] && [ -f "$here/tools/check.py" ] \
       && grep -q "$TOOLKIT_MARKER" "$here/tools/check.py" 2>/dev/null; then
      printf 'toolkit\n'; return 0
    fi
    here="$(dirname -- "$here")"; i=$((i + 1))
  done
  return 0
}

# The names this toolkit installs: its own skills and agents, plus every skill name in
# every pack specification. Read from the specs with sed, not jq, because --uninstall must
# work without it. Used only to decide whether a BROKEN link -- whose target is gone, so
# nothing can be read at the far end -- might be one of ours.
INSTALLED_NAMES=""
installs_name() {
  local spec
  if [ -z "$INSTALLED_NAMES" ]; then
    INSTALLED_NAMES="$( { for f in "$TOOLKIT_ROOT"/skills/*/; do
                            [ -e "$f" ] && basename -- "${f%/}"
                          done
                          for f in "$TOOLKIT_ROOT"/.claude/agents/*.md; do
                            [ -e "$f" ] && basename -- "$f"
                          done
                          for spec in "$TOOLKIT_ROOT"/packs/*.json; do
                            [ -e "$spec" ] || continue
                            sed -n '/"skills"[[:space:]]*:[[:space:]]*{/,/^[[:space:]]*}/p' "$spec" \
                              | sed -n 's/^[[:space:]]*"\([^"]*\)"[[:space:]]*:.*/\1/p'
                          done; } 2>/dev/null | sort -u)"
  fi
  printf '%s\n' "$INSTALLED_NAMES" | grep -qxF -- "$1"
}

link_owner() {
  local resolved=""
  [ -L "$1" ] || return 0
  resolved="$(readlink -f -- "$1" 2>/dev/null || echo)"
  [ -n "$resolved" ] || return 0
  link_owner_of_dir "$resolved"
}

unlink_recorded() {
  local dest="$1" target="$2" label="$3"
  if [ ! -L "$dest" ]; then
    if [ -e "$dest" ]; then
      say "  $label: replaced by your own file since install — left alone"
      kept=$((kept + 1))
    fi
    return 0
  fi
  if [ "$(readlink -- "$dest")" != "$target" ]; then
    say "  $label: now points at $(readlink -- "$dest") — left alone"
    kept=$((kept + 1)); return 0
  fi
  act "remove $label"
  [ "$DRY_RUN" -eq 0 ] && rm -- "$dest"
  removed=$((removed + 1))
  return 0
}

# --- the two content surfaces --------------------------------------------------------
do_agents() {
  say "agents -> ${CLAUDE_DIR#"$HOME"/}/agents/"
  local f name
  for f in "$TOOLKIT_ROOT"/.claude/agents/*.md; do
    [ -e "$f" ] || continue
    name="$(basename -- "$f")"
    link_one "$f" "$CLAUDE_DIR/agents/$name" "$name"
  done
}

do_skills() {
  say "skills -> ${CLAUDE_DIR#"$HOME"/}/skills/"
  local d name
  for d in "$TOOLKIT_ROOT"/skills/*/; do
    [ -d "$d" ] || continue
    name="$(basename -- "$d")"
    link_one "${d%/}" "$CLAUDE_DIR/skills/$name" "$name"
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
      say "  $name: not checked out — set $var to link it"
      continue
    elif [ ! -d "$dir/skills" ]; then
      warn "$name: $var=$dir has no skills/ — build it with tools/vendor-sync.py --pack"
      continue
    elif [ "$(link_owner_of_dir "$dir")" != "pack" ]; then
      # The installer's acceptance must not be broader than the uninstaller's
      # recognition, or it creates links nothing can later attribute. It did: any
      # directory with a skills/ subdirectory was linked, while link_owner needs
      # PACK.json and a PROVENANCE.json naming the tool that wrote it. The result was a
      # link this script created, left behind by --uninstall, under a summary that said
      # nothing else was touched.
      warn "$name: $var=$dir is not a pack this tooling built — no PACK.json and"
      warn "  PROVENANCE.json naming tools/vendor-sync.py. Refusing to link from it,"
      warn "  because --uninstall could not recognise those links afterwards."
      continue
    fi
    while IFS= read -r skill; do
      [ -n "$skill" ] || continue
      # An explicit if, not `[ -d ] && link_one`: under `set -e` a trailing false test is
      # the loop's exit status, and a pack missing its last skill would abort the whole
      # run silently, after linking everything before it.
      if [ -d "$dir/skills/$skill" ]; then
        link_one "$dir/skills/$skill" "$CLAUDE_DIR/skills/$skill" "$skill"
      else
        say "  $name/$skill: not in $var — skipped"
      fi
    done < <(jq -r '.skills | keys[]' "$spec")
  done
  return 0
}

# --- uninstall: the record first, then shape-and-far-end for what it does not cover ---
# No pack directory is consulted and no target is guessed. PACK_<NAME>_DIR is documented
# for --with-packs and is normally unset here, which is exactly why guessing fails.
DECIDED=""
already_decided() { [ -n "$DECIDED" ] && grep -qxF -- "$1" "$DECIDED"; }

do_uninstall() {
  say "removing links recorded in ${STATE_FILE#"$HOME"/}"
  DECIDED="$(mktemp)"
  local dest target n=0
  if [ -f "$STATE_FILE" ]; then
    while IFS=$'\t' read -r dest target; do
      [ -n "${dest:-}" ] || continue
      case "$dest" in '#'*) continue ;; esac
      n=$((n + 1))
      printf '%s\n' "$dest" >> "$DECIDED"
      unlink_recorded "$dest" "$target" "$(basename -- "$dest")"
    done < "$STATE_FILE"
    say "  $n recorded"
  else
    say "  no install record — falling back to links this toolkit can still recognise"
  fi

  # An install made before the record existed leaves nothing to read, and every install
  # that exists today is one of those, because this fix is not merged yet. Two kinds are
  # still recoverable without guessing: a link whose target resolves inside this toolkit,
  # and a link whose target is inside something that identifies itself as a pack. Both are
  # recognised from the link, never from a PACK_<NAME>_DIR that is not set here.
  #
  # The record pass above already decided about every path it holds -- including paths it
  # deliberately LEFT ALONE. Re-deciding them here would delete what was just reported as
  # kept, and would double-count under --dry-run, where nothing is removed and both passes
  # therefore see the same link twice.
  # Before this scan an upgrade -- install with an older bootstrap.sh, pull, uninstall --
  # left every pack link behind while the summary said nothing else was touched.
  # Measured: 26 of 26 survived.
  local dest2 name owner
  for dest2 in "$CLAUDE_DIR"/skills/* "$CLAUDE_DIR"/agents/*; do
    [ -L "$dest2" ] || continue
    already_decided "$dest2" && continue
    # Every link this script creates is NAME -> .../NAME: a skill keeps its directory
    # name, an agent keeps its file name. A link whose two ends disagree is therefore
    # not one of ours, whatever it points into. Without this, a link the user made
    # themselves at their own chosen name, into their own pack checkout, was deleted by
    # a run whose record was complete and never mentioned it.
    same_name "$dest2" || continue
    owner="$(link_owner "$dest2")"
    [ -n "$owner" ] || continue
    name="$(basename -- "$dest2")"
    case "$owner" in
      pack)    act "remove $name (unrecorded, but points into a skill pack)" ;;
      toolkit) act "remove $name (unrecorded, but points into a checkout of this toolkit)" ;;
    esac
    [ "$DRY_RUN" -eq 0 ] && rm -- "$dest2"
    removed=$((removed + 1))
  done

  if [ "$DRY_RUN" -eq 0 ] && [ -f "$STATE_FILE" ]; then
    # Keep only what is still ours: a symlink still pointing at the recorded target. A
    # path the user has taken over is no longer a link this script owns, so this script
    # stops claiming it.
    local remaining; remaining="$(mktemp)"
    while IFS=$'\t' read -r dest target; do
      [ -n "${dest:-}" ] || continue
      case "$dest" in '#'*) continue ;; esac
      if [ -L "$dest" ] && [ "$(readlink -- "$dest")" = "$target" ]; then
        printf '%s\t%s\n' "$dest" "$target" >> "$remaining"
      fi
    done < "$STATE_FILE"
    if [ -s "$remaining" ]; then mv -- "$remaining" "$STATE_FILE"
    else rm -f -- "$remaining" "$STATE_FILE"; fi
  fi

  # The summary used to say "Nothing else was touched" unconditionally, which was a claim
  # about the whole config directory made without looking at it. Look at it. Anything
  # still here that this toolkit demonstrably created -- a link into the toolkit, or into
  # something that identifies itself as a pack -- and that was neither removed nor
  # deliberately left alone is counted, so the summary cannot assert a clean undo it did
  # not achieve.
  # Not gated on DRY_RUN: it only reads, and a preview that promises a clean undo the real
  # run will not deliver is worse than no preview.
  if true; then
    local leftover
    for leftover in "$CLAUDE_DIR"/skills/* "$CLAUDE_DIR"/agents/*; do
      [ -L "$leftover" ] || continue
      already_decided "$leftover" && continue
      # The same shape rule as the remover, or this counts the user's own links against
      # us: a link at their chosen name into their own pack is not one we failed to
      # remove, it is one we correctly left alone.
      same_name "$leftover" || continue
      if [ "$DRY_RUN" -eq 0 ] && [ -n "$(link_owner "$leftover")" ]; then
        stranded=$((stranded + 1)); continue
      fi
      # A BROKEN link: its target is gone, so there is nothing left to read and nothing
      # to attribute it by. Deleting it would be guessing about somebody else's path;
      # ignoring it lets the summary claim a clean undo over links this script may well
      # have created -- which it did, silently, when a pack checkout was moved away.
      # Count it, name it, and let the summary withhold the claim.
      # A BROKEN link can only be judged by its name: its target is gone, so there is
      # nothing to read at the far end. Shape alone was not enough -- `ln -s <target>`
      # with no second argument creates NAME -> .../NAME, so any dead symlink of the
      # user's own passed that test and made this script report a failed undo over an
      # uninstall that had in fact removed every link it owned. It must ALSO be a name
      # this toolkit installs.
      if [ ! -e "$leftover" ] && same_name "$leftover" \
         && installs_name "${leftover##*/}"; then
        broken=$((broken + 1))
        say "  ${leftover##*/}: points at $(readlink -- "$leftover"), which no longer exists — cannot tell whose it is, left alone"
      fi
    done
  fi
  rm -f -- "$DECIDED"; DECIDED=""
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

if [ "$UNINSTALL" -eq 1 ]; then
  do_uninstall
else
  do_agents; say ""
  do_skills
  if [ "$WITH_PACKS" -eq 1 ]; then say ""; do_packs; fi
  if [ "$WITH_PLUGINS" -eq 1 ]; then say ""; do_plugins; fi
  write_state
fi

say ""
if [ "$UNINSTALL" -eq 1 ]; then
  if [ "$stranded" -gt 0 ] || [ "$broken" -gt 0 ]; then
    say "removed $removed link(s), left $kept alone."
    # Explicit ifs, not a `[ ] && warn && warn` chain: a false test as the last command of
    # a block is the block's exit status, and under `set -e` that has already cost this
    # script one silent abort. warn() also increments `problems`, so the run exits 1 --
    # an uninstall that did not undo cleanly should not report success.
    if [ "$stranded" -gt 0 ]; then
      warn "$stranded link(s) this toolkit created are still in place and were not recognised."
    fi
    if [ "$broken" -gt 0 ]; then
      warn "$broken broken link(s) remain. Their targets are gone, so this script cannot tell"
      warn "whether it created them. Check them and remove by hand the ones that are its."
    fi
    warn "This run did NOT undo cleanly."
  else
    say "removed $removed link(s), left $kept alone. Nothing else was touched."
  fi
else
  say "linked $linked, already correct $skipped, backed up $backed_up, problems $problems"
  [ "$backed_up" -gt 0 ] && say "backups: $BACKUP_DIR"
  [ "$WITH_PACKS" -eq 0 ] && say "pack skills not linked — add --with-packs (see packs/README.md)"
  [ "$WITH_PLUGINS" -eq 0 ] && say "plugins not touched — add --with-plugins to install them from the manifest"
fi
[ "$problems" -eq 0 ] || exit 1
