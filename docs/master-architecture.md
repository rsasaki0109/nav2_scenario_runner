# Master Architecture Design

Design status: v0.1 planning draft

Target users: Nav2 users, Nav2 maintainers, AMR developers, robotics system integrators, researchers, and CI/CD platform owners.

Non-goals: a general AV validation standard, a custom simulator, or a replacement implementation for Nav2.

## Executive Summary

`nav2_scenario_runner` is an E2E scenario test runner for Nav2-based AMR and mobile robot development.

Web E2E tools such as Playwright and Cypress combine browser actions, waiting, assertions, tracing, parallel execution, and CI reporting into one developer experience. `nav2_scenario_runner` applies the same product pattern to Nav2:

- set initial pose
- send goals
- inject obstacles, people, door events, and route changes
- measure metrics
- evaluate regressions
- publish CI reports and failure artifacts

The project is not "Scenario Simulator for Nav2". It is a daily test runner for Nav2 users. The central value is readable YAML, reproducible execution, Nav2-aware metrics, and reports that explain failures quickly.

## Vision

Robot navigation tests should be as easy to write, run, review, and regress as web end-to-end tests.

The intended user experience is:

```bash
nav2_scenario_runner run scenarios/
```

One command should:

- validate scenario YAML
- launch or attach to ROS 2, Nav2, and a simulator
- set initial pose
- send navigation goals
- inject events and dynamic entities
- monitor Nav2 results
- evaluate collision-free, timeout, path length, travel time, recovery count, and replanning count
- emit JUnit XML, JSON, HTML, Markdown, GitHub annotations, traces, and optional rosbag artifacts
- decide pass/fail in CI

## Product Category

Recommended category:

- Nav2 E2E Scenario Testing Framework
- Scenario-as-Code Test Runner for Nav2

Avoid:

- simulator for Nav2
- Scenario Simulator for Nav2
- OpenSCENARIO for ROS
- launch_testing wrapper

## Design Principles

### Thin Core, Thick Ecosystem

The core owns the contracts and the developer experience. Details that vary by simulator, robot, deployment, or organization belong behind adapters or plugins.

Core responsibilities:

- DSL parsing
- schema validation
- execution lifecycle
- event bus
- plugin registry
- metric aggregation
- report generation
- CLI UX
- compatibility contracts

Out of scope for core:

- simulator-specific APIs
- URDF, SDF, USD, or WBT asset ownership
- every actor behavior
- Nav2 internals
- a full AV/ADAS scenario standard

### Adapter Everything

Simulator, robot, Nav2 connection, metrics, reporters, launchers, and fixtures should all be adapter/plugin boundaries.

### Metrics Are First-Class

The test is not just a sequence of steps. The point is to verify navigation behavior and regressions.

### CI Is A Product Surface

Docker images, JUnit, GitHub summaries, artifact directories, deterministic seeds, and failure bundles are part of the product.

### Determinism Over Fidelity

For v1, reliable repeatable tests matter more than maximum simulator fidelity.

## Component Model

```text
CLI
  -> Scenario Loader
  -> Schema Validator
  -> Test Planner
  -> Execution Engine
       -> Event Bus
       -> Nav2 Adapter
       -> Simulator Adapter
       -> Robot Profile
       -> Metrics Framework
       -> Artifact Manager
  -> Reporter
```

## Core Components

### CLI Layer

Commands:

- `run`
- `lint`
- `list`
- `report`
- `compare`
- `init`
- `doctor`
- `plugins`
- `record` in a later phase
- `explain` in a later phase

Example commands:

```bash
nav2_scenario_runner run scenario.yaml
nav2_scenario_runner run scenarios/ --tag smoke
nav2_scenario_runner run scenarios/ --sim gazebo --headless
nav2_scenario_runner compare reports/current.json --baseline reports/main.json
nav2_scenario_runner lint scenarios/
nav2_scenario_runner doctor --check-gazebo
```

### Scenario Loader

Responsibilities:

