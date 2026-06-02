# Gazebo Sim

`gazebo-sim` mode is currently a lifecycle smoke for the Gazebo Sim adapter. It validates that a scenario can launch its configured world with `gz sim`, can optionally start scenario launch blocks, can reset the world, can apply top-level simulator entity steps, can schedule top-level `parallel` simulator branches during Nav2 execution, can collect Gazebo contact topics, observes one `/clock` message, can execute the built-in Nav2 steps against the active ROS graph, shuts processes down, and preserves logs as CI artifacts.

It does not yet provide deep readiness checks for launched ROS stacks or full event-driven `on_event` execution.

## Requirements

Run the preflight check first:

```bash
nav2_scenario_runner doctor --check-gazebo
```

Required checks:

- `gz` on `PATH`
- `gz sim --help`
- `ros2` on `PATH`
- `ros2 pkg prefix ros_gz_bridge`

To inspect ROS graph readiness separately:

```bash
nav2_scenario_runner doctor --check-ros-graph
```

This verifies `ros2 node list` and `ros2 topic list`.

## Readiness Stages

The Gazebo Sim adapter is being built in explicit layers:

1. Process lifecycle smoke: launch `gz sim`, keep it alive briefly, stop it, and collect artifacts.
2. Scenario stack launch: optionally start `simulator.launch` and `nav2.bringup` blocks with `--launch-scenario-stack`.
3. World reset: optionally reset the Gazebo world with `--reset-world`.
4. Simulator steps: optionally apply top-level `spawn_obstacle`, `move_entity`, `delete_entity`, and `wait` steps with `--execute-simulator-steps`.
5. Contact collection: optionally monitor Gazebo contact topics with `--collect-contacts`.
6. ROS graph readiness: optionally verify the ROS CLI can inspect the active graph with `--wait-for-ros-graph`.
7. `/clock` readiness: optionally wait until simulation time is available with `--wait-for-clock`.
8. Nav2 readiness: optionally verify the `NavigateToPose` action server with `--wait-for-nav2`.
9. Navigation data readiness: optionally verify TF, map, and costmap topics with `--wait-for-navigation-data`.
10. Nav2 action execution: optionally run scenario steps against Nav2 while Gazebo is active with `--execute-nav2`.
11. Scheduled simulator branches: when `--execute-nav2` and `--execute-simulator-steps` are both enabled, top-level `parallel` branches containing `wait`, `spawn_obstacle`, `move_entity`, or `delete_entity` run while Nav2 steps execute.

## Scenario Shape

The current lifecycle smoke reads:

```yaml
simulator:
  type: gazebo_sim
  headless: true
  world: worlds/empty.sdf
```

Relative `world` paths are resolved from the scenario file directory. Local-looking paths such as `worlds/empty.sdf` or `/tmp/world.sdf` must exist before `gz sim` is launched, so missing example assets fail early with a clear error.

Resource URIs such as `model://demo_world` are passed through to `gz sim`.

## Run

```bash
nav2_scenario_runner run examples/turtlebot3_gazebo/smoke.yaml \
  --mode gazebo-sim \
  --sim-startup-timeout 5 \
  --launch-scenario-stack \
  --reset-world \
  --world-reset-timeout 10 \
  --execute-simulator-steps \
  --simulator-step-timeout 10 \
  --collect-contacts \
  --contact-topic /world/empty/model/robot/link/base_link/sensor/contact/contact \
  --wait-for-ros-graph \
  --ros-graph-timeout 10 \
  --wait-for-clock \
  --clock-timeout 10 \
  --wait-for-nav2 \
  --nav2-timeout 30 \
  --wait-for-navigation-data \
  --navigation-data-timeout 30 \
  --execute-nav2 \
  --report-dir reports/ \
  --trace-report trace.json \
  --html-report index.html
```

By default, `--mode gazebo-sim` runs the same checks as `doctor --check-gazebo` before launching `gz sim`.

`--launch-scenario-stack` starts `simulator.launch` and `nav2.bringup` blocks when they exist in the scenario. Commands are launched as `ros2 launch <package> <file> key:=value`, and logs are saved beside `gazebo.log`.

`--wait-for-ros-graph` runs `ros2 node list` and `ros2 topic list` after process startup. This catches ROS graph visibility problems before `/clock` or Nav2 step execution.

