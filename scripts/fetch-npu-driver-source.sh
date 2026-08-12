#!/bin/bash
# Fetch the Intel NPU driver source, and keep fetching until it is complete.
#
# Separate from the container build for one reason: a container build throws
# away everything it has when a step fails, so on an unreliable connection
# each attempt starts from nothing and the download never finishes. A
# directory on the host keeps what it has won, and this can be run again and
# again until it is done, resuming each time.
#
# Completeness is judged by looking at the directories rather than by asking
# git, because git has been wrong about it in three different ways here:
# `submodule update` exits 0 having fetched nothing; `submodule status`
# reports a submodule as present when its directory is empty; and a failed
# checkout leaves a directory holding nothing but a .git file, which looks
# populated to anything that merely counts entries.
#
# Usage: fetch-npu-driver-source.sh [destination] [tag]
set -euo pipefail

DESTINATION="${1:-$HOME/.cache/intel-npu-driver-src}"
TAG="${2:-v1.35.0}"
REPOSITORY="https://github.com/intel/linux-npu-driver.git"
ATTEMPTS="${FETCH_ATTEMPTS:-40}"

# Multiplexing fetches over one HTTP/2 connection is efficient until that
# connection is unreliable, at which point a single drop takes all of them.
export GIT_CONFIG_COUNT=4
export GIT_CONFIG_KEY_0=http.version      GIT_CONFIG_VALUE_0=HTTP/1.1
export GIT_CONFIG_KEY_1=http.postBuffer   GIT_CONFIG_VALUE_1=524288000
export GIT_CONFIG_KEY_2=http.lowSpeedLimit GIT_CONFIG_VALUE_2=1000
export GIT_CONFIG_KEY_3=http.lowSpeedTime  GIT_CONFIG_VALUE_3=60

# A submodule is only really here if its directory holds something other than
# the .git file that a failed checkout leaves behind.
incomplete_submodules() {
  git -C "$DESTINATION" submodule status --recursive 2>/dev/null \
    | awk '{print $2}' \
    | while read -r path; do
        [ -n "$path" ] || continue
        if [ -z "$(find "$DESTINATION/$path" -mindepth 1 -maxdepth 1 ! -name '.git' -print -quit 2>/dev/null)" ]; then
          echo "$path"
        fi
      done
}

if [ ! -d "$DESTINATION/.git" ]; then
  echo "Cloning $REPOSITORY at $TAG into $DESTINATION…"
  for attempt in $(seq 1 "$ATTEMPTS"); do
    rm -rf "$DESTINATION"
    if git clone --depth 1 --branch "$TAG" "$REPOSITORY" "$DESTINATION"; then
      break
    fi
    echo "  clone attempt $attempt failed"
    test "$attempt" -lt "$ATTEMPTS" || { echo "could not clone the driver" >&2; exit 1; }
    sleep 10
  done
fi

for attempt in $(seq 1 "$ATTEMPTS"); do
  git -C "$DESTINATION" submodule update --init --recursive --depth 1 --force || true
  missing=$(incomplete_submodules)
  if [ -z "$missing" ]; then
    echo
    echo "Complete. $DESTINATION holds the driver source and every submodule."
    echo "Build it with:"
    echo "  podman build -t intel-npu-driver:fedora \\"
    echo "    -v $DESTINATION:/src/npu-driver-cache:ro \\"
    echo "    -f packaging/docker/Dockerfile.fedora-driver ."
    exit 0
  fi
  echo "pass $attempt — still missing:"
  printf '%s\n' "$missing" | sed 's/^/  /'
  test "$attempt" -lt "$ATTEMPTS" || { echo "gave up with submodules missing" >&2; exit 1; }
  sleep 5
done