- YAML loading
- include resolution
- template expansion
- variable expansion
- environment variable injection
- suite directory resolution
- scenario ID generation
- source map generation

Source maps are required so failures can point to the YAML file and line that caused them.

### Schema Validator

Responsibilities:

- DSL version checks
- required field checks
- unknown key detection
- type validation
- plugin schema validation
- simulator capability validation
- robot profile compatibility validation

Example validation failure:

```text
Scenario requires action spawn_actor(type=person).
Selected simulator adapter webots does not declare capability actor.trajectory.v1.
```

### Test Planner

Responsibilities:

- scenario discovery
- tag filtering
- matrix expansion
- parameter sweeps
- retry policy
- sharding
- dependency ordering
- fail-fast decisions

### Execution Engine

Responsibilities:

- scenario lifecycle management
- step execution
- timeout management
- event bus orchestration
- hard and soft assertion handling
- cleanup guarantees
- artifact hooks

The execution engine is not a simple loop. Actions emit events; metrics and assertions subscribe to events; reporters record events; failure policies react to events.

### Nav2 Adapter

Responsibilities:

- Nav2 lifecycle readiness
- initial pose publication
- goal submission
- future waypoint, follow-path, docking, and behavior tree integrations
- costmap clear services
- planner and controller selector operations
- action feedback and result monitoring
- Nav2-specific event emission

The runner observes and operates Nav2 through ROS 2 actions, services, topics, TF, lifecycle state, and logs. It should not reimplement Nav2 behavior.

### Simulator Adapter

Responsibilities:

- simulator launch and shutdown
- world loading
- reset
- pause, resume, and step
- entity spawn and delete
- actor spawn and movement
- door open and close
- collision/contact collection
- screenshots and video when available
- simulation clock synchronization
- capability declaration

### Robot Profile

Responsibilities:

- kinematics
- footprint
- frames
- topics
- velocity limits
- sensor topics
- base command topic
- expected action namespace
- collision model
- metric normalization

### Metrics Framework

Responsibilities:

- raw telemetry collection
- metric aggregation
- assertion evaluation
- baseline comparison
- statistical summaries
- artifact generation

### Reporter

Responsibilities:

- console summary
- JUnit XML
- JSON
- HTML
- Markdown summary
- GitHub annotation or summary
- trace timeline
- metric trend

## Dependency Model

Required runtime dependencies:

- ROS 2 runtime
- Nav2 message, action, and service interfaces
- Python runtime
- YAML parser
- JSON schema validation
- report generation
- `rclpy` ROS client layer

Optional dependencies:

| Dependency | Purpose |
|---|---|
| Gazebo Sim adapter | Primary OSS simulator target |
| Gazebo Classic adapter | Legacy projects and existing Nav2 tests |
| Isaac Sim adapter | GPU, photorealistic, digital twin workflows |
| Webots adapter | CPU-friendly education and research workflows |
| RMF integration plugin | Doors, lifts, crowds, and building events |
| rosbag2 plugin | Failure replay |
| HTML report plugin | Developer experience and CI artifacts |
| GitHub reporter | Pull request annotation and summary |

## Data Flow

1. User runs `nav2_scenario_runner run scenarios/`.
2. Scenario discovery builds a suite index.
3. Validation checks DSL schema, plugin schemas, and adapter capabilities.
4. Environment preparation sets ROS isolation and log/artifact directories.
5. Synchronization waits for `/clock`, TF, Nav2 lifecycle active, map, costmaps, and robot pose.
6. Execution runs steps sequentially, in parallel, or event-driven depending on DSL.
7. Metrics collection observes odom, path, TF, action feedback, contacts, costmaps, and logs.
8. Evaluation applies hard assertions, soft assertions, and baseline regression rules.
9. Teardown cancels goals, stops actors, resets or shuts down simulator processes, and collects logs.
10. Reporting writes console, JUnit, JSON, HTML, traces, and artifacts.

## Execution Modes

### Launch-All Mode

The runner launches simulator, robot, and Nav2.

