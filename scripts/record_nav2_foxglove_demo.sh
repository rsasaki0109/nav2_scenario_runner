#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/humble/setup.bash}"
FOXGLOVE_PORT="${FOXGLOVE_PORT:-8765}"
OUTPUT="${OUTPUT:-$ROOT_DIR/docs/assets/nav2-scenario-runner-demo.gif}"
DURATION="${DURATION:-18}"
FPS="${FPS:-8}"
WIDTH="${WIDTH:-1440}"
HEIGHT="${HEIGHT:-900}"
RECORD_WAIT_BEFORE="${RECORD_WAIT_BEFORE:-4}"
SCENARIO_DELAY="${SCENARIO_DELAY:-6}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/reports/demo-capture}"

PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -INT "$pid" >/dev/null 2>&1 || true
    fi
  done
  wait >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

fail() {
  echo "error: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

require_ros_package() {
  ros2 pkg prefix "$1" >/dev/null 2>&1 || fail "missing ROS package: $1"
}

if [[ ! -f "$ROS_SETUP" ]]; then
  fail "ROS setup file not found: $ROS_SETUP"
fi

# ROS setup scripts may read optional unset variables, so keep nounset off while sourcing.
set +u
# shellcheck disable=SC1090
source "$ROS_SETUP"
set -u

require_command python3
require_command ffmpeg
require_command ros2
require_command gzserver
require_ros_package nav2_bringup
require_ros_package gazebo_ros
require_ros_package foxglove_bridge

mkdir -p "$LOG_DIR" "$(dirname "$OUTPUT")"

DEMO_SCENARIO="$LOG_DIR/nav2_demo_smoke.yaml"
cat > "$DEMO_SCENARIO" <<'YAML'
apiVersion: nav2.scenario/v1alpha1
kind: Scenario

metadata:
  name: readme_demo_straight_goal
  tags: [demo, smoke, navigation]

runtime:
  timeout: 90
  use_sim_time: true

steps:
  - wait_for_nav2_active:
      timeout: 60
  - set_initial_pose:
      x: -2.0
      y: -0.5
      yaw: 0.0
  - send_goal:
      name: main_goal
      pose:
        x: 0.5
        y: -0.5
        yaw: 0.0
  - expect_goal_reached:
      goal: main_goal
      timeout: 60

assertions:
  - goal_reached: {}
  - travel_time:
      max: 60.0
  - path_length:
      max: 6.0
YAML

echo "Starting Nav2 TurtleBot3 simulation..."
ros2 launch nav2_bringup tb3_simulation_launch.py \
  use_rviz:=False \
  headless:=True \
  >"$LOG_DIR/nav2_tb3_simulation.log" 2>&1 &
PIDS+=("$!")

echo "Waiting for /clock and Nav2 action server..."
python3 - <<'PY'
import subprocess
import sys
import time

deadline = time.time() + 90
required_topics = {"/clock", "/tf"}

while time.time() < deadline:
    topics = subprocess.run(
        ["ros2", "topic", "list"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    if required_topics.issubset(set(topics)):
        break
    time.sleep(1)
else:
    print("Timed out waiting for /clock and /tf.", file=sys.stderr)
    sys.exit(1)
PY

echo "Starting Foxglove Bridge on port $FOXGLOVE_PORT..."
ros2 launch foxglove_bridge foxglove_bridge_launch.xml port:="$FOXGLOVE_PORT" \
  >"$LOG_DIR/foxglove_bridge.log" 2>&1 &
PIDS+=("$!")

python3 - "$FOXGLOVE_PORT" <<'PY'
import socket
import sys
import time

port = int(sys.argv[1])
deadline = time.time() + 30
while time.time() < deadline:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            sys.exit(0)
    except OSError:
        time.sleep(0.5)
print(f"Timed out waiting for Foxglove Bridge on port {port}.", file=sys.stderr)
sys.exit(1)
PY

FOXGLOVE_URL="https://app.foxglove.dev/~/view?ds=foxglove-websocket&ds.url=ws%3A%2F%2Flocalhost%3A${FOXGLOVE_PORT}"

echo "Starting Playwright recording..."
python3 "$ROOT_DIR/scripts/record_browser_demo.py" \
  --url "$FOXGLOVE_URL" \
  --output "$OUTPUT" \
  --duration "$DURATION" \
  --fps "$FPS" \
  --width "$WIDTH" \
  --height "$HEIGHT" \
  --wait-before "$RECORD_WAIT_BEFORE" \
  >"$LOG_DIR/record_browser_demo.log" 2>&1 &
RECORDER_PID="$!"

sleep "$SCENARIO_DELAY"

echo "Running nav2_scenario_runner demo scenario..."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m nav2_scenario_runner run "$DEMO_SCENARIO" \
    --mode attach \
    --report-dir "$LOG_DIR/runner-report" \
    --trace-report trace.json \
    --html-report index.html \
    >"$LOG_DIR/nav2_scenario_runner.log" 2>&1

wait "$RECORDER_PID"
echo "Wrote $OUTPUT"
echo "Logs: $LOG_DIR"
