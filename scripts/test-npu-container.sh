#!/bin/bash
# Build the headless image and check that the NPU is actually reachable inside
# it. This is the test CI cannot run: GitHub's runners have no NPU, so every
# job in validate.yml checks packaging and never touches the device. This has
# to run on a machine with the hardware.
#
# It answers one question — does OpenVINO inside a container see the NPU that
# the host sees — and answers it out loud, because the failure mode that
# matters is subtle: OpenVINO falls back to CPU without complaining, so a
# container with a broken passthrough looks like a working one that is merely
# slow.
#
# Usage: test-npu-container.sh [--runtime podman|docker] [--keep]
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="intel-npu-tools:test"
RUNTIME=""
KEEP=false

while [ $# -gt 0 ]; do
  case "$1" in
    --runtime) RUNTIME="${2:?--runtime needs a value}"; shift 2 ;;
    --keep) KEEP=true; shift ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$RUNTIME" ]; then
  for candidate in podman docker; do
    if command -v "$candidate" >/dev/null; then RUNTIME="$candidate"; break; fi
  done
fi
if [ -z "$RUNTIME" ] || ! command -v "$RUNTIME" >/dev/null; then
  cat >&2 <<'EOF'
No container runtime found. Install one first:

    sudo apt-get install -y podman     # no daemon, runs as you
    sudo apt-get install -y docker.io  # root daemon, adds a docker group

podman is the lighter choice here: it runs as your own user, so the render
group membership you already have is what grants the NPU, rather than a
daemon's.
EOF
  exit 1
fi

echo "== The host's side of this =="
if [ ! -e /dev/accel/accel0 ]; then
  echo "  /dev/accel/accel0 does not exist: this machine has no NPU, or intel_vpu is not loaded." >&2
  echo "  Nothing below would mean anything, so stopping here." >&2
  exit 1
fi
find /dev/accel/accel0 -maxdepth 0 -printf '  %M %u:%g %p\n'
if id -nG | tr ' ' '\n' | grep -qx render; then
  echo "  you are in the render group"
else
  echo "  WARNING: you are not in the render group; the device will not open." >&2
  echo "  sudo usermod -aG render \"$USER\", then log out and back in." >&2
fi
# The container's userspace has to get along with the host's kernel driver, so
# say what the host has. A mismatch here is the first thing to suspect.
if command -v dpkg-query >/dev/null; then
  dpkg-query -W -f'  host userspace: ${Package} ${Version}\n' \
    intel-level-zero-npu libze1 2>/dev/null || true
fi

echo
echo "== Building $IMAGE with $RUNTIME =="
"$RUNTIME" build -t "$IMAGE" -f "$PROJECT_DIR/packaging/docker/Dockerfile" "$PROJECT_DIR"

# Passing the device is not enough on its own: the node is root:render, so the
# process inside also has to hold that group. The two runtimes spell that
# differently, and rootless podman has to carry the group through rather than
# name it, because inside its user namespace the host's gid means nothing.
RUN_ARGUMENTS=(--rm --device /dev/accel/accel0)
case "$RUNTIME" in
  podman) RUN_ARGUMENTS+=(--group-add keep-groups) ;;
  docker)
    RENDER_GID="$(getent group render | cut -d: -f3)"
    if [ -z "$RENDER_GID" ]; then
      echo "no render group on this host" >&2; exit 1
    fi
    RUN_ARGUMENTS+=(--group-add "$RENDER_GID")
    ;;
esac

echo
echo "== Can the container open the device at all? =="
"$RUNTIME" run "${RUN_ARGUMENTS[@]}" "$IMAGE" \
  python3 -c "
import os, sys
path = '/dev/accel/accel0'
if not os.path.exists(path):
    sys.exit('  the device was not passed through: ' + path + ' is absent inside')
try:
    os.close(os.open(path, os.O_RDWR))
except OSError as error:
    sys.exit(f'  the device is present but will not open ({error.strerror}); this is the group, not the passthrough')
print('  opened', path, 'read-write')
"

echo
echo "== Does OpenVINO inside the container find the NPU? =="
# The check that matters. OpenVINO reports CPU whatever happens, so finding
# devices proves nothing on its own; NPU has to be among them, and a real
# compile has to succeed, because the device can enumerate and still fail to
# take work.
"$RUNTIME" run "${RUN_ARGUMENTS[@]}" "$IMAGE" \
  python3 -c "
import sys
import openvino as ov
core = ov.Core()
devices = core.available_devices
print('  devices:', ', '.join(devices) or '(none)')
if 'NPU' not in devices:
    sys.exit('  NPU is NOT visible inside the container.\n'
             '  The device opened, so this is the userspace half: the image\\'s\n'
             '  Intel driver is probably not compatible with the host kernel driver.\n'
             '  Try matching the versions printed above by setting NPU_DRIVER_TAG\n'
             '  and NPU_DRIVER_ASSET at build time.')
print('  NPU:', core.get_property('NPU', 'FULL_DEVICE_NAME'))

import numpy as np
import openvino.opset13 as ops   # openvino.runtime was removed in 2026
parameter = ops.parameter([1, 8], ov.Type.f32, name='input')
model = ov.Model([ops.relu(parameter)], [parameter], 'smoke')
compiled = core.compile_model(model, 'NPU')
# Compiling is not proof on its own — run it and check the arithmetic, so a
# device that accepts work and returns nonsense cannot pass.
result = compiled([np.array([[-1, 2, -3, 4, -5, 6, -7, 8]], dtype=np.float32)])[0]
expected = np.array([[0, 2, 0, 4, 0, 6, 0, 8]], dtype=np.float32)
if not np.array_equal(result, expected):
    sys.exit(f'  the NPU ran the model and got it wrong: {result} instead of {expected}')
print('  ran a model on the NPU and the arithmetic is right:', result.tolist()[0])
"

if ! $KEEP; then
  "$RUNTIME" rmi -f "$IMAGE" >/dev/null 2>&1 || true
fi

echo
echo "The NPU is reachable from inside a container on this machine."