```bash
nav2_scenario_runner run scenario.yaml --mode launch
```

Use for CI, reproducible regression, and OSS examples.

### Attach Mode

The runner connects to an already-running ROS graph.

```bash
nav2_scenario_runner run scenario.yaml --mode attach
```

Use for local debugging, real robots, and external launch systems.

### Hybrid Mode

The runner launches some components and attaches to others. This is useful for heavy simulators such as Isaac Sim or internal company launch systems.

## Scenario State

Scenario states:

- pending
- running
- passed
- failed
- skipped
- timeout
- cancelled

Step states:

- pending
- ready
- running
- waiting
- passed
- failed
- skipped
- timeout
- cancelled

Each step records:

- ID
- source location
- start time
- end time
- sim time
- status
- emitted events
- artifacts
- failure reason

## Event Model

Core event types:

- `scenario.started`
- `scenario.finished`
- `step.started`
- `step.finished`
- `step.failed`
- `nav2.goal.sent`
- `nav2.goal.feedback`
- `nav2.goal.succeeded`
- `nav2.goal.failed`
- `nav2.goal.canceled`
- `nav2.recovery.started`
- `nav2.recovery.finished`
- `nav2.replan.detected`
- `sim.collision`
- `sim.entity.spawned`
- `sim.entity.moved`
- `metric.threshold_exceeded`
- `timeout`
- `custom.*`

Example failure path:

```text
sim.collision
  -> collision_free assertion fails
  -> engine marks scenario failed
  -> artifact manager starts failure bundle
  -> active Nav2 goal is canceled
  -> teardown begins
```

## Test Isolation

CI isolation requirements:

- unique ROS_DOMAIN_ID per scenario when possible
- namespace isolation
- temporary log directory
- process group management
- simulator world reset
- fixed random seed
- environment capture with secret masking
- dependency version capture

## Parallel Execution

Suite-level parallelism runs scenarios in separate ROS domains:

```bash
nav2_scenario_runner run scenarios/ --workers 4
```

Scenario-level parallelism runs branches inside one scenario. v1 should prioritize suite-level parallelism because it is easier to debug and isolate.

## Simulator Strategy

Gazebo Sim is the primary v1 simulator target.

Gazebo Classic is legacy support and should live outside core.

Isaac Sim is experimental or beta, with emphasis on adapter contracts and enterprise extension.

Webots is a CPU-friendly target to grow after Gazebo Sim support is stable.

RMF integrations for doors, lifts, and crowds are optional plugins, not core features.

## Plugin Architecture

Plugin types:

- action plugin
- assertion plugin
- metric plugin
- simulator adapter plugin
- robot profile plugin
- reporter plugin
- launcher plugin
- fixture plugin

Each plugin provides:

- name
- version
- DSL schema
- capabilities
- dependencies
- initialize hook
- execute, observe, or evaluate hook
- artifacts
- cleanup hook

Plugin API stability:

| Phase | Stability |
|---|---|
| v0.1-v0.3 | Internal only |
| v0.4 | Experimental plugin SDK |
| v0.6 | Beta plugin SDK |
| v1.0 | Stable plugin API |

Security requirements:

- scenario YAML must not imply arbitrary code execution
- templates must not execute shell commands
- only explicitly installed plugins are loaded
- CI supports plugin allowlists
- reports must not leak secrets
- captured environment variables are masked

## Strategic Design Decisions

1. YAML-first, Python-optional.
2. Gazebo Sim first.
3. JUnit XML is mandatory by v0.2.
4. Collision strategy is capability-based.
5. Baseline regression belongs in core.
6. Plugin SDK waits until real usage shapes the abstraction.

## North Star

Success means:

- Nav2 pull requests include scenario regression results.
- AMR teams version maps, robot profiles, Nav2 params, and scenario YAML together.
- CI detects collisions, recovery increases, path quality regressions, and timeout regressions.
- planner and controller plugins publish scenario test evidence.
- robot developers replace manual RViz checks with repeatable Scenario-as-Code quality gates.
