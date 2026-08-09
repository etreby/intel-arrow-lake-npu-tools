#!/bin/bash
set -euo pipefail

PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DATA_DIR="${INTEL_NPU_TOOLS_HOME:-$HOME/.local/share/intel-arrow-lake-npu-tools}"
VENV="$DATA_DIR/venv"
WITH_DRIVER=false
WITH_MCP=true

for argument in "$@"; do
  case "$argument" in
    --with-driver) WITH_DRIVER=true ;;
    --without-mcp) WITH_MCP=false ;;
    -h|--help)
      echo "Usage: ./install.sh [--with-driver] [--without-mcp]"
      exit 0
      ;;
    *) echo "Unknown option: $argument" >&2; exit 2 ;;
  esac
done

if $WITH_DRIVER; then
  "$PROJECT_DIR/scripts/install-intel-npu-driver-ubuntu.sh"
fi

# Install only what is actually missing.
#
# Doing this unconditionally used to abort the whole install on machines whose
# apt configuration has an unrelated problem, because `apt-get update` exits
# non-zero for any failing source and this script runs under `set -e`. A stale
# cdrom:// entry left behind by an installation from USB media is enough, and
# has nothing to do with these packages. Checking first also means a machine
# that already has everything is never asked for a sudo password at all.
APT_PACKAGES=(python3-venv ffmpeg pipewire-bin kde-spectacle tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara wl-clipboard pciutils)
MISSING_PACKAGES=()
for package in "${APT_PACKAGES[@]}"; do
  dpkg -s "$package" >/dev/null 2>&1 || MISSING_PACKAGES+=("$package")
