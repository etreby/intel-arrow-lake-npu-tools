#!/bin/bash
set -euo pipefail

DRIVER_VERSION="1.32.1"
DRIVER_BUILD="20260422-24767473183"
ARCHIVE="linux-npu-driver-v${DRIVER_VERSION}.${DRIVER_BUILD}-ubuntu2404.tar.gz"
RELEASE="https://github.com/intel/linux-npu-driver/releases/download/v${DRIVER_VERSION}/${ARCHIVE}"
LEVEL_ZERO="https://snapshot.ppa.launchpadcontent.net/kobuk-team/intel-graphics/ubuntu/20260324T100000Z/pool/main/l/level-zero-loader/libze1_1.27.0-1~24.04~ppa2_amd64.deb"
# The PPA snapshot is not GPG-signed for this download path, so the archive is
# pinned by digest instead.
LEVEL_ZERO_SHA256="526808b420a2bd7b4ee24a99e9a71a35de820abe3e33c22dcb51c490da4439e0"
KEY_FINGERPRINT="EA267657A608300C296B8F8AD52C9665A4077678"

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" && "${ID_LIKE:-}" != *ubuntu* ]]; then
  echo "This installer currently supports Ubuntu-compatible distributions only." >&2
  exit 1
fi
if [[ "${VERSION_ID:-}" != "24.04" ]]; then
  echo "Intel's bundled package used here targets Ubuntu 24.04; found ${VERSION_ID:-unknown}." >&2
  exit 1
fi
if ! lspci -nn | grep -qi '8086:ad1d'; then
  echo "Arrow Lake NPU PCI ID 8086:ad1d was not found." >&2
  exit 1
fi

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
curl -fL --retry 5 "$RELEASE" -o "$work/$ARCHIVE"
tar -xzf "$work/$ARCHIVE" -C "$work"
curl -fL "https://keys.openpgp.org/vks/v1/by-fingerprint/$KEY_FINGERPRINT" -o "$work/intel-key.asc"
mkdir -m 700 "$work/gnupg"
GNUPGHOME="$work/gnupg" gpg --batch --import "$work/intel-key.asc"
# Verify every package that will be installed, rather than every signature that
# happens to be present: a substituted .deb shipped without its .asc must not
# slip through because its siblings are correctly signed.
packages=()
for component in intel-driver-compiler-npu intel-fw-npu intel-level-zero-npu; do
  found=0
  for package in "$work/${component}"_*.deb; do
    [[ -f "$package" ]] || continue
    if [[ ! -f "$package.asc" ]]; then
      echo "No signature for $(basename "$package") in $ARCHIVE; refusing to install." >&2
      exit 1
    fi
    GNUPGHOME="$work/gnupg" gpg --batch --verify "$package.asc" "$package"
    packages+=("$package")
    found=$((found + 1))
  done
  if (( found == 0 )); then
    echo "Expected package $component was not found in $ARCHIVE; refusing to install." >&2
    exit 1
  fi
done
curl -fL --retry 5 "$LEVEL_ZERO" -o "$work/libze1.deb"
echo "$LEVEL_ZERO_SHA256  $work/libze1.deb" | sha256sum --check --status || {
  echo "Level Zero loader digest mismatch; refusing to install $LEVEL_ZERO" >&2
  exit 1
}

sudo apt-get update
sudo apt-get install -y "${packages[@]}" "$work/libze1.deb"
sudo usermod -aG render "$USER"

echo "Intel NPU user-mode driver installed. Log out and back in before using it."
