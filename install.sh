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

sudo apt-get update
sudo apt-get install -y python3-venv ffmpeg pipewire-bin kde-spectacle tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara wl-clipboard pciutils
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
