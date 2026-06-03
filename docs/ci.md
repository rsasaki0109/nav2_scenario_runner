# CI/CD Strategy

CI is a first-class product surface. The runner should ship with Docker images, GitHub Actions examples, JUnit XML, JSON reports, GitHub summaries, deterministic seeds, and failure artifacts from the first useful releases.

## GitHub Actions Target UX

This repository's own CI lives at `.github/workflows/ci.yml` and runs:

- `pytest -q`
- `python -m compileall -q src tests`
- schema asset sync check
- example YAML parsing
- `nav2_scenario_runner doctor`
- `init -> lint -> run --dry-run` smoke test

Create starter files:

```bash
nav2_scenario_runner init .
nav2_scenario_runner doctor
```

This generates:

- `scenarios/smoke.yaml`
- `.github/workflows/nav2_scenario_tests.yaml`

```yaml
name: Nav2 Scenario Tests

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
```

The default report directory contains:

- `results.json`
- `junit.xml`
- `trace.json` when `--trace-report trace.json` is used
- `index.html` when `--html-report index.html` is used

`run` can write CI-facing summaries directly:

```bash
nav2_scenario_runner run scenarios/ \
  --report-dir reports/ \
  --junit-report junit.xml \
  --trace-report trace.json \
  --markdown-report summary.md \
  --html-report index.html \
  --github-summary
```

Render a console or Markdown summary from the JSON report:

```bash
nav2_scenario_runner report reports/results.json
nav2_scenario_runner report reports/results.json --format markdown --output reports/summary.md
nav2_scenario_runner report reports/results.json --format html --output reports/index.html
nav2_scenario_runner report reports/results.json --github-summary
```

`--github-summary` appends Markdown to `$GITHUB_STEP_SUMMARY` in GitHub Actions. `--format html` creates a self-contained artifact report. Use `--fail-on-failure` when the summary step itself should fail if the report contains failed scenarios.

## Test Pyramid

PR fast path:

- DSL lint
- schema validation
- no-sim dry run
- loopback or fake Nav2 smoke
- 1 to 3 headless Gazebo smoke scenarios

Nightly:

- full scenario suite
- dynamic obstacles
- parameter matrix
- multiple robot profiles
- baseline regression

Weekly:

- multi-simulator run
- optional Isaac and Webots runs
- long-running flake detection
- performance trend

## Docker Tags

Planned image families:

- `nav2-scenario-runner:jazzy-core`
- `nav2-scenario-runner:jazzy-gazebo`
- `nav2-scenario-runner:jazzy-gazebo-classic`
- `nav2-scenario-runner:jazzy-webots`
- `nav2-scenario-runner:kilted-core`
- `nav2-scenario-runner:rolling-core`

## Regression Workflow

Main branch:

1. Run scenarios.
2. Publish baseline artifact.

Pull request:

1. Run the same scenarios.
2. Compare metrics with main baseline.
3. Annotate the PR with deltas.

Current minimal comparison command:

```bash
nav2_scenario_runner compare reports/current.json \
  --baseline reports/main.json \
  --max-increase-percent travel_time=15 \
  --max-increase-percent path_length_traveled=10 \
  --max-delta recovery_count=1 \
  --output reports/compare.json \
  --markdown-output reports/compare.md \
  --github-summary
```

`--github-summary` appends the regression comparison to the same GitHub Step Summary used by `run --github-summary`.

Policy example:

```yaml
regression:
  baseline_source: github-artifact
  rules:
    travel_time:
      max_increase_percent: 15
    path_length_traveled:
      max_increase_percent: 10
    recovery_count:
      max_delta: 1
    collision_free:
      must_remain: true
```

## Flaky Test Management

Built-in features:

- fixed seed
- scenario retry
- retry classification
- failure fingerprint
- sim real-time factor tracking
- warmup phase
- quarantine tags
- nightly flake report

```yaml
retries:
  max: 2
  classify_flake: true
```

Safety-related assertions should not become ordinary passes after retry. A retry pass should be classified as `flaky_pass` and surfaced as a CI warning.
