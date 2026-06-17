#!/usr/bin/env bash
# install-system.sh — pick a color-emoji set from a terminal menu and install it
# as the macOS *system* emoji font.
#
# Replacing the sealed system font is the only route that changes auto-typed emoji
# in all apps on macOS 10.15+. It requires SIP and authenticated-root to be
# disabled first (see https://github.com/iebb/emojiswap — system-font/README.md).
#
# This script downloads the ready-made sbix build from the iebb/emojifonts
# `latest` release, backs up the original, writes it onto the sealed System
# volume, and re-blesses the boot snapshot. All paths are derived relative to
# this script — nothing is hard-coded.
#
# Usage:
#   ./install-system.sh            # interactive numbered picker
#   sudo ./install-system.sh noto  # non-interactive; re-run with sudo if needed
#   sudo ./install-system.sh apple # restore the backed-up original
#
# If run without sudo the picker is shown, then the script re-invokes itself
# with sudo carrying the chosen key so you only see the menu once.
set -euo pipefail

REPO="iebb/emojifonts"
BASE="https://github.com/$REPO/releases/download/latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"
BACKUP_DIR="${BACKUP_DIR:-$SCRIPT_DIR/backup}"   # overridable; defaults beside this script
BACKUP="$BACKUP_DIR/Apple Color Emoji.ttc.orig"
SYS_FONT="/System/Library/Fonts/Apple Color Emoji.ttc"
TMP="${TMPDIR:-/tmp}/emojiswap-release.ttf"

red(){ printf '\033[31m%s\033[0m\n' "$*"; }
grn(){ printf '\033[32m%s\033[0m\n' "$*"; }
ylw(){ printf '\033[33m%s\033[0m\n' "$*"; }

# Pickable sbix color sets: "key|release-file|label"
# `apple` is a special sentinel that restores the backup.
SETS=(
  "noto|noto.ttf|Google Noto Color Emoji"
  "blobmoji|blobmoji.ttf|Blobmoji (Android blobs)"
  "fluent|fluent.ttf|Microsoft Fluent 3D"
  "twemoji|twemoji.ttf|Twemoji"
  "openmoji|openmoji.ttf|OpenMoji"
  "emojitwo|emojitwo.ttf|EmojiTwo"
  "tossface|tossface.ttf|Toss Face"
  "apple|@restore|Apple — restore the original"
)

list_keys(){ local e; for e in "${SETS[@]}"; do printf '  %s\n' "${e%%|*}"; done; }

# resolve <key> → sets globals FILE and LABEL; returns 1 if unknown
resolve(){
  local e k f l
  for e in "${SETS[@]}"; do
    IFS='|' read -r k f l <<<"$e"
    if [ "$k" = "$1" ]; then FILE="$f"; LABEL="$l"; return 0; fi
  done
  return 1
}

# interactive picker → sets global KEY
choose_set(){
  local labels=() e
  for e in "${SETS[@]}"; do labels+=("${e##*|}"); done
  echo "Pick a system emoji font (downloaded from $REPO):"
  local PS3="Number (Ctrl-C to cancel): "
  local label
  select label in "${labels[@]}"; do
    if [ -n "$label" ]; then KEY="${SETS[$((REPLY-1))]%%|*}"; return 0; fi
    red "  invalid choice"
  done
}

KEY="${1:-}"
[ -n "$KEY" ] || choose_set
if ! resolve "$KEY"; then
  red "unknown set: '$KEY'"
  echo "valid sets:"; list_keys
  exit 1
fi

# Not root → show what was chosen, then re-run with sudo so the menu isn't repeated.
if [ "$(id -u)" -ne 0 ]; then
  ylw "Selected: $LABEL — re-running with sudo to modify the System volume…"
  exec sudo "$SELF" "$KEY"
fi

# ---------- privileged: from here on we are root ----------

# Preflight: authenticated-root must be disabled to write the sealed system volume.
if ! csrutil authenticated-root status 2>/dev/null | grep -qi disabled; then
  red "authenticated-root is still ENABLED — the System volume is sealed."
  ylw "In Recovery, run:  csrutil disable && csrutil authenticated-root disable"
  exit 1
fi

mkdir -p "$BACKUP_DIR"

# Back up the pristine original — never clobber an existing good backup.
if [ -s "$BACKUP" ]; then
  grn "using existing backup: $BACKUP ($(stat -f%z "$BACKUP") bytes)"
else
  echo "backing up original → $BACKUP"
  cp "$SYS_FONT" "$BACKUP"
  grn "backup created ($(stat -f%z "$BACKUP") bytes)"
fi

# Source: the backup (restore) or a fresh download.
if [ "$FILE" = "@restore" ]; then
  SRC="$BACKUP"
  [ -s "$SRC" ] || { red "no backup found at $BACKUP"; exit 1; }
else
  echo "downloading $LABEL → $BASE/$FILE"
  curl -fL --retry 3 "$BASE/$FILE" -o "$TMP"
  [ "$(stat -f%z "$TMP")" -gt 100000 ] || { red "download failed / too small"; rm -f "$TMP"; exit 1; }
  SRC="$TMP"
  trap 'rm -f "$TMP"' EXIT
fi

# Mount the underlying System volume read-write.
# The booted "/" is a sealed, read-only snapshot; we mount its backing volume
# separately (matching the approach in iebb/emojiswap install.sh).
ROOTDEV=$(diskutil info / | awk -F': *' '/Device Node/{print $2}')
SYSVOL=$(printf '%s' "$ROOTDEV" | sed -E 's/s[0-9]+$//')
echo "System volume: $SYSVOL  (booted snapshot: $ROOTDEV)"
MNT=$(mount | awk -v d="$SYSVOL" '$1==d {print $3; exit}')
if [ -z "$MNT" ]; then
  MNT="/System/Volumes/Update/mnt1"
  echo "mounting $SYSVOL at $MNT …"
  mkdir -p "$MNT"
  mount -o nobrowse -t apfs "$SYSVOL" "$MNT"
else
  echo "System volume already mounted at: $MNT"
fi
mount -uw "$MNT" 2>/dev/null || true

TARGET="$MNT/System/Library/Fonts/Apple Color Emoji.ttc"
[ -f "$TARGET" ] || { red "not found on System volume: $TARGET"; exit 1; }

echo "installing font …"
if ! cp "$SRC" "$TARGET" 2>/dev/null; then
  red "could not write $TARGET — is authenticated-root really disabled?"
  exit 1
fi
chown root:wheel "$TARGET"; chmod 644 "$TARGET"

if [ "$(stat -f%z "$TARGET")" != "$(stat -f%z "$SRC")" ]; then
  red "installed file failed size check — restoring backup."
  cp "$BACKUP" "$TARGET"; chown root:wheel "$TARGET"; chmod 644 "$TARGET"
  exit 1
fi
grn "installed & verified on the System volume"

echo "creating + blessing a new boot snapshot …"
bless --mount "$MNT" --create-snapshot --setBoot

echo
grn "Done — installed: $LABEL"
ylw "REBOOT for it to take effect:   sudo reboot"
echo "Undo:                           sudo $SELF apple"
