#!/bin/bash
# Build a .deb for Debian, Ubuntu and Pop!_OS.
#
# Uses dpkg-deb against a staged tree rather than dpkg-buildpackage, because
# the package is architecture-independent data and scripts: there is nothing to
# compile, and this keeps the build to two tools that are present on any Debian
# derivative.
#
# Usage: build-deb.sh [output-directory]
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$PROJECT_DIR/dist}"
NAME="intel-npu-tools"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$PROJECT_DIR/pyproject.toml" | head -1)"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

"$PROJECT_DIR/scripts/stage-package.sh" "$BUILD" /usr

install -d "$BUILD/DEBIAN"
INSTALLED_SIZE="$(du -sk "$BUILD/usr" | cut -f1)"

cat > "$BUILD/DEBIAN/control" <<EOF
Package: $NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: Mohamed El-Etreby <40498+etreby@users.noreply.github.com>
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.10), python3-venv, ffmpeg, tesseract-ocr, tesseract-ocr-eng, pciutils
Recommends: tesseract-ocr-ara, wl-clipboard, pipewire-bin, librsvg2-bin
Suggests: kde-spectacle | gnome-screenshot | grim, xclip
Homepage: https://github.com/etreby/intel-npu-tools
Description: Local speech, OCR and semantic search on the Intel NPU
 Makes the integrated Intel AI Boost NPU in Arrow Lake processors useful on
 Linux. Provides private semantic search, local Whisper transcription,
 screenshot text extraction, a control panel, and an MCP server that AI agents
 can call to keep bulk text out of their context window.
 .
 The models and the OpenVINO runtime are not included: they are large and are
 redistributed under their own licences. Run intel-npu-tools-setup once as your
 own user to create the environment and download them.
EOF

cat > "$BUILD/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    if command -v update-desktop-database >/dev/null; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if command -v gtk-update-icon-cache >/dev/null; then
        gtk-update-icon-cache -qtf /usr/share/icons/hicolor || true
    fi
    cat <<'MESSAGE'

Intel NPU Tools is installed. Each user runs this once to create their
environment and download the models:

    intel-npu-tools-setup

MESSAGE
fi
exit 0
EOF

cat > "$BUILD/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if command -v update-desktop-database >/dev/null; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if command -v gtk-update-icon-cache >/dev/null; then
        gtk-update-icon-cache -qtf /usr/share/icons/hicolor || true
    fi
fi
# Each user's environment and models live in their home directory and are
# deliberately left alone: removing a package must not delete a user's data.
exit 0
EOF

chmod 755 "$BUILD/DEBIAN/postinst" "$BUILD/DEBIAN/postrm"

mkdir -p "$OUTPUT"
PACKAGE="$OUTPUT/${NAME}_${VERSION}_all.deb"
fakeroot dpkg-deb --build "$BUILD" "$PACKAGE" >/dev/null
echo "Built $PACKAGE"
dpkg-deb --info "$PACKAGE" | sed -n '1,4p;/Description/,$p'
