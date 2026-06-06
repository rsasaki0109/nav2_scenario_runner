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

# The benchmark scenarios drive the real tb3_sandbox world. The bare `gz sim`
# server the runner launches needs (a) the model:// include path on
# GZ_SIM_RESOURCE_PATH and (b) a plain SDF — the shipped world is a xacro — so
# expand it once here to the path the scenarios reference.
TB3_SIM_SHARE="$(ros2 pkg prefix nav2_minimal_tb3_sim)/share/nav2_minimal_tb3_sim"
export GZ_SIM_RESOURCE_PATH="$TB3_SIM_SHARE/models:/opt/ros/${ROS_DISTRO:-jazzy}/share${GZ_SIM_RESOURCE_PATH:+:$GZ_SIM_RESOURCE_PATH}"
echo "== Expanding tb3_sandbox world xacro =="
xacro -o "$TB3_SIM_SHARE/worlds/tb3_sandbox.sdf" headless:=True "$TB3_SIM_SHARE/worlds/tb3_sandbox.sdf.xacro"

echo "== Preflight: doctor --check-gazebo =="
nav2_scenario_runner doctor --check-gazebo || echo "(doctor reported issues; continuing to capture logs)"

echo "== Running benchmark suite under real Nav2 (config: $CONFIG_LABEL) =="
# Each scenario brings up its own full Gazebo + Nav2 stack and the built-in Nav2
# steps, collecting real metrics (travel_time, path_length_traveled,
# recovery_count). The tb3 robot has no contact sensors, so collision metrics are
# left unmeasured rather than failing the run.
#
# Scenarios run one-per-invocation under a unique ROS_DOMAIN_ID and GZ_PARTITION:
# a shared domain/partition would let a previous scenario's lingering Nav2 nodes
# (duplicate names) and Gazebo server block the next scenario's stack from
# activating. A scenario failure must not abort the others or the dashboards, so
# capture the exit code per scenario and keep going.
RUN_RC=0
DOMAIN=51
for scenario in "$ROOT"/examples/benchmark/scenarios/*.yaml; do
  name="$(basename "$scenario" .yaml)"
  echo "-- scenario: $name (ROS_DOMAIN_ID=$DOMAIN, GZ_PARTITION=bench_$name) --"
  ROS_DOMAIN_ID="$DOMAIN" GZ_PARTITION="bench_$name" \
  nav2_scenario_runner run "$scenario" \
    --mode gazebo-sim \
    --skip-gazebo-preflight \
    --launch-scenario-stack \
    --wait-for-ros-graph --ros-graph-timeout 90 \
    --wait-for-nav2 --nav2-timeout 180 \
    --wait-for-navigation-data --navigation-data-timeout 180 \
    --execute-nav2 \
    --sim-startup-timeout 25 \
    --report-dir "$OUT/reports/$name" \
    --json-report "results.json" \
    --html-report "run.html" || RUN_RC=$?
  DOMAIN=$((DOMAIN + 1))
done
# (No --github-summary: GITHUB_STEP_SUMMARY isn't visible inside the container;
#  the workflow's Summarize step writes the run summary on the host instead.)

# Merge the per-scenario reports into a single results.json the dashboards read.
echo "== Merging per-scenario reports =="
python3 - "$OUT/reports" <<'PY'
import json, sys, glob, os
base = sys.argv[1]
reports = sorted(glob.glob(os.path.join(base, "*", "results.json")))
scenarios, merged = [], None
for path in reports:
    d = json.load(open(path))
    merged = merged or d
    scenarios.extend(d.get("scenarios", []))
if merged is None:
    sys.exit("no per-scenario reports produced")
merged["scenarios"] = scenarios
merged["total"] = len(scenarios)
merged["passed"] = sum(1 for s in scenarios if s.get("status") in ("passed", "dry_run_passed"))
merged["failed"] = merged["total"] - merged["passed"]
json.dump(merged, open(os.path.join(base, "results.json"), "w"), indent=2)
print(f"merged {len(scenarios)} scenario(s): {merged['passed']} passed, {merged['failed']} failed")
PY

if [ "$RUN_RC" -ne 0 ]; then
  echo "== One or more scenarios failed (rc=$RUN_RC) =="
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
