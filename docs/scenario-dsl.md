# Scenario DSL

The DSL optimizes for readability, reviewability, CI stability, extensibility, simulator independence, and an escape hatch for low-level ROS 2 operations.

## Basic Scenario

```yaml
apiVersion: nav2.scenario/v1alpha1
kind: Scenario

metadata:
  name: straight_line_goal
  description: Robot should reach a goal 10m ahead without collision.
  tags: [smoke, navigation, diff_drive]
  owner: navigation-team

runtime:
  timeout: 90
  use_sim_time: true
  seed: 42
  isolation:
    ros_domain_id: auto
    namespace: /robot1

simulator:
  type: gazebo_sim
  headless: true
  world: worlds/empty.sdf
  launch:
    package: my_robot_bringup
    file: sim.launch.py

robot:
  profile: turtlebot3_waffle
  initial_pose:
    x: 0
    y: 0
    yaw: 0

nav2:
  bringup:
    package: nav2_bringup
    file: bringup_launch.py
  params: config/nav2_params.yaml
  map: maps/warehouse.yaml
  autostart: true

steps:
  - wait_for_nav2_active:
      timeout: 30
  - set_initial_pose:
      x: 0
      y: 0
      yaw: 0
  - send_goal:
      name: main_goal
      pose:
        x: 10
        y: 0
        yaw: 0
  - expect_goal_reached:
      goal: main_goal
      timeout: 60

assertions:
  - collision_free: {}
  - path_length:
      max: 13.0
  - travel_time:
      max: 60.0
  - recovery_count:
      max: 0

artifacts:
  rosbag: on_failure
  html_report: always
  timeline: always
```

## DSL Layers

### Layer 1: User-Friendly Scenario DSL

Daily usage should be short and Nav2-aware.

```yaml
- send_goal:
    x: 10
    y: 0
    yaw: 0
```

### Layer 2: Advanced Scenario DSL

Advanced scenarios can use events, conditionals, parallel branches, and templates.

```yaml
- parallel:
    branches:
      - steps:
          - wait:
              seconds: 5
          - spawn_obstacle:
              name: box1
              x: 5
              y: 0
      - steps:
          - send_goal:
              x: 10
              y: 0
              yaw: 0
```

### Layer 3: Escape Hatch

Low-level ROS 2 operations are allowed, but should not be the default path.

```yaml
- call_service:
    service: /global_costmap/clear_entirely_global_costmap
    type: nav2_msgs/srv/ClearEntireCostmap
    request: {}
```

## Built-In Actions

Navigation:

```yaml
- wait_for_nav2_active:
    timeout: 30

- set_initial_pose:
    x: 0
    y: 0
    yaw: 0

- send_goal:
    name: goal_1
    pose: {x: 10, y: 0, yaw: 0}
    behavior_tree: optional_bt.xml

- send_waypoints:
    name: patrol
    poses:
      - {x: 1, y: 0, yaw: 0}
      - {x: 2, y: 2, yaw: 1.57}

- cancel_goal:
    goal: goal_1

- clear_costmaps: {}

- select_planner:
    id: GridBased

- select_controller:
    id: FollowPath
```

Simulator:

```yaml
- spawn_obstacle:
    name: pallet
    type: box
    pose: {x: 4.0, y: 0.2, yaw: 0}
    size: {x: 0.8, y: 0.8, z: 1.0}

- delete_entity:
    name: pallet

- move_entity:
    name: pallet
    trajectory:
      - at: 0.0
        pose: {x: 4.0, y: 0.2, yaw: 0}
      - at: 5.0
        pose: {x: 4.0, y: -0.5, yaw: 0}

- spawn_person:
    name: person_1
    pose: {x: 5.0, y: -1.0, yaw: 1.57}
    behavior:
      type: walk_line
      to: {x: 5.0, y: 1.0}
      speed: 0.8

- set_door:
    name: door_A
    state: closed
```

