# Plugin Authoring

The project should become plugin-first, but the SDK should not be frozen too early. v0.1 through v0.3 should collect real scenarios and implementation pressure before stabilizing external contracts.

## Plugin Types

| Plugin type | Purpose |
|---|---|
| Action plugin | Add custom YAML actions |
| Assertion plugin | Add custom expectations |
| Metric plugin | Collect custom metrics |
| Simulator adapter plugin | Integrate new simulators |
| Robot profile plugin | Add robot families |
| Reporter plugin | Emit custom reports |
| Launcher plugin | Integrate custom launch systems |
| Fixture plugin | Provide scenario fixture libraries |

## Contract

Each plugin should provide:

- name
- version
- DSL schema
- capabilities
- dependencies
- initialize hook
- execute, observe, or evaluate hook
- artifacts
- cleanup hook

This file describes the intended boundary, not a stable SDK.

## Action Plugin Example

Scenario YAML:

```yaml
- warehouse_spawn_forklift:
    name: forklift_1
    route: aisle_3_crossing
    speed: 1.2
```

Plugin responsibilities:

- provide schema
- require simulator capabilities
- issue low-level instructions through the simulator adapter
- emit events
- add forklift trajectory markers to artifacts

## Assertion Plugin Example

```yaml
- expect_no_blocking_near_goal:
    radius: 1.0
    duration: 5.0
```

Plugin responsibilities:

- observe robot pose
- detect prolonged stopping near the goal
- mark the failure on the timeline

## Distribution

Built-in plugins:

- Nav2 actions
- common assertions
- common metrics
- JSON, JUnit, and HTML reporters
- Gazebo Sim adapter

Official plugins:

- Gazebo Classic
- Webots
- Isaac Sim
- RMF
- TurtleBot3 fixtures

Community plugins:

- custom warehouse simulators
- proprietary robot profiles
- enterprise reporting

## Stability

| Phase | API stability |
|---|---|
| v0.1-v0.3 | Internal only |
| v0.4 | Experimental plugin SDK |
| v0.6 | Beta plugin SDK |
| v1.0 | Stable plugin API |

## Security

- Scenario YAML must not execute arbitrary code.
- Template expansion must not execute shell commands.
- Plugins must be explicitly installed.
- CI should support plugin allowlists.
- Reports must not leak secrets.
- Environment dumps must mask sensitive values.
