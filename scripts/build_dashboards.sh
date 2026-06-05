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

echo "Building evaluation dashboard..."
"${RUN[@]}" evaluate \
  --entry navfn="$BENCH/navfn.json" \
  --entry smac="$BENCH/smac.json" \
  --entry teb="$BENCH/teb.json" \
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

echo "Dashboards written to $OUT/{evaluation,trend,replay}.html"