`--reset-world` calls the Gazebo service `/world/<name>/control` with `reset: {all: true}` after the simulator and optional launch stack have survived startup. For local SDF files, `<name>` comes from the first `<world name="...">` element; if no world name can be parsed, the file stem is used. Resource URI worlds fall back to the URI stem.

`--execute-simulator-steps` walks the top-level scenario steps and applies Gazebo-backed simulator actions before readiness checks. The current scope supports `spawn_obstacle` with `type: box`, `move_entity` with either `pose` or `trajectory`, `delete_entity`, and `wait`. Nav2 steps are skipped by this pass. When `--execute-nav2` is also enabled, top-level `parallel` branches are split: Nav2 branches are flattened into the Nav2 execution scenario, and simulator branches are scheduled in background threads while Nav2 executes. Without `--execute-nav2`, `parallel` still fails clearly. Higher-level dynamic constructs such as `on_event`, `spawn_person`, and `set_door` are not executed yet.

`spawn_obstacle` creates an inline static SDF box through `/world/<name>/create`. `move_entity` sets model poses through `/world/<name>/set_pose`; trajectory `at` values are relative to the start of that `move_entity` step and must be non-decreasing. `delete_entity` removes a model through `/world/<name>/remove`.

`--collect-contacts` starts `gz topic -e` monitors for Gazebo contact topics and parses their logs at teardown. When `--contact-topic` is not provided, the runner uses `gz topic -l` and selects topics whose names contain `contact`. The collector emits `collision_count`, `collision_free`, and contact pair summaries, and can evaluate `collision_free` assertions from Gazebo contact data.

`--wait-for-nav2` creates the attach backend and waits for the Nav2 `NavigateToPose` action server. This gives a dedicated readiness failure before scenario steps begin.

`--wait-for-navigation-data` waits for one message from TF, map, global costmap, and local costmap topics. Defaults are `/tf`, `<namespace>/map`, `<namespace>/global_costmap/costmap`, and `<namespace>/local_costmap/costmap`. Override them with `robot.topics.tf`, `robot.topics.map`, `robot.topics.global_costmap`, and `robot.topics.local_costmap`.

`--execute-nav2` reuses the attach backend while the Gazebo process is alive. It expects Nav2 action servers and the relevant topics to become available in the ROS graph. Scenario `runtime.isolation.namespace` is respected by the attach backend.

Use this only in prevalidated CI images or test harnesses:

```bash
nav2_scenario_runner run examples/turtlebot3_gazebo/smoke.yaml \
  --mode gazebo-sim \
  --skip-gazebo-preflight
```

The runner launches:

```bash
gz sim -s examples/turtlebot3_gazebo/worlds/empty.sdf
```

when `headless: true`.

## Artifacts

Generated artifacts include the normal run reports plus a scenario bundle:

- `reports/results.json`
- `reports/junit.xml`
- `reports/trace.json` when requested
- `reports/index.html` when requested
- `reports/artifacts/<scenario_id>/scenario.yaml`
- `reports/artifacts/<scenario_id>/gazebo.log`
- `reports/artifacts/<scenario_id>/simulator_launch.log` when `--launch-scenario-stack` starts `simulator.launch`
- `reports/artifacts/<scenario_id>/nav2_bringup.log` when `--launch-scenario-stack` starts `nav2.bringup`
- `reports/artifacts/<scenario_id>/metadata.json`

Trace reports use explicit step `time_offset_seconds` when the Gazebo Sim backend provides it. This keeps scheduled top-level `parallel` simulator branches in timeline order even though the normal step summary remains grouped by lifecycle stage.

The JSON result includes:

