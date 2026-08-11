#!/bin/bash
# Render the application icon into a hicolor theme tree.
#
# Two source drawings, not one. The detailed icon is correct from 48 pixels up;
# below that its package pins dissolve into a dotted fringe that eats the
# silhouette and its five waveform bars merge into a block. The simplified
# drawing drops the pins and keeps three fat bars, which still reads as a chip
# with a voice in it at the size panels and title bars actually use.
#
# Missing rsvg-convert is fatal by default. A package built without it would
# carry the scalable icon alone and install perfectly happily, so the omission
# would only show up as a missing icon on someone's desktop — which is why
# every packaging definition declares the rasteriser as a build dependency.
# Installing into a home directory is the one case where degrading is right,
# since a user cannot be required to have librsvg, and install.sh says so with
# --allow-scalable-only.
#
# Usage: render-icons.sh [--allow-scalable-only] <destination-icon-dir>
#   e.g. render-icons.sh /usr/share/icons/hicolor
#        render-icons.sh --allow-scalable-only "$HOME/.local/share/icons/hicolor"
set -euo pipefail

ALLOW_SCALABLE_ONLY=false
DESTINATION=""
for argument in "$@"; do
  case "$argument" in
    --allow-scalable-only) ALLOW_SCALABLE_ONLY=true ;;
    -*) echo "Unknown option: $argument" >&2; exit 2 ;;
    *) DESTINATION="$argument" ;;
  esac
done
: "${DESTINATION:?usage: render-icons.sh [--allow-scalable-only] <destination-icon-dir>}"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../packaging/icons" && pwd)"
NAME="intel-npu-tools"

SMALL_SIZES=(16 22 24 32)
LARGE_SIZES=(48 64 128 256 512)

# The scalable copy is what modern desktops prefer, and it is the only thing
# that works if no rasteriser is installed.
install -Dm644 "$SOURCE_DIR/$NAME.svg" "$DESTINATION/scalable/apps/$NAME.svg"

if ! command -v rsvg-convert >/dev/null; then
  if $ALLOW_SCALABLE_ONLY; then
    echo "rsvg-convert not found; installed the scalable icon only." >&2
    echo "Install librsvg2-bin (Debian), librsvg (Arch) or librsvg2-tools (Fedora) for PNG sizes." >&2
    exit 0
  fi
  echo "rsvg-convert not found, so only the scalable icon could be installed." >&2
  echo "A package must not ship an incomplete icon theme, so this is an error." >&2
  echo "Install librsvg2-bin (Debian), librsvg (Arch) or librsvg2-tools (Fedora)," >&2
  echo "or pass --allow-scalable-only if this is an install into a home directory." >&2
  exit 1
fi

for size in "${SMALL_SIZES[@]}"; do
  target="$DESTINATION/${size}x${size}/apps/$NAME.png"
  mkdir -p "$(dirname "$target")"
  rsvg-convert -w "$size" -h "$size" "$SOURCE_DIR/$NAME-small.svg" -o "$target"
done

for size in "${LARGE_SIZES[@]}"; do
  target="$DESTINATION/${size}x${size}/apps/$NAME.png"
  mkdir -p "$(dirname "$target")"
  rsvg-convert -w "$size" -h "$size" "$SOURCE_DIR/$NAME.svg" -o "$target"
done

echo "Icons installed under $DESTINATION"