done
if ((${#MISSING_PACKAGES[@]})); then
  echo "Installing system packages: ${MISSING_PACKAGES[*]}"
  # A failing update is not fatal: the install below can still succeed from the
  # cached package lists, and it reports its own error if it cannot.
  sudo apt-get update || echo "Warning: apt-get update failed; continuing with the cached package lists."
  sudo apt-get install -y "${MISSING_PACKAGES[@]}"
else
  echo "All required system packages are already installed."
fi
mkdir -p "$DATA_DIR" "$HOME/.local/bin" "$HOME/.local/share/applications"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install "$PROJECT_DIR"
INTEL_NPU_TOOLS_HOME="$DATA_DIR" "$VENV/bin/python" "$PROJECT_DIR/scripts/download-models.py"

for command in intel-npu-info intel-npu-mcp intel-npu-ocr intel-npu-speech intel-npu-search; do
  target="$HOME/.local/bin/$command"
  if [[ -e "$target" && ! -L "$target" ]]; then
    mv "$target" "$target.before-intel-npu-tools-$(date +%Y%m%d-%H%M%S)"
  fi
  ln -sfn "$VENV/bin/$command" "$target"
done

sed -e "s|@HOME@|$HOME|g" "$PROJECT_DIR/packaging/intel-npu-speech.desktop.in" > "$HOME/.local/share/applications/intel-npu-speech.desktop"
sed -e "s|@HOME@|$HOME|g" "$PROJECT_DIR/packaging/intel-npu-ocr.desktop.in" > "$HOME/.local/share/applications/intel-npu-ocr.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

# Register the KDE global shortcuts.
#
# The X-KDE-Shortcuts line in each desktop file does not do this. KDE reads that
# field when it builds its service cache for system-installed applications; for
# a desktop file dropped into ~/.local/share/applications it records nothing, so
# the shortcut silently never exists. Earlier versions of this installer relied
# on it and the documented shortcuts simply did not work.
#
# kglobalaccel keys each entry by desktop file name, and the value is
# "active,default,friendly name".
SHORTCUTS_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/kglobalshortcutsrc"

# Report the entry already holding an accelerator, if any.
#
# Writing a binding that another component owns is worse than not writing one:
# kglobalaccel silently blanks the active field at the next login, leaving
# "_launch=,Meta+Alt+S,..." behind, and the shortcut appears to be installed
# while doing nothing. Meta+Alt+S is the concrete case — kaccess binds it to
# "Toggle Screen Reader On and Off" on a stock KDE, so the speech shortcut this
# project documented could never have worked on any KDE machine.
conflicting_entry() {
  local accelerator="$1" desktop="$2"
  [[ -r "$SHORTCUTS_FILE" ]] || return 0
  awk -v want="$accelerator" -v skip="[$desktop]" '
    /^\[/ { group = $0; next }
    index($0, want "," ) && group != skip {
      split($0, kv, "=")
      printf "%s (%s)", kv[1], substr(group, 2, length(group) - 2)
      exit
    }
  ' "$SHORTCUTS_FILE"
}

register_shortcut() {
  local desktop="$1" accelerator="$2" label="$3" taken
  if [[ -z "${KWRITECONFIG:-}" ]]; then
    return 0
  fi
  # Never overwrite a binding the user has already chosen for this application.
  if [[ -n "${KREADCONFIG:-}" ]] &&
     [[ -n "$("$KREADCONFIG" --file kglobalshortcutsrc --group "$desktop" --key _launch 2>/dev/null)" ]]; then
    echo "Keeping the existing shortcut for $label."
    return 0
  fi
  taken="$(conflicting_entry "$accelerator" "$desktop")"
  if [[ -n "$taken" ]]; then
    echo "Not registering $accelerator for $label: already used by $taken."
    echo "  Bind it yourself in System Settings if you want it on a different key."
    return 0
  fi
  "$KWRITECONFIG" --file kglobalshortcutsrc --group "$desktop" --key _k_friendly_name "$label"
  "$KWRITECONFIG" --file kglobalshortcutsrc --group "$desktop" --key _launch "$accelerator,$accelerator,$label"
  echo "Registered $accelerator for $label."
}

KWRITECONFIG="$(command -v kwriteconfig6 || command -v kwriteconfig5 || true)"
KREADCONFIG="$(command -v kreadconfig6 || command -v kreadconfig5 || true)"
if [[ -n "$KWRITECONFIG" ]]; then
  register_shortcut intel-npu-speech.desktop "Meta+F9" "Intel NPU Speech to Text"
  register_shortcut intel-npu-ocr.desktop "Meta+Alt+O" "Intel NPU Screenshot OCR"
  # kglobalaccel only reads this file at startup, so the keys start working
  # after the next login. Restarting it here would drop every other global
  # shortcut for a moment, which is not a reasonable thing for an installer to
  # do to a running desktop session.
  echo "Keyboard shortcuts take effect after your next login."
else
  echo "KDE configuration tools not found; skipping keyboard shortcut registration."
  echo "Launch the applications from the desktop menu, or bind them yourself in System Settings."
fi

if $WITH_MCP; then
  MCP_COMMAND="$HOME/.local/bin/intel-npu-mcp"
  if command -v codex >/dev/null && ! codex mcp get intel-npu-tools >/dev/null 2>&1; then
    codex mcp add intel-npu-tools -- "$MCP_COMMAND"
  fi
  if command -v claude >/dev/null && ! claude mcp get intel-npu-tools >/dev/null 2>&1; then
    claude mcp add --scope user --transport stdio intel-npu-tools -- "$MCP_COMMAND"
  fi
  if command -v hermes >/dev/null && ! hermes mcp list 2>/dev/null | grep -q intel-npu-tools; then
    printf 'Y\n' | hermes mcp add intel-npu-tools --command "$MCP_COMMAND" --connect-timeout 60
  fi
  if command -v gemini >/dev/null && ! gemini mcp list 2>/dev/null | grep -q intel-npu-tools; then
    gemini mcp add --scope user intel-npu-tools "$MCP_COMMAND"
  fi
  MCP_COMMAND="$MCP_COMMAND" python3 - <<'PY'
import json, os
from pathlib import Path

command = os.environ["MCP_COMMAND"]
configs = (
    (Path.home() / ".gemini/config/mcp_config.json", "agy"),
    (Path.home() / ".config/opencode/opencode.json", "opencode"),
)
for path, kind in configs:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        config = json.loads(path.read_text()) if path.exists() and path.stat().st_size else {}
    except json.JSONDecodeError:
        backup = path.with_name(path.name + ".before-intel-npu-tools")
        path.replace(backup)
        config = {}
    if kind == "agy":
        config.setdefault("mcpServers", {})["intel-npu-tools"] = {"command": command, "args": []}
    else:
        config.setdefault("$schema", "https://opencode.ai/config.json")
        config.setdefault("mcp", {})["intel-npu-tools"] = {
            "type": "local", "command": [command], "enabled": True, "timeout": 60000
        }
    path.write_text(json.dumps(config, indent=2) + "\n")
PY
  ANTIGRAVITY="$HOME/.gemini/antigravity/mcp_config.json"
  if [[ -d "$(dirname "$ANTIGRAVITY")" ]]; then
    MCP_COMMAND="$MCP_COMMAND" ANTIGRAVITY="$ANTIGRAVITY" python3 - <<'PY'
import json, os
from pathlib import Path
path = Path(os.environ["ANTIGRAVITY"])
try:
    config = json.loads(path.read_text()) if path.stat().st_size else {}
except (FileNotFoundError, json.JSONDecodeError):
    config = {}
config.setdefault("mcpServers", {})["intel-npu-tools"] = {"command": os.environ["MCP_COMMAND"], "args": []}
path.write_text(json.dumps(config, indent=2) + "\n")
PY
  fi
fi

echo
"$HOME/.local/bin/intel-npu-info" || true
echo "Installation complete. If NPU is not listed, log out/in and verify the driver setup in README.md."
