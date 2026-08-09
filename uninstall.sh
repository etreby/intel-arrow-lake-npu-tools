#!/bin/bash
set -euo pipefail

DATA_DIR="${INTEL_NPU_TOOLS_HOME:-$HOME/.local/share/intel-arrow-lake-npu-tools}"

# INTEL_NPU_TOOLS_HOME reaches "rm -rf" below. Canonicalize before checking
# containment so that "..", or a symlinked component such as $HOME/data -> /etc,
# cannot pass a lexical prefix test and then delete outside the home directory.
CANONICAL_HOME=$(realpath -m -- "$HOME")
DATA_DIR=$(realpath -m -- "$DATA_DIR")
case "$DATA_DIR" in
  "$CANONICAL_HOME"/?*) ;;
  *)
    echo "Refusing to remove '$DATA_DIR': INTEL_NPU_TOOLS_HOME must resolve to a subdirectory of $CANONICAL_HOME." >&2
    exit 2
    ;;
esac

echo "This removes the user applications, model cache, and MCP entries. System NPU drivers are preserved."
read -r -p "Continue? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || exit 0

for client in codex claude; do
  if command -v "$client" >/dev/null; then "$client" mcp remove intel-npu-tools >/dev/null 2>&1 || true; fi
done
if command -v hermes >/dev/null; then hermes mcp remove intel-npu-tools >/dev/null 2>&1 || true; fi
if command -v gemini >/dev/null; then gemini mcp remove --scope user intel-npu-tools >/dev/null 2>&1 || true; fi
python3 - <<'PY'
import json
from pathlib import Path
for path, section in (
    (Path.home() / ".gemini/config/mcp_config.json", "mcpServers"),
    (Path.home() / ".config/opencode/opencode.json", "mcp"),
):
    try:
        config = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        continue
    servers = config.get(section)
    if isinstance(servers, dict):
        servers.pop("intel-npu-tools", None)
        path.write_text(json.dumps(config, indent=2) + "\n")
PY
rm -f "$HOME/.local/bin/intel-npu-info" "$HOME/.local/bin/intel-npu-mcp" "$HOME/.local/bin/intel-npu-ocr" "$HOME/.local/bin/intel-npu-speech" "$HOME/.local/bin/intel-npu-search"
rm -f "$HOME/.local/share/applications/intel-npu-speech.desktop" "$HOME/.local/share/applications/intel-npu-ocr.desktop"

# Release the global shortcuts, so Meta+Alt+S and Meta+Alt+O are free again
# rather than staying bound to applications that no longer exist.
#
# Only the binding this project wrote is removed. install.sh deliberately keeps
# a shortcut the user had already chosen for these applications, so deleting it
# here would make uninstalling destroy configuration that installing respected.
# A value that no longer matches what the installer wrote is the user's, not
# ours, and is left alone.
KWRITECONFIG="$(command -v kwriteconfig6 || command -v kwriteconfig5 || true)"
KREADCONFIG="$(command -v kreadconfig6 || command -v kreadconfig5 || true)"
release_shortcut() {
  local desktop="$1" installed="$2" current
  if [[ -z "$KREADCONFIG" ]]; then
    # Without a way to read the current value there is no way to tell our
    # binding from the user's, and leaving a dead shortcut behind is the less
    # damaging of the two mistakes.
    echo "Cannot read KDE configuration; leaving the shortcut for $desktop in place."
    return 0
  fi
  current="$("$KREADCONFIG" --file kglobalshortcutsrc --group "$desktop" --key _launch 2>/dev/null || true)"
  if [[ -z "$current" ]]; then
    return 0
  fi
  if [[ "$current" != "$installed" ]]; then
    echo "Keeping your customised shortcut for $desktop."
    return 0
  fi
  for key in _launch _k_friendly_name; do
    "$KWRITECONFIG" --file kglobalshortcutsrc --group "$desktop" --key "$key" --delete 2>/dev/null || true
  done
}
if [[ -n "$KWRITECONFIG" ]]; then
  release_shortcut intel-npu-speech.desktop "Meta+Alt+S,Meta+Alt+S,Intel NPU Speech to Text"
  release_shortcut intel-npu-ocr.desktop "Meta+Alt+O,Meta+Alt+O,Intel NPU Screenshot OCR"
fi
rm -rf -- "$DATA_DIR"
echo "User installation removed."
