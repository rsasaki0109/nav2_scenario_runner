# Real Nav2 Benchmark (Docker + CI)

The published leaderboard, trend, and explorer can be driven by **real Nav2 +
Gazebo runs**, not just the bundled example fixtures. This page describes the
containerized, reproducible flow.

## Why a container

A real benchmark needs a full robotics stack — Nav2, a controller/planner, a
simulator, and a robot description. The [`docker/Dockerfile`](../docker/Dockerfile)
pins all of it on ROS 2 Jazzy using Nav2's own demo robot
(`nav2_minimal_tb3_sim`), so the benchmark runs anywhere Docker does, with no
host ROS setup.

## Build and run locally

```bash
# from the repo root
docker build -f docker/Dockerfile -t nav2-scenario-runner:jazzy-gazebo .

# run the benchmark suite against real Nav2 and emit dashboards into ./out
docker run --rm -v "$PWD/out:/out" \
  -e CONFIG_LABEL=nav2-jazzy \
  nav2-scenario-runner:jazzy-gazebo \
  "bash docker/run_benchmark.sh /out"
```

`out/` then contains the real run reports plus `trend.html`, `viewer.html`, and
(when ≥2 configs are present) `evaluation.html`.

## The pipeline

[`docker/run_benchmark.sh`](../docker/run_benchmark.sh) does the real work:

1. `doctor --check-gazebo` preflight.
2. `run examples/benchmark/scenarios/ --mode gazebo-sim` with the full execution
   ladder (`--launch-scenario-stack --wait-for-ros-graph --wait-for-nav2
   --wait-for-navigation-data --execute-nav2 --collect-contacts`), producing a
   real `results.json`.
3. The run report **shares the benchmark config schema**, so it feeds the
   dashboards directly — no conversion. It is copied to `out/<CONFIG_LABEL>.json`.
4. `record` appends the run to `out/history.jsonl` (labelled by commit SHA).
5. `trend` and `viewer` (and `evaluate` once ≥2 configs exist) render the
   dashboards from the real reports.

The benchmark scenarios live in
[`examples/benchmark/scenarios/`](../examples/benchmark/scenarios/) —
`straight_line`, `narrow_corridor`, and `u_turn`. Their ids match the fixture
configs, so real runs slot into the same leaderboard and explorer rows. They are
linted and dry-run in CI (`tests/test_benchmark_scenarios.py`).

## In CI

[`.github/workflows/nav2-benchmark.yml`](../.github/workflows/nav2-benchmark.yml)
builds the image and runs the benchmark **on demand** (`workflow_dispatch`) and
**weekly** (Mondays 06:00 UTC) — not per-PR, because a full Gazebo run is slow.
It uploads `out/` (reports + dashboards) as an artifact and writes a pass/total
line to the job summary. The per-PR
[benchmark bot](pr-benchmark-bot.md) stays on the lightweight fixtures for fast
feedback.

## Comparing planners

To rank multiple configurations, run the suite once per planner/controller
parameter set with a distinct `CONFIG_LABEL`, writing each `out/<label>.json`
into the same directory. `run_benchmark.sh` calls `evaluate` automatically once
two or more config reports are present, and `viewer`/`evaluate` then show them
side by side.

> The committed `examples/benchmark/*.json` fixtures are representative samples
> so the public dashboards render deterministically without a GPU/sim in the
> Pages job. Replace them (or add submissions) with real `run_benchmark.sh`
> output to publish measured numbers.
