#!/bin/bash
# Build a signed apt repository from one or more .deb files.
#
# An apt repository is three things: the packages, an index describing them
# (Packages), and a signed summary of that index (Release plus InRelease).
# The signature is what apt actually trusts — without it a modern apt refuses
# the repository outright rather than warning — so this fails loudly if no key
# is available instead of quietly producing something nobody can install.
#
# The layout is the "flat repository" form, which needs no distribution or
# component directories and is the right shape for a project publishing a
# handful of architecture-independent packages to a static host.
#
# Usage: build-apt-repo.sh <output-dir> <deb> [deb...]
# Environment:
#   APT_GPG_KEY_ID   key to sign with; defaults to the only secret key present
set -euo pipefail

OUTPUT="${1:?usage: build-apt-repo.sh <output-dir> <deb> [deb...]}"
shift
if [[ $# -eq 0 ]]; then
  echo "No .deb files given." >&2
  exit 2
fi

for tool in gpg apt-ftparchive; do
  command -v "$tool" >/dev/null || {
    echo "$tool is required. Install gnupg and apt-utils." >&2
    exit 1
  }
done

KEY_ID="${APT_GPG_KEY_ID:-}"
if [[ -z "$KEY_ID" ]]; then
  KEY_ID="$(gpg --list-secret-keys --with-colons | awk -F: '/^sec:/ {print $5; exit}')"
fi
if [[ -z "$KEY_ID" ]]; then
  echo "No GPG secret key available to sign the repository." >&2
  echo "Generate one and either import it here or set APT_GPG_KEY_ID." >&2
  exit 1
fi

mkdir -p "$OUTPUT/pool"
for package in "$@"; do
  cp -f "$package" "$OUTPUT/pool/"
done

cd "$OUTPUT"
apt-ftparchive packages pool > Packages
gzip -9fk Packages

# Release carries the checksums of Packages; the signatures cover Release.
apt-ftparchive \
  -o "APT::FTPArchive::Release::Origin=intel-npu-tools" \
  -o "APT::FTPArchive::Release::Label=Intel NPU Tools" \
  -o "APT::FTPArchive::Release::Suite=stable" \
  -o "APT::FTPArchive::Release::Codename=stable" \
  -o "APT::FTPArchive::Release::Architectures=all" \
  -o "APT::FTPArchive::Release::Components=main" \
  -o "APT::FTPArchive::Release::Description=Local speech, OCR and semantic search on the Intel NPU" \
  release . > Release

# Both forms: InRelease is the inline-signed file modern apt prefers, and
# Release.gpg is the detached signature older clients look for.
rm -f InRelease Release.gpg
gpg --batch --yes --default-key "$KEY_ID" --clearsign -o InRelease Release
gpg --batch --yes --default-key "$KEY_ID" -abs -o Release.gpg Release

# The public key, in the dearmored form apt expects under
# /etc/apt/keyrings, so a user never has to run gpg themselves.
gpg --export "$KEY_ID" > intel-npu-tools-archive-keyring.gpg
gpg --export --armor "$KEY_ID" > intel-npu-tools.asc

echo "Signed apt repository written to $OUTPUT (key $KEY_ID)"
find "$OUTPUT" -maxdepth 1 -type f | sort | sed 's/^/  /'
