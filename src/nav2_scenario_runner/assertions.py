from __future__ import annotations

from typing import Any

from .runner import AssertionRunResult, MetricValue
from .scenario import Scenario


PASS_STATUSES = {"passed", "warning", "skipped"}


def evaluate_assertions(
    scenario: Scenario,
    metrics: dict[str, MetricValue],
    duration_seconds: float,
) -> list[AssertionRunResult]:
    raw_assertions = scenario.document.get("assertions") or []
    if not isinstance(raw_assertions, list):
        return [
            AssertionRunResult(
                index=0,
                kind="<assertions>",
                status="failed",
                message="Scenario assertions must be a list.",
            )
        ]

    results: list[AssertionRunResult] = []
    for index, raw_assertion in enumerate(raw_assertions):
        if not isinstance(raw_assertion, dict) or len(raw_assertion) != 1:
            results.append(
                AssertionRunResult(
                    index=index,
                    kind="<invalid>",
                    status="failed",
                    message=f"Assertion {index} must contain exactly one assertion.",
                )
            )
            continue

        kind, params = next(iter(raw_assertion.items()))
        if params is None:
            params = {}
        if not isinstance(params, dict):
            results.append(
                AssertionRunResult(
                    index=index,
                    kind=str(kind),
                    status="failed",
                    message=f"Assertion parameters for {kind} must be a mapping.",
                )
            )
            continue

        results.append(_evaluate_one(index, str(kind), params, metrics, duration_seconds))

    return results


def assertion_results_passed(assertions: list[AssertionRunResult]) -> bool:
    return all(result.status in PASS_STATUSES for result in assertions)


def first_failed_assertion(assertions: list[AssertionRunResult]) -> AssertionRunResult | None:
    for assertion in assertions:
        if assertion.status not in PASS_STATUSES:
            return assertion
    return None


def _evaluate_one(
    index: int,
    kind: str,
    params: dict[str, Any],
    metrics: dict[str, MetricValue],
    duration_seconds: float,
) -> AssertionRunResult:
    severity = str(params.get("severity", "error"))

    if kind == "goal_reached":
        reached = metrics.get("goal_reached")
        if reached is True:
            return _passed(index, kind, "Goal reached.", severity, metric="goal_reached", actual=True, expected=True)
        return _threshold_failed(
            index,
            kind,
            f"Goal was not reached; metric goal_reached={reached!r}.",
            severity,
            metric="goal_reached",
            actual=reached,
            expected=True,
        )

    if kind == "collision_free":
        if "collision_free" not in metrics:
            return AssertionRunResult(
                index=index,
                kind=kind,
                status="skipped",
                message="Required metric is not available: collision_free",
                severity=severity,
                metric="collision_free",
            )
        collision_free = metrics.get("collision_free")
        collision_count = metrics.get("collision_count")
        if collision_free is True:
            return _passed(
                index,
                kind,
                "No collisions detected.",
                severity,
                metric="collision_free",
                actual=True,
                expected=True,
            )
        return _threshold_failed(
            index,
            kind,
            f"Collision detected; collision_count={collision_count!r}.",
            severity,
            metric="collision_free",
            actual=collision_free,
            expected=True,
        )

    if kind == "travel_time":
        return _evaluate_max_metric(index, kind, params, metrics, metric="travel_time", severity=severity)

    if kind in {"path_length", "path_length_traveled"}:
        if "path_length_traveled" not in metrics:
            return AssertionRunResult(
                index=index,
                kind=kind,
                status="skipped",
                message="Required metric is not available: path_length_traveled",
                severity=severity,
                metric="path_length_traveled",
            )
        return _evaluate_max_metric(
            index,
            kind,
            params,
            metrics,
            metric="path_length_traveled",
            severity=severity,
        )

    if kind == "replanning_count":
        if "replanning_count" not in metrics:
            return AssertionRunResult(
                index=index,
                kind=kind,
                status="skipped",
                message="Required metric is not available: replanning_count",
                severity=severity,
                metric="replanning_count",
            )
        return _evaluate_max_metric(
            index,
            kind,
            params,
            metrics,
            metric="replanning_count",
            severity=severity,
        )

    if kind == "recovery_count":
        if "recovery_count" not in metrics:
            return AssertionRunResult(
                index=index,
                kind=kind,
                status="skipped",
                message="Required metric is not available: recovery_count",
                severity=severity,
                metric="recovery_count",
            )
        return _evaluate_max_metric(
            index,
            kind,
            params,
            metrics,
            metric="recovery_count",
            severity=severity,
        )

    if kind == "timeout":
        return _evaluate_max_value(
            index,
            kind,
            actual=duration_seconds,
            expected=params.get("max"),
            metric="duration_seconds",
            severity=severity,
        )

    return AssertionRunResult(
        index=index,
        kind=kind,
        status="skipped",
        message=f"Assertion is not supported by the current runner: {kind}",
        severity=severity,
    )


def _evaluate_max_metric(
    index: int,
    kind: str,
    params: dict[str, Any],
    metrics: dict[str, MetricValue],
    metric: str,
    severity: str,
) -> AssertionRunResult:
    if metric not in metrics:
        return _threshold_failed(
            index,
            kind,
            f"Required metric is not available: {metric}",
            severity,
            metric=metric,
        )
    return _evaluate_max_value(
        index=index,
        kind=kind,
        actual=metrics[metric],
        expected=params.get("max"),
        metric=metric,
        severity=severity,
    )


def _evaluate_max_value(
    index: int,
    kind: str,
    actual: MetricValue | None,
    expected: Any,
    metric: str,
    severity: str,
) -> AssertionRunResult:
    if expected is None:
        return _threshold_failed(
            index,
            kind,
            f"Assertion requires a max value: {kind}",
            severity,
            metric=metric,
            actual=actual,
        )
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return _threshold_failed(
            index,
            kind,
            f"Metric {metric} is not numeric: {actual!r}",
            severity,
            metric=metric,
            actual=actual,
            expected=expected,
        )
    try:
        expected_float = float(expected)
    except (TypeError, ValueError):
        return _threshold_failed(
            index,
            kind,
            f"Assertion max must be numeric: {expected!r}",
            severity,
            metric=metric,
            actual=actual,
            expected=expected,
        )

    if float(actual) <= expected_float:
        return _passed(
            index,
            kind,
            f"{metric}={float(actual):g} is within max {expected_float:g}.",
            severity,
            metric=metric,
            actual=float(actual),
            expected=expected_float,
        )

    return _threshold_failed(
        index,
        kind,
        f"{metric}={float(actual):g} exceeds max {expected_float:g}.",
        severity,
        metric=metric,
        actual=float(actual),
        expected=expected_float,
    )


def _passed(
    index: int,
    kind: str,
    message: str,
    severity: str,
    metric: str | None = None,
    actual: MetricValue | None = None,
    expected: MetricValue | None = None,
) -> AssertionRunResult:
    return AssertionRunResult(
        index=index,
        kind=kind,
        status="passed",
        message=message,
        severity=severity,
        metric=metric,
        actual=actual,
        expected=expected,
    )


def _threshold_failed(
    index: int,
    kind: str,
    message: str,
    severity: str,
    metric: str | None = None,
    actual: MetricValue | None = None,
    expected: MetricValue | None = None,
) -> AssertionRunResult:
    return AssertionRunResult(
        index=index,
        kind=kind,
        status="warning" if severity == "warning" else "failed",
        message=message,
        severity=severity,
        metric=metric,
        actual=actual,
        expected=expected,
    )
