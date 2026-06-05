# Interactive Benchmark Explorer

`viewer` renders a **single self-contained HTML page** that turns a set of Nav2
run reports into an interactive explorer: toggle planner configs, pick a
scenario, and scrub or play the robot along every recorded trajectory over the
real map — all with dependency-free vanilla JavaScript and the data embedded in
the page.

Because everything (map PNG, trajectories, metrics) lives inside the one file,
it opens straight from `file://` and from GitHub Pages alike, which makes it easy
to share a short screen capture.

## Usage

```bash
nav2_scenario_runner viewer \
  --entry navfn=reports/navfn.json \
  --entry smac=reports/smac.json \
  --entry teb=reports/teb.json \
  --map maps/warehouse.yaml \
  --title "Nav2 Benchmark Explorer" \
  --html-output reports/viewer.html
```

- `--entry LABEL=report.json` — one per configuration (repeatable). A single
  config is allowed; two or more enable side-by-side comparison.
- `--map map.yaml` — optional ROS map (`map.yaml` + P2/P5 PGM). With it, the map
  is drawn under the trajectories; without it, the view auto-fits a bounding box
  over the visible trajectories.
- `--title` — page heading.

## What you can do in the page

- **Planners** — checkboxes toggle each config on/off; the canvas and the metric
  table update live. Each config keeps a stable color from the shared palette.
- **Scenario** — a dropdown switches the active scenario.
- **Scrub / Play** — a slider moves the robot marker along each trajectory; the
  travelled portion of the path brightens. Play loops the run (~4s).
- **Metrics table** — scalar metrics per visible config for the active scenario,
  with the best cell starred using the same lower/higher-is-better directions as
  `evaluate`.

## How the data is embedded

The benchmark data is serialized to JSON and embedded in a
`<script type="application/json">` block. To make that safe, every `<` in the
payload is written as `<`, so a scenario id or label can never break out of
the script element. The page parses the block on load and renders with the
Canvas 2D API.

## Public site

`scripts/build_dashboards.sh` builds the explorer for the bundled
[example benchmark suite](../examples/benchmark/) (including any community
[submissions](../examples/benchmark/submissions/)) and publishes it at
[`/viewer.html`](https://rsasaki0109.github.io/nav2_scenario_runner/viewer.html),
linked from the [benchmark gallery](https://rsasaki0109.github.io/nav2_scenario_runner/#benchmark).
