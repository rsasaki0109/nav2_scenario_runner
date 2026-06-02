# Contributing

This repository is in planning scaffold state. Contributions should focus on tightening the architecture, validating the DSL against real Nav2 workflows, and creating small executable slices.

Good first contribution areas:

- scenario examples
- DSL schema validation improvements
- metric definitions
- report format examples
- simulator adapter capability review
- documentation fixes

## Development Principles

- Keep core small.
- Put simulator-specific behavior behind adapters.
- Prefer deterministic CI behavior over maximum fidelity.
- Treat metrics and reports as product features.
- Do not add arbitrary code execution to scenario YAML.

## Documentation

Design docs live under `docs/`. Architectural decisions live under `docs/adr/`.

## License

By contributing, you agree that your contribution is licensed under Apache-2.0.
