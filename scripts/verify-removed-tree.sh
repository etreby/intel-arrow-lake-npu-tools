#!/bin/bash
# Check that uninstalling the package really took its files away.
#
# Reads the manifest captured by package-files.sh before the removal, so what
# is checked is everything the package actually owned rather than a handful of
# paths someone remembered to list.
#
# A surviving directory is judged by whether anything is left in it rather than
# by its name. /usr/bin belongs to every package at once and must survive, and
# it survives full; a directory the package brought along has nothing else in
# it once its files are gone, so an empty one that is still there was left
# behind. Judging by name instead would miss a package-owned directory that is
# not named after the package, and would condemn a shared one that is.
#
# The user's data under their home directory is not considered here at all:
# removing a package must never delete it, which is why no maintainer script
# touches it.
#
# Usage: verify-removed-tree.sh <manifest-file> [package-name]
set -euo pipefail

MANIFEST="${1:?usage: verify-removed-tree.sh <manifest-file> [package-name]}"
test -s "$MANIFEST" || { echo "empty or missing manifest: $MANIFEST" >&2; exit 1; }

owned_by_another_package() {
  if command -v rpm >/dev/null; then
    rpm -qf "$1" >/dev/null 2>&1
  elif command -v pacman >/dev/null; then
    pacman -Qo "$1" >/dev/null 2>&1
  elif command -v dpkg-query >/dev/null; then
    dpkg-query -S "$1" >/dev/null 2>&1
  else
    return 1
  fi
}

left=()
checked=0
# `|| [ -n "$path" ]` so a last line with no trailing newline is still read,
# and IFS= so a path with leading or trailing spaces survives intact.
while IFS= read -r path || [ -n "$path" ]; do
  [ -n "$path" ] || continue
  # A manifest is a list of absolute paths. Anything else means the capture
  # went wrong — an error message written where the list should be would
  # otherwise look like a set of paths that are all satisfyingly absent.
  case "$path" in
    /*) ;;
    *) echo "not a path, so this is not a manifest: $path" >&2; exit 1 ;;
  esac
  checked=$((checked + 1))
  # A path that is gone is the expected case, including a broken symlink,
  # which -e alone would miss.
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    continue
  fi
  if [ -d "$path" ] && [ ! -L "$path" ]; then
    # This package is gone by now, so anyone still claiming the directory is
    # another package that needs it. Ownership rather than emptiness is what
    # decides: a theme directory like icons/hicolor/48x48/apps belongs to
    # hicolor-icon-theme and may well be left empty once this package's icon
    # goes, and taking that as a leak would fail a perfectly clean removal.
    if owned_by_another_package "$path"; then
      continue
    fi
    if [ -n "$(ls -A -- "$path" 2>/dev/null)" ]; then
      continue                     # something else is living in it
    fi
    left+=("$path (an empty directory no package owns)")
    continue
  fi
  left+=("$path")
done < "$MANIFEST"

test "$checked" -gt 0 || { echo "the manifest listed nothing: $MANIFEST" >&2; exit 1; }

if [ ${#left[@]} -gt 0 ]; then
  echo "Removing the package left ${#left[@]} of its own path(s) behind:" >&2
  printf '  %s\n' "${left[@]}" >&2
  exit 1
fi

echo "Removal took away everything the package owned, and nothing shared."
