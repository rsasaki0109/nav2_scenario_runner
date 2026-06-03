# Doctor

`doctor` checks the local environment before running scenario tests.

```bash
nav2_scenario_runner doctor
nav2_scenario_runner doctor --check-ros
nav2_scenario_runner doctor --check-gazebo
nav2_scenario_runner doctor --check-ros-graph
nav2_scenario_runner doctor --json reports/doctor.json
```

Default checks:

- Python version
- required Python modules: `yaml`, `jsonschema`
- packaged v1alpha1 schema path
- optional ROS modules: `rclpy`, `action_msgs`, `geometry_msgs`, `nav2_msgs`, `nav_msgs`
- environment metadata such as `ROS_DISTRO`, `ROS_DOMAIN_ID`, and `RMW_IMPLEMENTATION`

By default, missing ROS modules are warnings because `lint`, `run --dry-run`, and `compare` do not require ROS. Use `--check-ros` before `run --mode attach` to make ROS/Nav2 modules required.

Use `--check-gazebo` before Gazebo Sim work. It requires:

- `gz` on `PATH`
- `gz sim --help` to run successfully
- `ros2` on `PATH`
- `ros2 pkg prefix ros_gz_bridge` to run successfully

Use `--check-ros-graph` before features that need an active ROS graph. It requires:

- `ros2` on `PATH`
- `ros2 node list` to run successfully
- `ros2 topic list` to run successfully
