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
set -euo pipefail

OUT="${1:-out}"
mkdir -p "$OUT"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1090
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"

CONFIG_LABEL="${CONFIG_LABEL:-${ROS_DISTRO:-nav2}}"
RUN_LABEL="${RUN_LABEL:-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y-%m-%d)}"

echo "== Preflight: doctor --check-gazebo =="
nav2_scenario_runner doctor --check-gazebo

echo "== Running benchmark suite under real Nav2 (config: $CONFIG_LABEL) =="
# Execute the full Gazebo + Nav2 stack and the built-in Nav2 steps, collecting
# real metrics (travel_time, path_length_traveled, recovery_count, contacts).
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
  --html-report "run.html" \
  --github-summary

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

# Only rank when at least two configurations are present.
if [ "${#EVAL_ENTRIES[@]}" -ge 4 ]; then
  echo "== Building leaderboard (>=2 configs) =="
  nav2_scenario_runner evaluate "${EVAL_ENTRIES[@]}" \
    --html-output "$OUT/evaluation.html" --json-output "$OUT/evaluation.json"
fi

echo "== Done. Artifacts in $OUT =="
ls -1 "$OUT"
