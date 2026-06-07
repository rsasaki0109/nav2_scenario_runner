#!/usr/bin/env bash
# Build the public benchmark dashboards from the committed example fixtures.
#
# Output is written into docs/ so GitHub Pages can publish it. The fixtures in
# examples/benchmark/ are deterministic (no current-time stamping), so this
# regenerates byte-identical output and is safe to run in CI before deploy.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN=(python3 -m nav2_scenario_runner)
if ! python3 -c "import nav2_scenario_runner" >/dev/null 2>&1; then
  export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
fi

BENCH="examples/benchmark"
OUT="docs"

# Core configurations plus any merged community submissions. A merged
# submission PR (a run report under submissions/) appears on the live
# leaderboard on the next deploy. Sorted for deterministic output.
EVAL_ENTRIES=(
  --entry navfn="$BENCH/navfn.json"
  --entry smac="$BENCH/smac.json"
  --entry teb="$BENCH/teb.json"
)
for submission in $(find "$BENCH/submissions" -maxdepth 1 -name '*.json' 2>/dev/null | sort); do
  label="$(basename "$submission" .json)"
  EVAL_ENTRIES+=(--entry "$label=$submission")
  echo "Including community submission: $label"
done

echo "Building evaluation dashboard..."
"${RUN[@]}" evaluate \
  "${EVAL_ENTRIES[@]}" \
  --html-output "$OUT/evaluation.html" \
  --json-output "$OUT/evaluation.json"

echo "Building trend dashboard..."
"${RUN[@]}" trend "$BENCH/history.jsonl" \
  --html-output "$OUT/trend.html" \
  --json-output "$OUT/trend.json"

echo "Building replay dashboard..."
"${RUN[@]}" replay "$BENCH/smac.json" \
  --map "$BENCH/maps/warehouse.yaml" \
  --duration 5 \
  --html-output "$OUT/replay.html"

echo "Building interactive viewer..."
"${RUN[@]}" viewer \
  "${EVAL_ENTRIES[@]}" \
  --map "$BENCH/maps/warehouse.yaml" \
  --title "Nav2 Benchmark Explorer" \
  --html-output "$OUT/viewer.html"

echo "Building shields endpoint badges..."
for kind in winner score passrate regressions; do
  "${RUN[@]}" badge \
    --evaluation "$OUT/evaluation.json" \
    --trend "$OUT/trend.json" \
    --kind "$kind" \
    --output "$OUT/badge-$kind.json"
done

# --- Measured track: real Nav2 + Gazebo runs -------------------------------
# The dashboards above are deterministic *demo* fixtures (navfn/smac/teb) that
# render without a GPU/sim. The real, GPU-less CI run publishes its measured
# reports under examples/benchmark/real/ (the `Nav2 Real Benchmark` workflow
# auto-commits them weekly). When present, build a clearly-separated
# `measured-*` set so the live site shows real metrics alongside the demo.
REAL="$BENCH/real"
REAL_ENTRIES=()
for report in $(find "$REAL" -maxdepth 1 -name '*.json' 2>/dev/null | sort); do
  label="$(basename "$report" .json)"
  REAL_ENTRIES+=(--entry "$label=$report")
done

if [ "${#REAL_ENTRIES[@]}" -ge 2 ]; then
  echo "Building measured (real Nav2) dashboards..."
  MEAS_MAP=()
  [ -f "$BENCH/maps/tb3_sandbox.yaml" ] && MEAS_MAP=(--map "$BENCH/maps/tb3_sandbox.yaml")

  "${RUN[@]}" viewer \
    "${REAL_ENTRIES[@]}" \
    "${MEAS_MAP[@]}" \
    --title "Nav2 Benchmark Explorer (measured · real Nav2 + Gazebo)" \
    --html-output "$OUT/measured-viewer.html"

  "${RUN[@]}" trend "$REAL/history.jsonl" \
    --html-output "$OUT/measured-trend.html" \
    --json-output "$OUT/measured-trend.json"

  # Rank measured configs against each other only once there are at least two
  # (each contributes one --entry pair = 2 args).
  if [ "${#REAL_ENTRIES[@]}" -ge 4 ]; then
    "${RUN[@]}" evaluate \
      "${REAL_ENTRIES[@]}" \
      --html-output "$OUT/measured-evaluation.html" \
      --json-output "$OUT/measured-evaluation.json"
  fi
  echo "Measured dashboards written to $OUT/measured-{viewer,trend}.html"
else
  echo "No measured run reports under $REAL/ yet; skipping measured dashboards."
fi

echo "Dashboards written to $OUT/{evaluation,trend,replay,viewer}.html"
echo "Badges written to $OUT/badge-{winner,score,passrate,regressions}.json"
