# ADR 0002: Gazebo Sim First

Status: proposed

## Context

The runner needs one reliable simulator target for v1 examples, CI, and initial adoption. Multi-simulator support is part of the architecture, but supporting every simulator equally from day one would dilute effort.

## Decision

Gazebo Sim is the primary v1 simulator target. Gazebo Classic is legacy support. Webots is a later CPU-friendly target. Isaac Sim is experimental or external in early releases.

## Consequences

- v1 examples and CI focus on one simulator path.
- Adapter contracts still support future simulators.
- Legacy users can be served through optional plugins.
