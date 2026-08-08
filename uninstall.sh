#!/bin/bash
set -euo pipefail

DATA_DIR="${INTEL_NPU_TOOLS_HOME:-$HOME/.local/share/intel-arrow-lake-npu-tools}"
echo "This removes the user applications, model cache, and MCP entries. System NPU drivers are preserved."
read -r -p "Continue? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || exit 0

for client in codex claude; do
  if command -v "$client" >/dev/null; then "$client" mcp remove intel-npu-tools >/dev/null 2>&1 || true; fi
done
if command -v hermes >/dev/null; then hermes mcp remove intel-npu-tools >/dev/null 2>&1 || true; fi
if command -v gemini >/dev/null; then gemini mcp remove --scope user intel-npu-tools >/dev/null 2>&1 || true; fi
rm -f "$HOME/.local/bin/intel-npu-info" "$HOME/.local/bin/intel-npu-mcp" "$HOME/.local/bin/intel-npu-ocr" "$HOME/.local/bin/intel-npu-speech"
rm -f "$HOME/.local/share/applications/intel-npu-speech.desktop" "$HOME/.local/share/applications/intel-npu-ocr.desktop"
rm -rf -- "$DATA_DIR"
echo "User installation removed."
