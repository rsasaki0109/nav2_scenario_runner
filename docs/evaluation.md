# Evaluation Dashboard

`nav2_scenario_runner` is a test runner first, but the same metrics make it a
lightweight **evaluation platform**: run one scenario suite under several Nav2
configurations, then rank them. The `evaluate` command turns a set of run
reports into a single leaderboard dashboard.

## Workflow

1. Run the same scenarios once per configuration, writing a JSON report each
   time. The configuration label is yours to choose (planner, controller, or a
   full parameter set).

   ```bash
   nav2_scenario_runner run scenarios/ --mode attach \
     --report-dir reports/navfn --json-report results.json
   nav2_scenario_runner run scenarios/ --mode attach \
     --report-dir reports/smac --json-report results.json
   ```

2. Combine the reports into one dashboard.

   ```bash
   nav2_scenario_runner evaluate \
     --entry navfn=reports/navfn/results.json \
     --entry smac=reports/smac/results.json \
     --html-output reports/evaluation.html \
     --markdown-output reports/evaluation.md \
     --json-output reports/evaluation.json
   ```

`evaluate` needs at least two `--entry LABEL=report.json` configurations.

## Scoring model

For every scenario the configurations are compared metric by metric. Each
metric value is normalized to `0.0` (worst) .. `1.0` (best) **within that
scenario**, respecting the metric direction. A configuration's composite
**score** is the mean of its normalized values across all comparable cells,
shown as `0-100` where higher is better.

The leaderboard ranks by, in order:

1. **Pass rate** — fraction of scenarios that passed.
2. **Composite score** — overall metric goodness.
3. **Wins** — number of scenario/metric cells where the configuration was best.

Score and wins are independent on purpose: a configuration that is *best-or-worst*
collects many wins but a middling score, while a *consistently strong* one scores
high without topping every cell.

## Metric direction

Defaults treat these metrics as **lower is better**: `travel_time`,
`path_length_traveled`, `path_length`, `recovery_count`, `replanning_count`,
`collision_count`, `duration_seconds`. Boolean-style metrics
`collision_free` and `goal_reached` are **higher is better** (`true` = `1.0`).

Per-goal sub-metrics (`travel_time.<goal_name>`) and the `trajectory` array are
excluded from scoring. Override a direction when your metric differs:

```bash
nav2_scenario_runner evaluate \
  --entry a=a.json --entry b=b.json \
  --higher-is-better clearance \
  --lower-is-better jerk
```

## Dashboard contents

The HTML dashboard has three sections:

- **Leaderboard** — medal cards ranked by score, with a relative score bar.
- **Metric Comparison** — one panel per metric; each bar's length encodes
  relative goodness so the longest bar is always the winner regardless of
  direction, and the label shows the real mean value.
- **Trajectory Overlay** — every configuration's `/odom` trajectory drawn on
  shared axes per scenario, colored to match the leaderboard.

The dashboard is a single self-contained HTML file with inline SVG and no
external assets, suitable for CI artifact upload or GitHub Pages.

## CI usage

Append the leaderboard to a pull request with `--github-summary`, and publish
`evaluation.json` as the machine-readable result for gating or trend tracking:

```bash
nav2_scenario_runner evaluate \
  --entry baseline=reports/baseline.json \
  --entry candidate=reports/candidate.json \
  --github-summary \
  --json-output reports/evaluation.json
```
