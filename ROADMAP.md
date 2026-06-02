# Roadmap

## v0.1: First Green Scenario

Scope:

- CLI `run`
- YAML parser
- schema validation
- `set_initial_pose`
- `send_goal`
- `expect_goal_reached`
- console report
- JSON report
- attach mode or minimal launch-all mode

Success condition:

- A roughly 10-line YAML scenario can pass a Nav2 goal test.

## v0.2: CI-Ready Smoke Testing

Scope:

- directory execution
- tags
- JUnit XML
- GitHub Actions template
- Docker image
- artifact directory
- 3 headless Gazebo Sim example scenarios

Success condition:

- A new user can follow the README and get green GitHub Actions results.

## v0.3: Metrics and Regression Core

Scope:

- metric collectors
- traveled path length
- recovery count
- replanning count
- baseline compare
- absolute threshold and baseline delta

Success condition:

- A pull request can show metric deltas against main branch baseline.

## v0.4: Dynamic Events and Robot Profiles

Scope:

- event bus
- `on_event`
- `parallel`
- dynamic obstacle support
- robot profile schema
- diff drive, Ackermann, and omni profile semantics
- timeline artifact

Success condition:

- A scenario can spawn an obstacle during navigation and measure replanning or recovery changes.

## v0.5: Multi-Simulator Foundation

Scope:

- simulator adapter capability model
- Gazebo Classic adapter
- Webots beta adapter
- simulator metadata in reports

Success condition:

- The same simple-goal scenario intent can run on Gazebo Sim and Webots.

## v0.6: Plugin SDK

Scope:

- action plugin SDK
- assertion plugin SDK
- metric plugin SDK
- reporter plugin SDK
- simulator adapter skeleton
- plugin template and docs

Success condition:

- A third party can add a custom action without changing core.

## v0.7: Baseline and Flake Management

Scope:

- retry classification
- `flaky_pass`
- baseline storage
- statistical thresholds
- GitHub artifact baseline comparison
- PR annotation

Success condition:

- Retry pass is classified as flaky rather than ordinary pass.

## v0.8: Scenario Library and Parameter Matrix

Scope:

- template library
- fixtures
- parameter sweep
- scenario matrix
- planner/controller comparison report

Success condition:

- The same scenario can compare planner A/B using path length and travel time.

## v0.9: v1 Release Candidate

Scope:

- DSL v1 freeze candidate
- report schema release candidate
- plugin API release candidate
- documentation completion
- migration guide
- deprecation policy

Success condition:

- Breaking changes needed for v1 are explicit and user scenarios can be migrated.

## v1.0: Stable OSS Product

Scope:

- stable DSL v1
- stable plugin API
- stable report schema
- CI templates
- support matrix
- console, JSON, JUnit, HTML, and GitHub summary reports

Success condition:

- A Nav2 user can add scenario regression testing to a GitHub repository in under 30 minutes.
- A Nav2 maintainer can reproduce a navigation regression from CI artifacts.
- A robotics company can version-control scenario YAML as part of its release gate.
