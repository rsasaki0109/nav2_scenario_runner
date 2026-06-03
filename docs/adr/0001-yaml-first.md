# ADR 0001: YAML-First, Python-Optional

Status: proposed

## Context

The project aims to provide a Playwright/Cypress-like user experience for Nav2 scenario tests. The main user should be able to review scenarios in pull requests and run them in CI without writing test code.

## Decision

The primary user interface is YAML. A Python API may be added later, but the first stable product surface is the CLI plus YAML DSL.

## Consequences

- Scenarios are easy to diff, review, and template.
- The CLI experience remains central.
- The DSL must be carefully versioned.
- Escape hatches are still needed for low-level ROS 2 operations.
