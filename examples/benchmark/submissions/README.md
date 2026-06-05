# Community benchmark submissions

Drop a Nav2 run report here to put your configuration on the **public
leaderboard**. Every `*.json` file in this directory is included by
[`scripts/build_dashboards.sh`](../../../scripts/build_dashboards.sh) and appears
on the [live benchmark dashboard](https://rsasaki0109.github.io/nav2_scenario_runner/#benchmark)
on the next deploy.

## How to submit

1. Run the benchmark scenario suite under your Nav2 configuration and produce a
   JSON run report:

   ```bash
   nav2_scenario_runner run scenarios/ --report-dir reports/
   ```

2. Copy the report here, named after your configuration (the file stem becomes
   the leaderboard label):

   ```
   examples/benchmark/submissions/my-planner.json
   ```

3. Open a pull request. CI validates the file, and once merged your entry shows
   up on the leaderboard.

## Requirements

- The report must cover the **same scenario ids** as the core configs so the
  comparison is apples-to-apples: `straight_line`, `narrow_corridor`, `u_turn`.
- Use a descriptive, kebab-case filename (e.g. `acme-smac-tuned.json`). It must
  be unique among submissions.
- Include real metrics. Optional `trajectory` arrays (lists of `{x, y}` in map
  frame) light up the trajectory overlay; keep them within the
  [warehouse map](../maps/warehouse.yaml) bounds.
- One configuration per file.

See [`community-dwb.json`](community-dwb.json) for a complete, valid example, and
[docs/pr-benchmark-bot.md](../../../docs/pr-benchmark-bot.md) for the comment bot
that renders these into a leaderboard.
