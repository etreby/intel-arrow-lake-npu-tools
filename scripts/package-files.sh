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
# Usage: package-files.sh [package-name]
set -euo pipefail

NAME="${1:-intel-npu-tools}"

if command -v rpm >/dev/null && rpm -q "$NAME" >/dev/null 2>&1; then
  manifest=$(rpm -ql "$NAME")
elif command -v pacman >/dev/null && pacman -Qq "$NAME" >/dev/null 2>&1; then
  manifest=$(pacman -Qlq "$NAME")
elif command -v dpkg-query >/dev/null && dpkg-query -s "$NAME" >/dev/null 2>&1; then
  manifest=$(dpkg-query -L "$NAME")
else
  echo "no package manager here has $NAME installed" >&2
  exit 1
fi

if [ -z "$manifest" ]; then
  echo "the package manager lists no files for $NAME" >&2
  exit 1
fi

printf '%s\n' "$manifest"
