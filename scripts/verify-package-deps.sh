#!/bin/bash
# Check that every dependency a built package names is a real package name in
# the distribution it is about to be installed on.
#
# Installing the package proves less than it looks. A weak dependency that does
# not exist is skipped in silence — dnf, zypper and pacman each warn at most
# and still exit 0 — and a hard one can resolve through some other package's
# Provides, which works today and breaks the day that provider is renamed. The
# weak names are also the ones most likely to be wrong, because they are the
# ones a maintainer copies from another distribution's package list.
#
# So every name is queried here, and a miss is a failure rather than a warning.
# The names are read out of the built package rather than out of the spec or
# the PKGBUILD, so what is checked is what was actually shipped.
#
# Usage: verify-package-deps.sh <package-file>
set -euo pipefail

PACKAGE="${1:?usage: verify-package-deps.sh <package-file>}"
test -f "$PACKAGE" || { echo "no such package: $PACKAGE" >&2; exit 1; }

# How to ask this distribution whether a dependency name can be satisfied at
# all. Each of these has to distinguish "nothing in the archive answers to this
# name" from "in the archive but not installed", which is why none of them is a
# plain install check.
#
# They match what a package provides, not only what it is called, because a
# virtual name is normal and correct in an RPM dependency: openSUSE has no
# package called ffmpeg or python3, and both are the right thing to require
# there — ffmpeg-7 and python311 answer to them, and naming the versioned
# package instead would break at the next major version. What has to be caught
# is a name that nothing answers to in any form.
QUERY=
if command -v dnf >/dev/null; then
  # dnf4 and dnf5 disagree about option spelling and about "--", and every one
  # of those disagreements produces empty output rather than an error, which is
  # indistinguishable from a package that is not there. The working form is
  # therefore chosen by trying each one below against a package that certainly
  # exists, instead of being assumed.
  package_exists() {
    case "$QUERY" in
      repoquery) test -n "$(dnf repoquery --quiet --whatprovides "$1" 2>/dev/null)" ;;
      provides)  dnf provides "$1" >/dev/null 2>&1 ;;
    esac
  }
  suggest_similar() { dnf repoquery --quiet "$1*" 2>/dev/null; }
  QUERY_FORMS="repoquery provides"
elif command -v zypper >/dev/null; then
  # search exits 104 when nothing matches.
  package_exists() { zypper --non-interactive --quiet search --provides --match-exact --type package -- "$1" >/dev/null 2>&1; }
  suggest_similar() { zypper --non-interactive --quiet search --type package -- "$1" 2>/dev/null | awk -F'|' 'NF>2 && $2 !~ /Name/ {gsub(/ /,"",$2); print $2}'; }
  QUERY_FORMS="zypper"
elif command -v pacman >/dev/null; then
  package_exists() { pacman -Si -- "$1" >/dev/null 2>&1; }
  suggest_similar() { pacman -Ssq -- "^$1" 2>/dev/null; }
  QUERY_FORMS="pacman"
else
  echo "no supported package manager found" >&2
  exit 1
fi

# A probe that answers "missing" to everything would condemn a set of perfectly
# good names, and it fails exactly that way when an option is rejected or the
# repository metadata was never fetched. So it is tried against a package that
# is certainly present, and nothing it says is trusted until it passes.
for QUERY in $QUERY_FORMS; do
  package_exists bash && break
  QUERY=
done
if [ -z "$QUERY" ]; then
  echo "The package query does not work here: it cannot even find bash." >&2
  echo "Fix the query before trusting anything it says about these names." >&2
  exit 1
fi

# Strip version constraints and drop the entries that are not names anything
# could satisfy: rpm records its own rpmlib features, the interpreter paths a
# script needs, and a capability naming this very package. Capabilities like
# python3dist(foo) are kept, because something in the archive does provide
# them; only a rich dependency, which starts with its own bracket, is dropped
# for being an expression rather than a name.
real_names() {
  sed -e 's/[<>=].*//' -e 's/[[:space:]]*$//' \
    | awk 'NF && $1 !~ /^rpmlib\(/ && $1 !~ /^config\(/ && $1 !~ /^\// && $1 !~ /^\(/ {print $1}' \
    | sort -u
}

case "$PACKAGE" in
  *.rpm)
    # Queried one at a time rather than as a group: a group's exit status is
    # its last command's, so a failing --recommends would be masked by a
    # succeeding --suggests and every recommended name would go unchecked.
    requires=$(rpm -qp --requires "$PACKAGE" 2>/dev/null)
    recommends=$(rpm -qp --recommends "$PACKAGE" 2>/dev/null)
    suggests=$(rpm -qp --suggests "$PACKAGE" 2>/dev/null)
    hard=$(printf '%s\n' "$requires" | real_names)
    weak=$(printf '%s\n%s\n' "$recommends" "$suggests" | real_names)
    ;;
  *.pkg.tar.*)
    metadata=$(bsdtar -xOf "$PACKAGE" .PKGINFO)
    hard=$(printf '%s\n' "$metadata" | sed -n 's/^depend = //p' | real_names)
    # "optdepend = name: why you might want it"
    weak=$(printf '%s\n' "$metadata" | sed -n 's/^optdepend = //p' | cut -d: -f1 | real_names)
    ;;
  *)
    echo "unsupported package type: $PACKAGE" >&2
    exit 1
    ;;
esac

missing=()

check_group() {
  local label="$1" names="$2" name prefix similar
  [ -n "$names" ] || return 0
  echo "$label:"
  while read -r name; do
    if package_exists "$name"; then
      echo "  ok       $name"
      continue
    fi
    echo "  MISSING  $name"
    missing+=("$name")
    # The name a distribution uses is usually a variation on the one that was
    # guessed, so offer what it does have under that prefix. Two components is
    # the useful amount: tesseract-ocr-traineddata-arabic searched whole finds
    # nothing, but tesseract-ocr finds the family it belongs to.
    prefix=$(printf '%s' "$name" | cut -d- -f1-2)
    # Never let the suggestion machinery decide the outcome: zypper exits 104
    # when a search finds nothing, and awk rather than head does the trimming
    # because head closing the pipe early is itself a pipeline failure.
    similar=$( { suggest_similar "$prefix" || true; } | grep -vx "$name" | sort -u | awk 'NR<=12' || true)
    if [ -n "$similar" ]; then
      echo "$similar" | awk '{print "             candidate: " $0}'
    fi
  done <<< "$names"
}

check_group "Required" "$hard"
check_group "Recommended and suggested" "$weak"

if [ ${#missing[@]} -gt 0 ]; then
  echo >&2
  echo "${#missing[@]} dependency name(s) mean nothing here: ${missing[*]}" >&2
  echo "Nothing in this distribution's archive answers to them under any name." >&2
  echo "A weak one is dropped in silence at install time, so the feature it was" >&2
  echo "meant to enable would simply never work." >&2
  exit 1
fi

echo "Every dependency name resolves to a package of that name."