- `simulator_started`
- `simulator_backend`
- `simulator_command`
- `artifact_dir`
- `scenario_copy`
- `gazebo_log`
- `simulator_log`
- `metadata`
- `world`
- `preflight_skipped`
- `error_type`
- `clock_requested`
- `clock_ready` when `--wait-for-clock` is set
- `clock_wait_seconds` when `--wait-for-clock` is set
- `clock_timeout` when `--wait-for-clock` is set
- `clock_command` when `--wait-for-clock` is set
- `ros_graph_ready` when `--wait-for-ros-graph` is set
- `ros_graph_wait_seconds` when `--wait-for-ros-graph` is set
- `ros_graph_timeout` when `--wait-for-ros-graph` is set
- `ros_graph_commands` when `--wait-for-ros-graph` is set
- `nav2_ready` when `--wait-for-nav2` is set
- `nav2_wait_seconds` when `--wait-for-nav2` is set
- `nav2_timeout` when `--wait-for-nav2` is set
- `navigation_data_ready` when `--wait-for-navigation-data` is set
- `navigation_data_wait_seconds` when `--wait-for-navigation-data` is set
- `navigation_data_timeout` when `--wait-for-navigation-data` is set
- `navigation_data_topics` when `--wait-for-navigation-data` is set
- `world_reset_succeeded` when `--reset-world` is set
- `world_reset_seconds` when `--reset-world` is set
- `world_reset_timeout` when `--reset-world` is set
- `world_reset_command` when `--reset-world` is set
- `simulator_steps_executed` when `--execute-simulator-steps` is set
- `simulator_steps_skipped` when `--execute-simulator-steps` is set
- `simulator_step_timeout` when `--execute-simulator-steps` is set
- `simulator_step_commands` when `--execute-simulator-steps` is set
- `scheduled_simulator_steps` when `--execute-simulator-steps` is set
- `spawned_entities` when `--execute-simulator-steps` is set
- `moved_entities` when `--execute-simulator-steps` is set
- `deleted_entities` when `--execute-simulator-steps` is set
- `collision_count` when `--collect-contacts` is set
- `collision_free` when `--collect-contacts` is set
- `contact_topics` when `--collect-contacts` is set
- `contact_logs` when `--collect-contacts` is set
- `contact_pairs` when `--collect-contacts` is set
- `nav2_executed`
- `nav2_status`
- `launch_scenario_stack`
- `launch_stack_started`
- `launch_process_count`
- `simulator_launch_log` when available
- `nav2_bringup_log` when available

`metadata.json` includes:

- command
- mode
- world
- started_at
- duration_seconds
- exit_code
- status
- error_type
- failure_reason
- preflight_skipped
- clock_requested
- clock_command
- clock_timeout
- clock_ready
- clock_wait_seconds
- clock_error
- ros_graph_requested
- ros_graph_commands
- ros_graph_timeout
- ros_graph_ready
- ros_graph_wait_seconds
- ros_graph_error
- nav2_readiness_requested
- nav2_timeout
- nav2_ready
- nav2_wait_seconds
- nav2_error
- navigation_data_requested
- navigation_data_topics
- navigation_data_commands
- navigation_data_timeout
- navigation_data_ready
- navigation_data_wait_seconds
- navigation_data_error
- world_reset_requested
- world_reset_command
- world_reset_timeout
- world_reset_succeeded
- world_reset_seconds
- world_reset_error
- execute_simulator_steps
- simulator_step_timeout
- simulator_steps_executed
- simulator_steps_skipped
- simulator_step_commands
- simulator_step_error
- spawned_entities
- moved_entities
- deleted_entities
- contact_collection_requested
- contact_topics
- contact_commands
- contact_logs
- contact_collection_ready
- contact_collection_seconds
- contact_collection_error
- contact_pairs
- collision_count
- collision_free
- execute_nav2
- nav2_status
- launch_scenario_stack
- launch_stack_started
- launch_processes
- scheduled_simulator_steps

When `--html-report index.html` is used, the HTML report shows the artifact bundle paths for each Gazebo Sim scenario, including the scenario copy, Gazebo log, and metadata file.

## Current Limits

- No semantic readiness checks for launched ROS stack processes beyond ROS graph visibility, Nav2 action availability, and core navigation data topics yet.
- `spawn_obstacle` currently supports static `type: box` only.
- `parallel` scheduling is top-level only and currently supports simulator branches while `--execute-nav2` is active.
- `on_event` scheduling is not implemented yet.
- `spawn_person` and `set_door` are not executed by the Gazebo Sim adapter yet.
- Contact collection requires contact topics to exist. Configure `--contact-topic` when topic discovery is insufficient.

The next adapter milestone is event-driven `on_event` scheduling and richer contact artifacts.
