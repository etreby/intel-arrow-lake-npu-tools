#!/bin/bash
# Print every path the installed package claims to own, one per line.
#
# The package manager's own manifest is the only authority on what a package
# installed, so both the installed-tree check and the removal check read it
# from here rather than from a hand-written list that would go stale the next
# time a file is added to the staging script.
#
# Fails rather than printing nothing when the package is not installed or the
# query does not work: an empty list would otherwise let every check that
# consumes it pass without comparing anything.
#
# With --with-state each line becomes three tab-separated fields instead:
#
#   <file|directory>  <own|shared>  <path>
#
# Both facts have to be recorded now, while the package is still installed,
# because neither can be recovered afterwards. Once a directory is gone there
# is nothing left to ask whether anybody else needed it.
#
# Usage: package-files.sh [--with-state] [package-name]
set -euo pipefail

WITH_STATE=false
NAME="intel-npu-tools"
for argument in "$@"; do
  case "$argument" in
    --with-state) WITH_STATE=true ;;
    -*) echo "Unknown option: $argument" >&2; exit 2 ;;
    *) NAME="$argument" ;;
  esac
done

if command -v rpm >/dev/null && rpm -q "$NAME" >/dev/null 2>&1; then
  MANAGER=rpm
  manifest=$(rpm -ql "$NAME")
elif command -v pacman >/dev/null && pacman -Qq "$NAME" >/dev/null 2>&1; then
  MANAGER=pacman
  manifest=$(pacman -Qlq "$NAME")
elif command -v dpkg-query >/dev/null && dpkg-query -s "$NAME" >/dev/null 2>&1; then
  MANAGER=dpkg
  manifest=$(dpkg-query -L "$NAME")
else
  echo "no package manager here has $NAME installed" >&2
  exit 1
fi

if [ -z "$manifest" ]; then
  echo "the package manager lists no files for $NAME" >&2
  exit 1
fi

if ! $WITH_STATE; then
  printf '%s\n' "$manifest"
  exit 0
fi

# Anyone other than this package who also claims the path. A directory with
# another owner is one that has to survive the removal.
another_owner_exists() {
  local owners
  case "$MANAGER" in
    rpm)    owners=$(rpm -qf --qf '%{NAME}\n' -- "$1" 2>/dev/null || true) ;;
    pacman) owners=$(pacman -Qoq -- "$1" 2>/dev/null || true) ;;
    dpkg)   owners=$(dpkg-query -S "$1" 2>/dev/null | sed 's/:[^:]*$//' | tr ',' '\n' | tr -d ' ' || true) ;;
  esac
  printf '%s\n' "$owners" | grep -qvx -e "$NAME" -e ''
}

while IFS= read -r path || [ -n "$path" ]; do
  [ -n "$path" ] || continue
  if [ -d "$path" ] && [ ! -L "$path" ]; then kind="directory"; else kind="file"; fi
  if another_owner_exists "$path"; then owner=shared; else owner=own; fi
  printf '%s\t%s\t%s\n' "$kind" "$owner" "$path"
done <<< "$manifest"
