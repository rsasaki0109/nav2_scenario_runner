# Trend Tracking

While [evaluation](evaluation.md) compares configurations *against each other*,
trend tracking watches one configuration *over time*. Record each run into an
append-only history store and render how navigation quality drifts across
commits, so CI can surface a slow regression that no single run would fail.

## Workflow

1. After a run, append its report to the history store, labeling it with the
   commit it came from.

   ```bash
   nav2_scenario_runner run scenarios/ --mode attach \
     --report-dir reports --json-report results.json

   nav2_scenario_runner record reports/results.json \
     --history reports/history.jsonl \
     --label "$(git rev-parse --short HEAD)"
   ```

   `record` keeps only scalar metrics (numbers and booleans). Trajectories and
   artifact paths are dropped so the store stays small. If `--label` is omitted
   it falls back to the report's `generated_at`.

2. Render the trend dashboard from the accumulated history.

   ```bash
   nav2_scenario_runner trend reports/history.jsonl \
     --html-output reports/trend.html \
     --markdown-output reports/trend.md \
     --json-output reports/trend.json
   ```

## History store

The store is JSONL — one self-contained run per line:

```json
{"label": "a1b2c3d", "timestamp": "2026-06-05T...", "mode": "attach",
 "total": 2, "passed": 2, "failed": 0,
 "scenarios": {"straight_line": {"status": "passed",
   "metrics": {"travel_time": 12.4, "path_length_traveled": 10.2}}}}
```

Appending is atomic per line, so the same file can be committed to the repo,
stored as a CI artifact, or kept on a branch as a rolling baseline.

## Dashboard contents

- **Pass Rate** — suite pass rate across every recorded run.
- **Metric Trends** — one panel per metric, one line per scenario, with the
  shared y-axis scaled to the data. Direction (`lower is better` /
  `higher is better`) is labeled per panel.

The Markdown summary adds a latest-vs-previous delta per scenario with a
direction-aware marker (`▼ better`, `▲ worse`, `→ stable`). The JSON output
exposes `latest_deltas` with an `improved` flag per metric for CI gating.

## CI usage

Commit or upload `history.jsonl`, append the latest run, and publish the trend
to the pull request:

```bash
nav2_scenario_runner record reports/results.json --history history.jsonl --label "$GITHUB_SHA"
nav2_scenario_runner trend history.jsonl --github-summary --json-output reports/trend.json
```
