#!/usr/bin/env bash
# Run the Nav2 benchmark scenario suite against a REAL Nav2 + Gazebo stack and
# build dashboards from the resulting reports. Intended to run inside the image
# built from docker/Dockerfile.
#
# Usage:
#   bash docker/run_benchmark.sh [OUT_DIR]
#
# Environment:
#   CONFIG_LABEL   Leaderboard label for this configuration (default: $ROS_DISTRO).
#   RUN_LABEL      History label for this run (default: short git SHA or date).
#
# Headless note: GitHub-hosted runners have no GPU/display, so we force software
# GL and an offscreen Qt platform. The benchmark always uploads whatever reports
# and dashboards it produced, even if some scenarios fail, so the artifacts stay
# useful for debugging the real stack.
set -uo pipefail

OUT="${1:-out}"
mkdir -p "$OUT"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Headless rendering for Gazebo + Qt on a runner with no GPU/display.
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export OGRE_RTT_MODE="${OGRE_RTT_MODE:-Copy}"

# ROS setup scripts reference unbound variables (AMENT_TRACE_SETUP_FILES, ...),
# so relax nounset only while sourcing them.
set +u
# shellcheck disable=SC1090
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
set -u

CONFIG_LABEL="${CONFIG_LABEL:-${ROS_DISTRO:-nav2}}"
RUN_LABEL="${RUN_LABEL:-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y-%m-%d)}"

echo "== Preflight: doctor --check-gazebo =="
nav2_scenario_runner doctor --check-gazebo || echo "(doctor reported issues; continuing to capture logs)"

echo "== Running benchmark suite under real Nav2 (config: $CONFIG_LABEL) =="
# Execute the full Gazebo + Nav2 stack and the built-in Nav2 steps, collecting
# real metrics (travel_time, path_length_traveled, recovery_count, contacts).
# A scenario failure must not abort the dashboards, so capture the exit code and
# keep going as long as a report was produced.
RUN_RC=0
nav2_scenario_runner run examples/benchmark/scenarios/ \
  --mode gazebo-sim \
  --launch-scenario-stack \
  --wait-for-ros-graph \
  --wait-for-nav2 \
  --wait-for-navigation-data \
  --execute-nav2 \
  --collect-contacts \
  --report-dir "$OUT/reports" \
  --json-report "results.json" \
  --html-report "run.html" || RUN_RC=$?
# (No --github-summary: GITHUB_STEP_SUMMARY isn't visible inside the container;
#  the workflow's Summarize step writes the run summary on the host instead.)

if [ "$RUN_RC" -ne 0 ]; then
  echo "== Benchmark run exited with code $RUN_RC (some scenarios may have failed) =="
fi

if [ ! -f "$OUT/reports/results.json" ]; then
  echo "!! No results.json produced — the real stack did not run far enough to report."
  echo "   See $OUT/reports/ logs for the simulator/Nav2 launch output."
  exit "${RUN_RC:-1}"
fi

# The run report shares the benchmark config schema, so it feeds the dashboards
# directly — no conversion step.
cp "$OUT/reports/results.json" "$OUT/$CONFIG_LABEL.json"

echo "== Recording run into history =="
HISTORY="$OUT/history.jsonl"
nav2_scenario_runner record "$OUT/$CONFIG_LABEL.json" --history "$HISTORY" --label "$RUN_LABEL"

echo "== Building trend + interactive viewer =="
nav2_scenario_runner trend "$HISTORY" \
  --html-output "$OUT/trend.html" --json-output "$OUT/trend.json"

VIEWER_ENTRIES=()
EVAL_ENTRIES=()
for report in "$OUT"/*.json; do
  base="$(basename "$report" .json)"
  case "$base" in
    trend|evaluation) continue ;;
  esac
  VIEWER_ENTRIES+=(--entry "$base=$report")
  EVAL_ENTRIES+=(--entry "$base=$report")
done

nav2_scenario_runner viewer "${VIEWER_ENTRIES[@]}" \
  --title "Nav2 Benchmark Explorer" \
  --html-output "$OUT/viewer.html"

# Only rank when at least two configurations are present (each adds 2 args).
if [ "${#EVAL_ENTRIES[@]}" -ge 4 ]; then
  echo "== Building leaderboard (>=2 configs) =="
  nav2_scenario_runner evaluate "${EVAL_ENTRIES[@]}" \
    --html-output "$OUT/evaluation.html" --json-output "$OUT/evaluation.json"
fi

echo "== Done. Artifacts in $OUT =="
ls -1 "$OUT"

# Surface the real run's pass/fail to CI while still having built the artifacts.
exit "$RUN_RC"
