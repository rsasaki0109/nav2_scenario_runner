from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_TEMPLATE = "turtlebot3-gazebo"


class InitError(RuntimeError):
    """Raised when project initialization cannot be completed safely."""


@dataclass(frozen=True)
class InitFile:
    relative_path: Path
    content: str


def available_templates() -> list[str]:
    return [DEFAULT_TEMPLATE]


def init_project(target_dir: Path, template: str = DEFAULT_TEMPLATE, force: bool = False) -> list[Path]:
    if template != DEFAULT_TEMPLATE:
        raise InitError(f"Unknown template: {template}")

    files = _turtlebot3_gazebo_files()
    conflicts = [
        target_dir / init_file.relative_path
        for init_file in files
        if (target_dir / init_file.relative_path).exists()
    ]
    if conflicts and not force:
        conflict_list = "\n".join(f"  - {path}" for path in conflicts)
        raise InitError(f"Refusing to overwrite existing files:\n{conflict_list}\nUse --force to overwrite.")

    created: list[Path] = []
    for init_file in files:
        path = target_dir / init_file.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(init_file.content, encoding="utf-8")
        created.append(path)

    return created


def _turtlebot3_gazebo_files() -> list[InitFile]:
    return [
        InitFile(
            relative_path=Path("scenarios/smoke.yaml"),
            content=_STARTER_SCENARIO,
        ),
        InitFile(
            relative_path=Path("scenarios/worlds/empty.sdf"),
            content=_EMPTY_WORLD,
        ),
        InitFile(
            relative_path=Path(".github/workflows/nav2_scenario_tests.yaml"),
            content=_GITHUB_ACTIONS_WORKFLOW,
        ),
    ]


_STARTER_SCENARIO = """apiVersion: nav2.scenario/v1alpha1
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
    x: 0.0
    y: 0.0
    yaw: 0.0

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
      x: 0.0
      y: 0.0
      yaw: 0.0

  - send_goal:
      name: main_goal
      pose:
        x: 10.0
        y: 0.0
        yaw: 0.0

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
"""


_GITHUB_ACTIONS_WORKFLOW = """name: Nav2 Scenario Tests

on:
  pull_request:
  push:
    branches: [main]

jobs:
  scenario-test:
    runs-on: ubuntu-latest
    container:
      image: ghcr.io/nav2-scenario-runner/nav2-scenario-runner:jazzy-gazebo
    steps:
      - uses: actions/checkout@v4

      - name: Run Nav2 scenarios
        run: >
          nav2_scenario_runner run scenarios/
          --report-dir reports/
          --junit-report junit.xml
          --trace-report trace.json
          --html-report index.html
          --github-summary

      - name: Upload artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: nav2-scenario-report
          path: reports/
"""


_EMPTY_WORLD = """<?xml version="1.0" ?>
<sdf version="1.9">
  <world name="empty">
    <physics name="default_physics" type="ode">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>
    </physics>

    <scene>
      <ambient>0.4 0.4 0.4 1</ambient>
      <background>0.7 0.8 0.9 1</background>
    </scene>

    <light name="sun" type="directional">
      <cast_shadows>true</cast_shadows>
      <pose>0 0 10 0 0 0</pose>
      <diffuse>0.8 0.8 0.8 1</diffuse>
      <specular>0.2 0.2 0.2 1</specular>
      <direction>-0.5 0.1 -0.9</direction>
    </light>

    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="collision">
          <geometry>
            <plane>
              <normal>0 0 1</normal>
              <size>20 20</size>
            </plane>
          </geometry>
        </collision>
        <visual name="visual">
          <geometry>
            <plane>
              <normal>0 0 1</normal>
              <size>20 20</size>
            </plane>
          </geometry>
          <material>
            <ambient>0.8 0.8 0.8 1</ambient>
            <diffuse>0.8 0.8 0.8 1</diffuse>
          </material>
        </visual>
      </link>
    </model>
  </world>
</sdf>
"""
