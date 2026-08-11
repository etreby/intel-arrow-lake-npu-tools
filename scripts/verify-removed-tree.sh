#!/bin/bash
# Check that uninstalling the package took its own files away and left
# everyone else's alone.
#
# Reads what package-files.sh --with-state recorded before the removal, so
# what is checked is everything the package actually owned rather than a
# handful of paths someone remembered to list. That capture has to happen
# first because neither fact it records survives the removal: once a directory
# is gone, nothing can be asked about who else needed it.
#
# Three rules, and the third is the one a simpler check gets wrong:
#
#   a file the package owned          must be gone
#   a directory nobody else claimed   must be gone, unless something else has
#                                     since moved into it
#   a directory somebody else claimed must STILL BE THERE — /usr/bin belongs
#                                     to every package at once, and a removal
#                                     that takes it has done real damage. A
#                                     check that only looks for leftovers
#                                     calls that a clean uninstall.
#
# The user's data under their home directory is not considered here at all:
# removing a package must never delete it, which is why no maintainer script
# touches it.
#
# Usage: verify-removed-tree.sh <manifest-file>
set -euo pipefail

MANIFEST="${1:?usage: verify-removed-tree.sh <manifest-file>}"
test -s "$MANIFEST" || { echo "empty or missing manifest: $MANIFEST" >&2; exit 1; }

left=()
destroyed=()
checked=0

# `|| [ -n "$line" ]` so a last line with no trailing newline is still read.
while IFS= read -r line || [ -n "$line" ]; do
  [ -n "$line" ] || continue
  IFS=$'\t' read -r kind owner path <<< "$line"
  # The manifest is three tab-separated fields ending in an absolute path.
  # Anything else means the capture went wrong, and an error message written
  # where the list should be would otherwise read as a set of paths that are
  # all satisfyingly absent.
  case "$kind:$owner:$path" in
    file:own:/*|file:shared:/*|directory:own:/*|directory:shared:/*) ;;
    *) echo "not a package-files.sh --with-state record: $line" >&2; exit 1 ;;
  esac
  checked=$((checked + 1))

  present=false
  if [ -e "$path" ] || [ -L "$path" ]; then
    present=true
  fi

  if [ "$kind" = directory ] && [ "$owner" = shared ]; then
    $present || destroyed+=("$path")
    continue
  fi
  $present || continue
  if [ "$kind" = directory ]; then
    # Nobody else claimed it, so it should have gone with the package. If
    # something has since moved in, that is not this package's leftover.
    if [ -n "$(ls -A -- "$path" 2>/dev/null)" ]; then
      continue
    fi
    left+=("$path (an empty directory no other package owns)")
    continue
  fi
  left+=("$path")
done < "$MANIFEST"

test "$checked" -gt 0 || { echo "the manifest listed nothing: $MANIFEST" >&2; exit 1; }

status=0
if [ ${#destroyed[@]} -gt 0 ]; then
  echo "Removing the package destroyed ${#destroyed[@]} directory(s) other packages own:" >&2
  printf '  %s\n' "${destroyed[@]}" >&2
  status=1
fi
if [ ${#left[@]} -gt 0 ]; then
  echo "Removing the package left ${#left[@]} of its own path(s) behind:" >&2
  printf '  %s\n' "${left[@]}" >&2
  status=1
fi
[ "$status" -eq 0 ] || exit "$status"

echo "Removal took away all $checked of its own paths, and nothing shared."
