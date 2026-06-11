#!/usr/bin/env bash
# Capture a real Nav2 + Gazebo Sim run in the OSS Lichtblick web viewer.
#
# The heavy ROS stack runs inside the repository's Jazzy/Gazebo Docker image.
# The browser recorder runs on the host so Playwright and ffmpeg produce the GIF
# directly under docs/assets/.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/reports/demo-capture}"
OUTPUT="${OUTPUT:-$ROOT_DIR/docs/assets/nav2-foxglove-demo.gif}"
LAYOUT_FILE="${LAYOUT_FILE:-$ROOT_DIR/docs/assets/foxglove-nav2-layout.json}"

DOCKER_IMAGE="${DOCKER_IMAGE:-nav2-scenario-runner:jazzy-gazebo}"
LICHTBLICK_IMAGE="${LICHTBLICK_IMAGE:-ghcr.io/lichtblick-suite/lichtblick@sha256:ebaff0942173dc42c221ec0cc14d2bd7e6591e27c16cd11c8b2e557ce8da28d9}"
STACK_CONTAINER="${STACK_CONTAINER:-nav2-foxglove-demo-stack}"
VIEWER_CONTAINER="${VIEWER_CONTAINER:-nav2-foxglove-demo-viewer}"

LICHTBLICK_PORT="${LICHTBLICK_PORT:-8080}"
BRIDGE_PORT="${BRIDGE_PORT:-8765}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-61}"
GZ_PARTITION="${GZ_PARTITION:-foxglove_demo}"

DURATION="${DURATION:-10}"
FPS="${FPS:-4}"
WIDTH="${WIDTH:-1280}"
HEIGHT="${HEIGHT:-800}"
VIEWER_WAIT_BEFORE="${VIEWER_WAIT_BEFORE:-6}"
RECORD_WAIT_AFTER_GOAL_START="${RECORD_WAIT_AFTER_GOAL_START:-1}"
GOAL_SETTLE_SECONDS="${GOAL_SETTLE_SECONDS:-4}"
GOAL_NAME="${GOAL_NAME:-turn_around}"
GOAL_X="${GOAL_X:-0.5}"
GOAL_Y="${GOAL_Y:-0.5}"
GOAL_YAW="${GOAL_YAW:-3.14159}"
SOFTWARE_WEBGL="${SOFTWARE_WEBGL:-1}"

PIDS=()

