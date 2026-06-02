# Metrics

Metrics are the core product surface. Goal success alone is insufficient for navigation regression testing.

Important questions:

- Did the robot reach the goal?
- Did it avoid collisions?
- How long did it take?
- How far did it travel?
- Did it rely on recovery behaviors too much?
- Did replanning increase unexpectedly?
- Did quality regress from the baseline?
- Can the artifacts explain the failure?

## Metric Categories

### Outcome Metrics

| Metric | Meaning | Primary sources |
|---|---|---|
| `goal_reached` | Goal action succeeded and final pose is within tolerance | Nav2 action result, TF |
| `timeout` | Scenario or step exceeded time limit | Runner clock |
| `collision_free` | No contact or footprint violation | Simulator contact, costmap, footprint checker |
| `scenario_passed` | All hard assertions passed | Runner |

### Navigation Quality Metrics

| Metric | Meaning |
|---|---|
| `path_length_planned` | Global path length |
| `path_length_traveled` | Integrated distance from odom or TF |
| `path_efficiency` | Straight-line distance divided by traveled distance |
| `minimum_clearance` | Minimum distance from obstacle or lethal costmap cell |
| `max_curvature` | Useful for Ackermann robots |
| `oscillation_score` | Velocity sign changes and heading oscillation |
| `stop_time` | Total time below velocity threshold |

`path_length_planned` and `path_length_traveled` must remain separate. A short planned path can still lead to inefficient controller behavior.

### Behavior Metrics

| Metric | Meaning |
|---|---|
| `recovery_count` | Number of recovery behaviors |
| `replanning_count` | Number of global path updates |
| `costmap_clear_count` | Number of costmap clear events |
| `goal_cancel_count` | Number of goal cancellations |
| `bt_failure_count` | Behavior tree node failures |
| `controller_patience_events` | Controller timeout or patience events |

### Performance Metrics

| Metric | Meaning |
|---|---|
| `travel_time` | Time from goal accepted to goal reached |
| `planning_latency` | Time from path request to path output |
| `control_frequency_actual` | Measured controller loop frequency |
| `sim_real_time_factor` | Simulation speed |
| `cpu_usage` | Optional system metric |
| `memory_usage` | Optional system metric |

### CI Health Metrics

| Metric | Meaning |
|---|---|
| `flake_rate` | Ratio of retry-pass scenarios |
| `scenario_duration` | CI runtime cost |
| `artifact_size` | Artifact growth monitoring |
| `baseline_delta` | Difference from main branch baseline |

## Collection Strategy

### Goal Reached

Primary:

- Nav2 `NavigateToPose` action result
- final pose tolerance check

Secondary:

- robot stopped near goal
- behavior tree navigator success event

Initial v0.1 execution metrics:

- `travel_time`: seconds from accepted `send_goal` to successful `expect_goal_reached`
- `travel_time.<goal_name>`: per-goal travel time using the YAML goal name
- `path_length_traveled`: traveled path length during goal execution
- `path_length_traveled.<goal_name>`: per-goal traveled path length
- `replanning_count`: global plan update count during goal execution
- `replanning_count.<goal_name>`: per-goal global plan update count
- `recovery_count`: recovery behavior count when the backend provides it
- `recovery_count.<goal_name>`: per-goal recovery behavior count when available
- `collision_count`: collision/contact count when the backend provides it
- `collision_count.<goal_name>`: per-goal collision/contact count when available
- `collision_free`: boolean derived from `collision_count == 0`
- `goal_reached`: boolean marker written when `expect_goal_reached` succeeds

Initial v0.1 assertion evaluation:

- `collision_free` checks the `collision_free` metric.
- `goal_reached` checks the `goal_reached` metric.
- `travel_time` supports `max`.
- `path_length` supports `max` against `path_length_traveled`.
- `replanning_count` supports `max`.
- `recovery_count` supports `max` when the metric is available.
- `timeout` supports `max` against scenario duration.
- Assertions whose metrics are unavailable are marked `skipped` in JSON and JUnit `system-out`.
- `severity: warning` records a warning instead of failing the scenario.

The ROS attach backend currently computes `path_length_traveled` by subscribing to namespaced `/odom` and integrating Euclidean distance between odometry samples.
It computes `replanning_count` by counting namespaced `/plan` topic updates during goal execution.
It does not yet collect `recovery_count`; recovery assertions are skipped in ROS attach mode until a reliable Nav2 recovery event source is added.
ROS attach mode does not collect `collision_count`; collision assertions require a simulator/contact backend. Gazebo Sim mode can emit `collision_count` and `collision_free` when `--collect-contacts` is used.

### Collision Free

Collision collection is capability-based:

1. simulator contact events
2. collision topic
3. footprint vs costmap checker
4. lidar or costmap clearance proxy

If no valid strategy is available and the assertion is required, validation should fail before execution.

```yaml
assertions:
  - collision_free:
      method: auto
```

### Recovery Count

Candidate sources:

- Nav2 behavior events
- behavior tree log
- Nav2 log pattern
- plugin-specific event stream

v1 should make the source explicit when ambiguity matters:

```yaml
metrics:
  recovery_count:
    source: nav2_behavior_events
```

### Replanning Count

Candidate sources:

- global path topic update count
- `ComputePathToPose` action call count
- behavior tree event
- planner server log

v1 should default to global path topic update count and leave deeper Nav2 event integration to plugins.

## Assertion Model

Hard assertion:

```yaml
- collision_free: {}
```

Warning assertion:

```yaml
- path_length:
    max: 12.0
    severity: warning
```

## Baseline Regression

```yaml
regression:
  baseline: reports/main/latest.json
  compare:
    path_length_traveled:
      max_increase_percent: 10
    travel_time:
      max_increase_percent: 15
    recovery_count:
      max_delta: 1
```

Comparison modes:

| Mode | Purpose |
|---|---|
| absolute threshold | safety and acceptance gates |
| baseline delta | regression detection |
| statistical band | noisy metrics and flaky environments |

Initial CLI support:

```bash
nav2_scenario_runner compare reports/current.json \
  --baseline reports/main.json \
  --max-increase-percent path_length_traveled=10 \
  --max-increase-percent travel_time=15 \
  --max-delta recovery_count=1
```

The initial implementation compares scenario status by default. Numeric metric regression checks are enabled by explicit CLI rules. Metric values are read from each scenario's `metrics` object in `results.json`.

## Reports

Console output should be dense:

```text
PASS straight_line_goal        12.4s   path=10.8m  recovery=0  replan=1
FAIL dynamic_obstacle_crossing 60.0s   timeout     recovery=3  replan=8

Failures:
  dynamic_obstacle_crossing
    step: expect_goal_reached
    reason: timeout after 60s
    artifacts:
      - report.html
      - trace.json
      - rosbag2/
      - nav2.log
```

HTML reports should include:

- timeline
- map overlay
- robot trajectory
- planned path
- collision markers
- dynamic entities
- step log
- metric table
- baseline diff
- ROS logs
- failure reason
