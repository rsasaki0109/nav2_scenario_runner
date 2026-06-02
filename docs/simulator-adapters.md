# Simulator Adapters

Simulator adapters hide simulator-specific details behind one contract. Scenario YAML should express intent, not SDF, USD, WBT, or simulator API calls.

User-level DSL:

```yaml
- spawn_obstacle:
    name: box
    pose: {x: 4, y: 0, yaw: 0}
```

Adapter implementations may map this to Gazebo entities, Isaac USD prims, Webots Supervisor operations, or another backend.

## Capability Model

Adapters declare capabilities:

```yaml
capabilities:
  world.load: v1
  world.reset: v1
  sim.pause: v1
  sim.step: v1
  entity.spawn.static: v1
  entity.spawn.dynamic: v1
  entity.set_pose: v1
  actor.person.walk: v1
  door.set_state: v1
  contact.events: v1
  screenshot.capture: v1
```

Execution fails before runtime if a scenario requires unsupported capabilities:

```text
Scenario requires actor.person.walk:v1.
Selected adapter gazebo_classic declares actor.person.walk:unsupported.
```

## Conceptual Contract

Adapters are responsible for:

- `prepare()`
- `start()`
- `wait_until_ready()`
- `load_world()`
- `reset_world()`
- `spawn_entity()`
- `delete_entity()`
- `set_entity_pose()`
- `spawn_actor()`
- `set_actor_trajectory()`
- `set_door_state()`
- `pause()`
- `resume()`
- `step()`
- `get_entity_pose()`
- `subscribe_contacts()`
- `capture_artifact()`
- `shutdown()`

This is a responsibility boundary, not a frozen class API.

## Gazebo Sim

Positioning:

- primary v1 OSS simulator target
- recommended headless CI backend
- successor path for many Gazebo Classic workflows

Adapter responsibilities:

- launch `gz sim -s`
- coordinate `ros_gz_bridge`
- wait for `/clock`
- load SDF worlds
- spawn and delete entities
- manipulate entity pose
- collect contact events
- capture real-time factor
- optionally capture screenshots

Recommended v1 scope:

- static obstacle spawn
- dynamic entity pose update
- contact-based collision
- world reset
- headless GitHub Actions compatibility

Current implementation status:

- `nav2_scenario_runner doctor --check-gazebo` validates the Gazebo Sim preflight surface.
- `nav2_scenario_runner run scenario.yaml --mode gazebo-sim` performs a lifecycle smoke: validate the local world path, launch `gz sim`, optionally start `simulator.launch` and `nav2.bringup` with `--launch-scenario-stack`, keep processes alive for `--sim-startup-timeout`, optionally reset the world with `--reset-world`, optionally apply top-level `spawn_obstacle`, `move_entity`, `delete_entity`, and `wait` steps with `--execute-simulator-steps`, optionally schedule top-level `parallel` simulator branches during `--execute-nav2`, optionally collect contact topics with `--collect-contacts`, optionally verify ROS graph visibility with `--wait-for-ros-graph`, optionally wait for `/clock` with `--wait-for-clock`, optionally verify Nav2 action availability with `--wait-for-nav2`, optionally verify TF/map/costmap topics with `--wait-for-navigation-data`, optionally execute Nav2 steps with `--execute-nav2`, shut processes down, and write a scenario bundle under `reports/artifacts/<scenario>/`.
- The current lifecycle smoke does not yet perform semantic readiness checks for launched ROS stack processes beyond ROS graph visibility, Nav2 action availability, and core navigation data topics or full event-driven `on_event` simulator scheduling.

## Gazebo Classic

Positioning:

- legacy support
- useful for existing Nav2/Gazebo Classic assets
- supported but not the strategic default

Risks:

- distribution compatibility
- dependency availability
- CI image maintenance
- long-term support burden

Strategy:

- separate plugin
- optional install such as `nav2_scenario_runner[gazebo-classic]`
- no core dependency

## Isaac Sim

Positioning:

- advanced, enterprise, photorealistic, and synthetic data workflows
- GPU or self-hosted runner environments
- experimental or beta in early releases

Adapter responsibilities:

- launch Isaac Sim Python scripts
- load USD stages
- validate ROS 2 bridge readiness
- spawn robot and obstacle prims
- move actors through Python APIs
- capture camera and screenshots
- support headless/EGL where possible
- validate GPU availability

Risks:

- large containers
- GPU runner requirements
- version compatibility
- startup time
- proprietary distribution constraints

Strategy:

- keep outside core
- provide adapter contract and reference adapter
- make enterprise integration straightforward without burdening the default OSS install

## Webots

Positioning:

- lightweight, education, research, and cross-platform workflows
- CPU-friendly CI candidate
- useful where Webots robot models already exist

Adapter responsibilities:

- launch Webots headless
- load worlds
- control entities through Supervisor APIs
- validate ROS 2 wrapper readiness
- get robot pose
- expose collision proxies
- optionally capture screenshots

Risks:

- fewer Nav2 examples than Gazebo
- Supervisor API differences
- world/model format differences

Strategy:

- introduce after Gazebo Sim is stable
- promote to official support when smoke scenarios are stable

## RMF Integration

RMF is an optional plugin source for infrastructure events:

```yaml
- rmf_set_door:
    name: pantry_door
    state: closed

- rmf_spawn_crowd:
    zone: lobby
    count: 10
```

RMF belongs outside core because fleet, building, and infrastructure orchestration are broader than Nav2 scenario testing.