cleanup() {
  local pid

  for pid in "${PIDS[@]:-}"; do
    kill "$pid" >/dev/null 2>&1 || true
  done
  docker rm -f "$STACK_CONTAINER" "$VIEWER_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

fail() {
  echo "error: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

wait_for_http() {
  local url="$1"
  local timeout="$2"
  local deadline=$((SECONDS + timeout))

  while ((SECONDS < deadline)); do
    if curl -sf "$url" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_port() {
  local host="$1"
  local port="$2"
  local timeout="$3"

  python3 - "$host" "$port" "$timeout" <<'PY'
import socket
import sys
import time

host, port, timeout = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
deadline = time.time() + timeout
while time.time() < deadline:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        try:
            sock.connect((host, port))
        except OSError:
            time.sleep(1)
            continue
        sys.exit(0)
sys.exit(1)
PY
}

require_command docker
require_command python3
require_command curl
require_command ffmpeg

[[ -f "$LAYOUT_FILE" ]] || fail "layout file not found: $LAYOUT_FILE"

mkdir -p "$LOG_DIR" "$(dirname "$OUTPUT")"

DEMO_SCENARIO="$LOG_DIR/foxglove_demo_goal.yaml"
cat >"$DEMO_SCENARIO" <<YAML
apiVersion: nav2.scenario/v1alpha1
kind: Scenario

metadata:
  name: foxglove_demo_goal
  tags: [demo, foxglove, navigation]

runtime:
  timeout: 180
  use_sim_time: true

steps:
  - wait_for_nav2_active:
      timeout: 90
  - set_initial_pose:
      x: -0.7
      y: 0.5
      yaw: 0.0
  - wait:
      seconds: ${GOAL_SETTLE_SECONDS}
  - send_goal:
      name: ${GOAL_NAME}
      pose:
        x: ${GOAL_X}
        y: ${GOAL_Y}
        yaw: ${GOAL_YAW}
  - expect_goal_reached:
      goal: ${GOAL_NAME}
      timeout: 120

assertions:
  - goal_reached: {}
  - travel_time:
      max: 60.0
  - path_length:
      max: 4.0
YAML

echo "== Starting OSS Lichtblick on http://127.0.0.1:$LICHTBLICK_PORT =="
docker rm -f "$VIEWER_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$VIEWER_CONTAINER" --network host \
  -v "$LAYOUT_FILE:/lichtblick/default-layout.json:ro" \
  "$LICHTBLICK_IMAGE" \
  >"$LOG_DIR/lichtblick.container" 2>"$LOG_DIR/lichtblick-docker.log"

wait_for_http "http://127.0.0.1:$LICHTBLICK_PORT/" 60 || {
  docker logs "$VIEWER_CONTAINER" >"$LOG_DIR/lichtblick.log" 2>&1 || true
  fail "Lichtblick did not become ready on port $LICHTBLICK_PORT"
}

echo "== Starting Jazzy + gz sim Nav2 stack in $DOCKER_IMAGE =="
docker rm -f "$STACK_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$STACK_CONTAINER" --network host \
  --entrypoint /bin/bash \
  -e ROS_DOMAIN_ID="$ROS_DOMAIN_ID" \
  -e GZ_PARTITION="$GZ_PARTITION" \
  -e BRIDGE_PORT="$BRIDGE_PORT" \
  -e LOG_DIR=/reports/demo-capture/stack \
  -e SEND_GOAL=0 \
  -v "$ROOT_DIR:/opt/nav2_scenario_runner" \
  -v "$LOG_DIR:/reports/demo-capture" \
  "$DOCKER_IMAGE" \
  /opt/nav2_scenario_runner/scripts/spike_foxglove_stack.sh \
  >"$LOG_DIR/stack.container" 2>"$LOG_DIR/stack-docker.log"

echo "== Waiting for foxglove_bridge on ws://127.0.0.1:$BRIDGE_PORT =="
wait_for_port 127.0.0.1 "$BRIDGE_PORT" 240 || {
  docker logs "$STACK_CONTAINER" >"$LOG_DIR/stack.log" 2>&1 || true
  fail "foxglove_bridge did not become ready on port $BRIDGE_PORT"
}

VIEWER_URL="http://127.0.0.1:${LICHTBLICK_PORT}/?ds=foxglove-websocket&ds.url=ws%3A%2F%2F127.0.0.1%3A${BRIDGE_PORT}"
echo "== Starting timed Nav2 goal =="
docker exec \
  -e ROS_DOMAIN_ID="$ROS_DOMAIN_ID" \
  -e GZ_PARTITION="$GZ_PARTITION" \
  "$STACK_CONTAINER" \
  /bin/bash -lc "set -eo pipefail; set +u; source /opt/ros/\${ROS_DISTRO:-jazzy}/setup.bash; set -u; PYTHONPATH=/opt/nav2_scenario_runner/src\${PYTHONPATH:+:\$PYTHONPATH} python3 -m nav2_scenario_runner run /reports/demo-capture/foxglove_demo_goal.yaml --mode attach --report-dir /reports/demo-capture/runner-report --trace-report trace.json --html-report index.html" \
  >"$LOG_DIR/nav2_scenario_runner.log" 2>&1 &
PIDS+=("$!")
RUNNER_PID="$!"

sleep "$RECORD_WAIT_AFTER_GOAL_START"

echo "== Recording Lichtblick scene to $OUTPUT =="
RECORD_ARGS=(
  python3 "$ROOT_DIR/scripts/record_browser_demo.py"
  --url "$VIEWER_URL"
  --output "$OUTPUT"
  --duration "$DURATION"
  --fps "$FPS"
  --width "$WIDTH"
  --height "$HEIGHT"
  --crop-left 240
  --wait-before "$VIEWER_WAIT_BEFORE"
  --wait-for-selector "canvas"
  --click "228,56"
  --browser chromium
)
if [[ "$SOFTWARE_WEBGL" == "1" ]]; then
  RECORD_ARGS+=(--software-webgl)
fi
"${RECORD_ARGS[@]}" >"$LOG_DIR/record_browser_demo.log" 2>&1

echo "== Waiting for Nav2 scenario to finish =="
if ! wait "$RUNNER_PID"; then
  fail "Nav2 scenario failed; see $LOG_DIR/nav2_scenario_runner.log"
fi

echo "Wrote $OUTPUT"
echo "Logs: $LOG_DIR"
