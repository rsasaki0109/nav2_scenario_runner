# Security

`nav2_scenario_runner` scenarios are intended to run in developer machines and CI environments with access to ROS 2 graphs, simulators, and artifacts. Treat scenario execution as a privileged test operation.

Security design goals:

- Scenario YAML must not execute arbitrary code.
- Template expansion must not execute shell commands.
- Plugins must be explicitly installed.
- CI should support plugin allowlists.
- Reports must not leak secrets.
- Captured environment variables must mask sensitive names and values.

To report a security issue, open a private advisory once the repository hosting configuration supports it. Until then, contact the maintainers privately through the project owner channel.
