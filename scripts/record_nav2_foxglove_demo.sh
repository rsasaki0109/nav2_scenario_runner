#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/humble/setup.bash}"
GAZEBO_SETUP="${GAZEBO_SETUP:-/usr/share/gazebo/setup.sh}"
OUTPUT="${OUTPUT:-$ROOT_DIR/docs/assets/nav2-scenario-runner-demo.gif}"
DURATION="${DURATION:-6}"
FPS="${FPS:-4}"
WIDTH="${WIDTH:-1280}"
HEIGHT="${HEIGHT:-800}"
RECORD_WAIT_BEFORE="${RECORD_WAIT_BEFORE:-0.5}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/reports/demo-capture}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export ROS_DOMAIN_ID

PIDS=()

cleanup() {
  local pid

  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -INT "$pid" >/dev/null 2>&1 || true
    fi
  done
  sleep 2
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -TERM "$pid" >/dev/null 2>&1 || true
    fi
  done
  sleep 1
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -KILL "$pid" >/dev/null 2>&1 || true
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

require_ros_packages() {
  local missing=()
  local package

  for package in "$@"; do
    if ! ros2 pkg prefix "$package" >/dev/null 2>&1; then
      missing+=("$package")
    fi
  done

  if ((${#missing[@]} > 0)); then
    echo "error: missing ROS package(s): ${missing[*]}" >&2
    echo "Install the bundled demo dependencies with:" >&2
    echo "  sudo apt-get update" >&2
    echo "  sudo apt-get install -y gazebo ros-${ROS_DISTRO}-gazebo-ros-pkgs ros-${ROS_DISTRO}-foxglove-bridge ros-${ROS_DISTRO}-turtlebot3-gazebo ros-${ROS_DISTRO}-turtlebot3-description" >&2
    exit 1
  fi
}

prepend_env_path() {
  local name="$1"
  local path="$2"
  local current="${!name:-}"

  if [[ -d "$path" ]]; then
    export "$name=$path${current:+:$current}"
  fi
}

if [[ ! -f "$ROS_SETUP" ]]; then
  fail "ROS setup file not found: $ROS_SETUP"
fi

if [[ -f "$GAZEBO_SETUP" ]]; then
  set +u
  # shellcheck disable=SC1090
  source "$GAZEBO_SETUP"
  set -u
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
require_ros_packages \
  nav2_bringup \
  gazebo_ros \
  turtlebot3_gazebo \
  turtlebot3_description

GAZEBO_ROS_PREFIX="$(ros2 pkg prefix gazebo_ros)"
TURTLEBOT3_GAZEBO_PREFIX="$(ros2 pkg prefix turtlebot3_gazebo)"
prepend_env_path GAZEBO_PLUGIN_PATH "$GAZEBO_ROS_PREFIX/lib"
prepend_env_path GAZEBO_MODEL_PATH "$TURTLEBOT3_GAZEBO_PREFIX/share/turtlebot3_gazebo/models"

mkdir -p "$LOG_DIR" "$(dirname "$OUTPUT")"
echo "Using ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo "Using GAZEBO_PLUGIN_PATH=$GAZEBO_PLUGIN_PATH"
echo "Using GAZEBO_MODEL_PATH=$GAZEBO_MODEL_PATH"

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
  - wait:
      seconds: 3
  - set_initial_pose:
      x: -2.0
      y: -0.5
      yaw: 0.0
  - wait:
      seconds: 6
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

echo "Waiting for simulation topics..."
python3 - <<'PY'
import subprocess
import sys
import time

deadline = time.time() + 90
required_topics = {"/clock", "/tf", "/odom", "/scan"}

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
    missing = ", ".join(sorted(required_topics.difference(topics)))
    print(f"Timed out waiting for simulation topics: {missing}.", file=sys.stderr)
    sys.exit(1)
PY

echo "Running nav2_scenario_runner demo scenario..."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m nav2_scenario_runner run "$DEMO_SCENARIO" \
    --mode attach \
    --report-dir "$LOG_DIR/runner-report" \
    --trace-report trace.json \
    --html-report index.html \
    >"$LOG_DIR/nav2_scenario_runner.log" 2>&1

REPORT_URL="file://$LOG_DIR/runner-report/index.html"

echo "Recording generated HTML report with Playwright..."
python3 "$ROOT_DIR/scripts/record_browser_demo.py" \
  --url "$REPORT_URL" \
  --output "$OUTPUT" \
  --duration "$DURATION" \
  --fps "$FPS" \
  --width "$WIDTH" \
  --height "$HEIGHT" \
  --wait-before "$RECORD_WAIT_BEFORE" \
  --wait-for-selector ".badge.pass" \
  >"$LOG_DIR/record_browser_demo.log" 2>&1

echo "Wrote $OUTPUT"
echo "Logs: $LOG_DIR"