Observation:

```yaml
- wait:
    seconds: 3

- wait_until:
    condition: "distance(robot.pose, goal.pose) < 2.0"
    timeout: 20

- wait_for_topic:
    topic: /scan
    timeout: 10

- wait_for_transform:
    from: map
    to: base_link
    timeout: 10
```

## Built-In Assertions

```yaml
assertions:
  - goal_reached:
      goal: main_goal
      tolerance_xy: 0.25
      tolerance_yaw: 0.25

  - collision_free:
      method: simulator_contact_or_footprint

  - timeout:
      max: 60

  - path_length:
      max: 12.5

  - travel_time:
      max: 50

  - recovery_count:
      max: 1

  - replanning_count:
      max: 5

  - minimum_clearance:
      min: 0.20

  - final_pose:
      within:
        x: 10
        y: 0
        yaw: 0
        tolerance_xy: 0.25
        tolerance_yaw: 0.25
```

Assertions can be hard failures or warnings:

```yaml
- path_length:
    max: 12.0
    severity: warning
```

The initial runner evaluates `collision_free`, `goal_reached`, `travel_time`, `path_length`, `replanning_count`, `recovery_count`, and `timeout` when the corresponding metrics are available. Assertions whose collectors are not implemented yet for the selected backend are reported as `skipped` rather than silently ignored.

## Event-Driven Scenario

```yaml
steps:
  - send_goal:
      name: main_goal
      pose: {x: 10, y: 0, yaw: 0}

  - on_event:
      event: nav2.goal.feedback
      when: "feedback.distance_remaining < 5.0"
      do:
        - spawn_obstacle:
            name: surprise_box
            type: box
            pose: {x: 6.0, y: 0.0, yaw: 0}
            size: {x: 0.7, y: 0.7, z: 1.0}

  - expect_goal_reached:
      goal: main_goal
      timeout: 60
```

## Conditionals

```yaml
steps:
  - if:
      condition: "${runtime.simulator} == 'gazebo_sim'"
      then:
        - spawn_obstacle:
            name: gazebo_box
            type: box
            pose: {x: 3, y: 0, yaw: 0}
      else:
        - log:
            message: "Skipping simulator-specific obstacle"
```

Conditionals should be limited to capability differences and scenario reuse.

## Parallel Branches

```yaml
steps:
  - parallel:
      join: all
      branches:
        - name: navigation
          steps:
            - send_goal:
                name: main_goal
                pose: {x: 10, y: 0, yaw: 0}
            - expect_goal_reached:
                goal: main_goal
                timeout: 60

        - name: dynamic_obstacle
          steps:
            - wait:
                seconds: 8
            - spawn_person:
                name: crossing_person
                pose: {x: 5, y: -2, yaw: 1.57}
                behavior:
                  type: walk_line
                  to: {x: 5, y: 2}
                  speed: 0.7
```

## Templates

```yaml
apiVersion: nav2.scenario/v1alpha1
kind: Template

metadata:
  name: simple_goal_test

parameters:
  start:
    type: pose2d
  goal:
    type: pose2d
  timeout:
    type: number
    default: 60

steps:
  - set_initial_pose: ${start}
  - send_goal:
      name: goal
      pose: ${goal}
  - expect_goal_reached:
      goal: goal
      timeout: ${timeout}
```

Usage:

```yaml
use:
  template: simple_goal_test
  with:
    start: {x: 0, y: 0, yaw: 0}
    goal: {x: 10, y: 0, yaw: 0}
    timeout: 60
```

## Versioning

- `v1alpha1`: breaking changes allowed
- `v1beta1`: main concepts frozen and plugin authors invited
- `v1`: backward compatibility guaranteed
- `v2`: only for major semantic changes

Compatibility rules:

- v1 scenarios must run on all v1.x runners.
- v1 runners may warn on deprecated fields.
- v1 runners must fail clearly on unknown required capabilities.
