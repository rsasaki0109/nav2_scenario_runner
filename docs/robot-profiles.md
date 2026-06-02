# Robot Profiles

Robot profiles make scenario intent portable across robot types.

```yaml
robot:
  profile: my_ackermann_robot

frames:
  map: map
  odom: odom
  base: base_link

topics:
  odom: /odom
  cmd_vel: /cmd_vel
  scan: /scan
  global_plan: /plan

footprint:
  type: polygon
  points:
    - [0.6, 0.35]
    - [0.6, -0.35]
    - [-0.6, -0.35]
    - [-0.6, 0.35]

limits:
  max_linear_velocity: 1.0
  max_angular_velocity: 1.2
  min_turning_radius: 1.5
```

## Profile Responsibilities

- kinematics
- frames
- topics
- velocity limits
- sensor topics
- base command topic
- expected action namespace
- footprint and collision model
- metric normalization

## Differential Drive

Default assumptions:

- in-place rotation is possible
- path curvature constraints are relatively loose
- final yaw alignment is possible
- oscillation detection is important

Metrics emphasis:

- rotate-in-place time
- angular oscillation
- path efficiency
- recovery count

## Ackermann

Default assumptions:

- in-place rotation is not possible
- minimum turning radius matters
- reverse behavior may matter
- final yaw may require more space

Metrics emphasis:

- curvature
- turning radius violation
- reverse distance
- path feasibility
- final heading tolerance

## Omnidirectional

Default assumptions:

- lateral motion is possible
- yaw and translation can be partially decoupled
- narrow passage behavior is important

Metrics emphasis:

- lateral velocity usage
- clearance
- path smoothness
- final alignment

## Compatibility

Scenarios can declare robot requirements:

```yaml
requires:
  robot:
    kinematics: [differential, omnidirectional]
    min_lidar_range: 8.0
```

If the profile is incompatible, the runner should skip or fail clearly:

```text
Scenario requires in_place_rotation=true.
Robot profile ackermann_robot declares in_place_rotation=false.
```
