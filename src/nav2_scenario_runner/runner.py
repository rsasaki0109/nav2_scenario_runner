from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from . import __version__
from .scenario import Scenario


MetricValue = Any


@dataclass(frozen=True)
class StepRunResult:
    index: int
    kind: str
    status: str
    duration_seconds: float
    failure_reason: str | None = None
    time_offset_seconds: float | None = None


@dataclass(frozen=True)
class AssertionRunResult:
    index: int
    kind: str
    status: str
    message: str
    severity: str = "error"
    metric: str | None = None
    actual: MetricValue | None = None
    expected: MetricValue | None = None


@dataclass(frozen=True)
class ScenarioRunResult:
    scenario_id: str
    name: str
    path: str
    tags: list[str]
    status: str
    step_count: int
    assertion_count: int
    duration_seconds: float
    failure_reason: str | None = None
    steps: list[StepRunResult] | None = None
    assertions: list[AssertionRunResult] | None = None
    metrics: dict[str, MetricValue] | None = None


@dataclass(frozen=True)
class RunReport:
    runner_version: str
    generated_at: str
    mode: str
    total: int
    passed: int
    failed: int
    scenarios: list[ScenarioRunResult]


def dry_run(scenarios: list[Scenario]) -> RunReport:
    results = [
        ScenarioRunResult(
            scenario_id=scenario.scenario_id,
            name=scenario.name,
            path=str(scenario.path),
            tags=sorted(scenario.tags),
            status="dry_run_passed",
            step_count=scenario.step_count,
            assertion_count=scenario.assertion_count,
            duration_seconds=0.0,
            failure_reason=None,
            steps=[],
            assertions=[],
            metrics={},
        )
        for scenario in scenarios
    ]
    return RunReport(
        runner_version=__version__,
        generated_at=datetime.now(timezone.utc).isoformat(),
        mode="dry_run",
        total=len(results),
        passed=len(results),
        failed=0,
        scenarios=results,
    )


def run_with_backend_factory(
    scenarios: list[Scenario],
    mode: str,
    backend_factory: Callable[[Scenario], object],
) -> RunReport:
    from .execution import ExecutionEngine

    results: list[ScenarioRunResult] = []
    for scenario in scenarios:
        backend = backend_factory(scenario)
        results.append(ExecutionEngine(backend).run(scenario))

    failed = sum(1 for result in results if result.status != "passed")
    return RunReport(
        runner_version=__version__,
        generated_at=datetime.now(timezone.utc).isoformat(),
        mode=mode,
        total=len(results),
        passed=len(results) - failed,
        failed=failed,
        scenarios=results,
    )
