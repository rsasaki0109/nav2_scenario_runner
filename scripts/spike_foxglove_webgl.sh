#!/usr/bin/env bash
# Phase 0 spike: real Jazzy stack + foxglove_bridge + OSS Lichtblick + headless WebGL frame.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/reports/demo-capture}"
OUTPUT="${OUTPUT:-$LOG_DIR/spike-foxglove-frame.png}"
DOCKER_IMAGE="${DOCKER_IMAGE:-nav2-scenario-runner:jazzy-gazebo}"
LICHTBLICK_IMAGE="${LICHTBLICK_IMAGE:-ghcr.io/lichtblick-suite/lichtblick@sha256:ebaff0942173dc42c221ec0cc14d2bd7e6591e27c16cd11c8b2e557ce8da28d9}"
LAYOUT_FILE="${LAYOUT_FILE:-$ROOT_DIR/docs/assets/foxglove-nav2-layout.json}"
LICHTBLICK_PORT="${LICHTBLICK_PORT:-8080}"
BRIDGE_PORT="${BRIDGE_PORT:-8765}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-60}"
WAIT_BEFORE="${WAIT_BEFORE:-25}"
SOFTWARE_WEBGL="${SOFTWARE_WEBGL:-1}"

STACK_CONTAINER="${STACK_CONTAINER:-nav2-foxglove-spike-stack}"
VIEWER_CONTAINER="${VIEWER_CONTAINER:-nav2-foxglove-spike-viewer}"

mkdir -p "$LOG_DIR"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "error: missing command: $1" >&2
    exit 1
  }
}

require_command docker
require_command python3
require_command curl

if [[ ! -f "$LAYOUT_FILE" ]]; then
  echo "error: layout file not found: $LAYOUT_FILE" >&2
  exit 1
fi

cleanup() {
  docker rm -f "$STACK_CONTAINER" "$VIEWER_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "== Starting OSS Lichtblick on :$LICHTBLICK_PORT (layout: $LAYOUT_FILE) =="
docker rm -f "$VIEWER_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$VIEWER_CONTAINER" --network host \
  -v "$LAYOUT_FILE:/lichtblick/default-layout.json:ro" \
  "$LICHTBLICK_IMAGE" >/dev/null

for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$LICHTBLICK_PORT/" >/dev/null; then
    break
  fi
  sleep 1
done
curl -sf "http://127.0.0.1:$LICHTBLICK_PORT/" >/dev/null || {
  echo "error: Lichtblick did not become ready on port $LICHTBLICK_PORT" >&2
  exit 1
}

echo "== Starting real Nav2 stack + foxglove_bridge in $DOCKER_IMAGE =="
docker rm -f "$STACK_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$STACK_CONTAINER" --network host \
  --entrypoint /bin/bash \
  -e ROS_DOMAIN_ID="$ROS_DOMAIN_ID" \
  -e GZ_PARTITION=foxglove_spike \
  -e BRIDGE_PORT="$BRIDGE_PORT" \
  -e LOG_DIR=/reports/demo-capture/spike-stack \
  -v "$ROOT_DIR:/opt/nav2_scenario_runner" \
  -v "$LOG_DIR:/reports/demo-capture" \
  "$DOCKER_IMAGE" \
  /opt/nav2_scenario_runner/scripts/spike_foxglove_stack.sh \
  >"$LOG_DIR/spike-stack-docker.log" 2>&1

echo "== Waiting for foxglove_bridge on ws://127.0.0.1:$BRIDGE_PORT =="
python3 - <<PY
import socket
import sys
import time

deadline = time.time() + 240
while time.time() < deadline:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.connect(("127.0.0.1", int("$BRIDGE_PORT")))
    except OSError:
        time.sleep(2)
        continue
    finally:
        sock.close()
    print("foxglove_bridge port is open")
    sys.exit(0)

print("Timed out waiting for foxglove_bridge.", file=sys.stderr)
sys.exit(1)
PY

VIEWER_URL="http://127.0.0.1:${LICHTBLICK_PORT}/?ds=foxglove-websocket&ds.url=ws%3A%2F%2F127.0.0.1%3A${BRIDGE_PORT}"
SPIKE_ARGS=(
  python3 "$ROOT_DIR/scripts/spike_foxglove_webgl.py"
  --url "$VIEWER_URL"
  --output "$OUTPUT"
  --wait-before "$WAIT_BEFORE"
)
if [[ "$SOFTWARE_WEBGL" == "1" ]]; then
  SPIKE_ARGS+=(--software-webgl)
fi

echo "== Capturing one headless frame from $VIEWER_URL =="
"${SPIKE_ARGS[@]}" | tee "$LOG_DIR/spike-foxglove-webgl.log"

echo "== Phase 0/1 spike complete =="
echo "Frame: $OUTPUT"
echo "Layout: $LAYOUT_FILE"
echo "Stack logs: $LOG_DIR/spike-stack/ and $LOG_DIR/spike-stack-docker.log"
