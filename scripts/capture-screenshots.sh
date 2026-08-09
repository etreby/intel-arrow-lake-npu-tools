#!/bin/bash
# Capture the application screenshots used in the README.
#
# Runs each window on a virtual display rather than the real one, so
# regenerating the images never steals focus from whoever is running it and the
# result does not depend on their wallpaper, panel or window decorations. The
# images are therefore reproducible, which is the point: a screenshot that
# nobody can regenerate goes stale the first time the interface changes.
#
# Usage: capture-screenshots.sh [output-dir]
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$PROJECT_DIR/docs/images}"
DATA_DIR="${INTEL_NPU_TOOLS_HOME:-$HOME/.local/share/intel-arrow-lake-npu-tools}"
VENV="$DATA_DIR/venv"
# The panel asks for 940x680; matching the screen to it avoids a dead border.
WIDTH=940
HEIGHT=680

for tool in xvfb-run ffmpeg; do
  command -v "$tool" >/dev/null || { echo "$tool is required." >&2; exit 1; }
done
[[ -x "$VENV/bin/python" ]] || { echo "No environment at $VENV; run install.sh first." >&2; exit 1; }

mkdir -p "$OUTPUT"

# Capture one window: start it, let it settle and finish any first load, grab a
# single frame, then stop it.
capture() {
  local name="$1" tab="$2" settle="$3"
  echo "Capturing $name…"
  xvfb-run -a --server-args="-screen 0 ${WIDTH}x${HEIGHT}x24" bash -c "
    ${VENV}/bin/python - <<'PY' &
import tkinter as tk
from intel_npu_tools.panel import Panel
root = tk.Tk()
panel = Panel(root)
panel.tabs.select(${tab})
root.mainloop()
PY
    APP=\$!
    sleep ${settle}
    ffmpeg -loglevel error -y -f x11grab -video_size ${WIDTH}x${HEIGHT} -draw_mouse 0 -i \$DISPLAY -frames:v 1 '${OUTPUT}/${name}.png'
    kill \$APP 2>/dev/null || true
    wait \$APP 2>/dev/null || true
  "
}

# The NPU needs the render group, and the status tab queries the device.
if ! id -nG | tr ' ' '\n' | grep -qx render; then
  echo "Not in the render group; the status panel will show no NPU." >&2
fi

capture panel-voice 0 6
capture panel-search 2 6
capture panel-config 3 6
capture panel-status 4 9

echo
echo "Wrote:"
find "$OUTPUT" -name "*.png" | sort | sed 's/^/  /'
