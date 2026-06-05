# Benchmark Fixtures

Sample run reports that drive the public dashboards on the
[project site](https://rsasaki0109.github.io/nav2_scenario_runner/#benchmark).
They are illustrative fixtures (not captured from a live robot) so the published
benchmark is reproducible and deterministic.

| File | Used by |
|---|---|
| `navfn.json`, `smac.json`, `teb.json` | `evaluate` leaderboard (three configurations, three scenarios, with trajectories) |
| `history.jsonl` | `trend` dashboard (six dated runs) |
| `maps/warehouse.yaml` + `maps/warehouse.pgm` | `replay` map underlay |

Rebuild the dashboards into `docs/` with:

```bash
bash scripts/build_dashboards.sh
```

The GitHub Pages workflow runs the same script on every deploy, so the live site
always matches these fixtures. `tests/test_benchmark_fixtures.py` keeps them
loadable and inside the map bounds.
