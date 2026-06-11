#!/usr/bin/env bash
# Bring up the real Jazzy + gz sim Nav2 stack and foxglove_bridge.
# Intended to run inside nav2-scenario-runner:jazzy-gazebo with --network host.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$ROOT/reports/demo-capture/spike-stack}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-60}"
GZ_PARTITION="${GZ_PARTITION:-foxglove_spike}"
BRIDGE_PORT="${BRIDGE_PORT:-8765}"
SEND_GOAL="${SEND_GOAL:-1}"

mkdir -p "$LOG_DIR"

export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export OGRE_RTT_MODE="${OGRE_RTT_MODE:-Copy}"
export ROS_DOMAIN_ID GZ_PARTITION

set +u
# shellcheck disable=SC1091
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
set -u

TB3_SIM_SHARE="$(ros2 pkg prefix nav2_minimal_tb3_sim)/share/nav2_minimal_tb3_sim"
export GZ_SIM_RESOURCE_PATH="$TB3_SIM_SHARE/models:/opt/ros/${ROS_DISTRO:-jazzy}/share${GZ_SIM_RESOURCE_PATH:+:$GZ_SIM_RESOURCE_PATH}"

echo "== Expanding tb3_sandbox world xacro =="
xacro -o "$TB3_SIM_SHARE/worlds/tb3_sandbox.sdf" headless:=True "$TB3_SIM_SHARE/worlds/tb3_sandbox.sdf.xacro"

PIDS=()
cleanup() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    kill -INT "$pid" >/dev/null 2>&1 || true
  done
  sleep 2
  for pid in "${PIDS[@]:-}"; do
    kill -TERM "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

echo "== Starting gz sim tb3_sandbox (ROS_DOMAIN_ID=$ROS_DOMAIN_ID) =="
gz sim -r -s "$TB3_SIM_SHARE/worlds/tb3_sandbox.sdf" >"$LOG_DIR/gz_sim.log" 2>&1 &
PIDS+=("$!")

sleep 3

echo "== Starting Nav2 tb3_simulation_launch (use_simulator:=False) =="
ros2 launch nav2_bringup tb3_simulation_launch.py \
  use_simulator:=False \
  use_rviz:=False \
  headless:=True \
  use_sim_time:=True \
  x_pose:=-0.7 \
  y_pose:=0.5 \
  params_file:="$ROOT/examples/benchmark/config/nav2_params.yaml" \
  map:="/opt/ros/jazzy/share/nav2_bringup/maps/tb3_sandbox.yaml" \
  >"$LOG_DIR/nav2_bringup.log" 2>&1 &
PIDS+=("$!")

echo "== Waiting for core navigation topics =="
python3 - <<'PY'
import subprocess
import sys
import time

deadline = time.time() + 180
required = {
    "/clock",
    "/tf",
    "/scan",
    "/map",
    "/global_costmap/costmap",
    "/local_costmap/costmap",
}

while time.time() < deadline:
    result = subprocess.run(
        ["ros2", "topic", "list"],
        capture_output=True,
        text=True,
        check=False,
    )
    topics = set(result.stdout.splitlines())
    if required.issubset(topics):
        print("ready topics:", ", ".join(sorted(required)))
        sys.exit(0)
    time.sleep(2)

print("Timed out waiting for topics.", file=sys.stderr)
sys.exit(1)
PY

if ! ros2 pkg prefix foxglove_bridge >/dev/null 2>&1; then
  echo "== Installing ros-${ROS_DISTRO:-jazzy}-foxglove-bridge =="
  apt-get update >/dev/null
  apt-get install -y --no-install-recommends "ros-${ROS_DISTRO:-jazzy}-foxglove-bridge" >/dev/null
fi

echo "== Starting foxglove_bridge on port $BRIDGE_PORT =="
ros2 launch foxglove_bridge foxglove_bridge_launch.xml port:="$BRIDGE_PORT" \
  >"$LOG_DIR/foxglove_bridge.log" 2>&1 &
PIDS+=("$!")

sleep 3

if [[ "$SEND_GOAL" == "1" ]]; then
  SPIKE_SCENARIO="$LOG_DIR/spike_nav2_goal.yaml"
  cat > "$SPIKE_SCENARIO" <<'YAML'
apiVersion: nav2.scenario/v1alpha1
kind: Scenario

metadata:
  name: foxglove_spike_goal
  tags: [demo, spike]

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
      seconds: 15
  - send_goal:
      name: ahead
      pose:
        x: 0.7
        y: 0.5
        yaw: 0.0
  - expect_goal_reached:
      goal: ahead
      timeout: 120
YAML

  echo "== Sending benchmark straight-line goal (attach mode) =="
  PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m nav2_scenario_runner run "$SPIKE_SCENARIO" \
      --mode attach \
      --report-dir "$LOG_DIR/runner-report" \
      >"$LOG_DIR/nav2_scenario_runner.log" 2>&1 &
  PIDS+=("$!")
else
  echo "== SEND_GOAL=0; holding stack for external goal command =="
fi

echo "== Stack ready; holding until SIGTERM =="
while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      echo "error: process $pid exited early" >&2
      exit 1
    fi
  done
  sleep 5
done
