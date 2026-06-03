from __future__ import annotations

from pathlib import Path

from nav2_scenario_runner.assertions import evaluate_assertions
from nav2_scenario_runner.scenario import Scenario


def test_evaluate_supported_assertions_pass():
    scenario = _scenario(
        [
            {"goal_reached": {}},
            {"collision_free": {}},
            {"travel_time": {"max": 10.0}},
            {"path_length": {"max": 12.0}},
            {"replanning_count": {"max": 2}},
            {"recovery_count": {"max": 0}},
            {"timeout": {"max": 20.0}},
        ]
    )

    results = evaluate_assertions(
        scenario,
        metrics={
            "goal_reached": True,
            "collision_free": True,
            "collision_count": 0,
            "travel_time": 3.0,
            "path_length_traveled": 10.0,
            "replanning_count": 1,
            "recovery_count": 0,
        },
        duration_seconds=5.0,
    )

    assert [result.status for result in results] == [
        "passed",
        "passed",
        "passed",
        "passed",
        "passed",
        "passed",
        "passed",
    ]


def test_evaluate_travel_time_failure():
    scenario = _scenario([{"travel_time": {"max": 2.0}}])

    results = evaluate_assertions(
        scenario,
        metrics={"travel_time": 3.0},
        duration_seconds=5.0,
    )

    assert results[0].status == "failed"
    assert results[0].message == "travel_time=3 exceeds max 2."


def test_evaluate_warning_severity_does_not_hard_fail():
    scenario = _scenario([{"travel_time": {"max": 2.0, "severity": "warning"}}])

    results = evaluate_assertions(
        scenario,
        metrics={"travel_time": 3.0},
        duration_seconds=5.0,
    )

    assert results[0].status == "warning"
    assert results[0].severity == "warning"


def test_unknown_assertion_is_skipped():
    scenario = _scenario([{"collision_free": {}}])

    results = evaluate_assertions(scenario, metrics={}, duration_seconds=1.0)

    assert results[0].status == "skipped"
    assert results[0].metric == "collision_free"


def test_collision_free_fails_when_collision_detected():
    scenario = _scenario([{"collision_free": {}}])

    results = evaluate_assertions(
        scenario,
        metrics={"collision_free": False, "collision_count": 2},
        duration_seconds=1.0,
    )

    assert results[0].status == "failed"
    assert results[0].message == "Collision detected; collision_count=2."


def test_path_length_skips_when_metric_missing():
    scenario = _scenario([{"path_length": {"max": 12.0}}])

    results = evaluate_assertions(scenario, metrics={}, duration_seconds=1.0)

    assert results[0].status == "skipped"
    assert results[0].metric == "path_length_traveled"


def test_path_length_fails_when_above_max():
    scenario = _scenario([{"path_length": {"max": 8.0}}])

    results = evaluate_assertions(
        scenario,
        metrics={"path_length_traveled": 10.0},
        duration_seconds=1.0,
    )

    assert results[0].status == "failed"
    assert results[0].message == "path_length_traveled=10 exceeds max 8."


def test_replanning_count_skips_when_metric_missing():
    scenario = _scenario([{"replanning_count": {"max": 3}}])

    results = evaluate_assertions(scenario, metrics={}, duration_seconds=1.0)

    assert results[0].status == "skipped"
    assert results[0].metric == "replanning_count"


def test_replanning_count_fails_when_above_max():
    scenario = _scenario([{"replanning_count": {"max": 0}}])

    results = evaluate_assertions(
        scenario,
        metrics={"replanning_count": 1},
        duration_seconds=1.0,
    )

    assert results[0].status == "failed"
    assert results[0].message == "replanning_count=1 exceeds max 0."


def test_recovery_count_skips_when_metric_missing():
    scenario = _scenario([{"recovery_count": {"max": 1}}])

    results = evaluate_assertions(scenario, metrics={}, duration_seconds=1.0)

    assert results[0].status == "skipped"
    assert results[0].metric == "recovery_count"


def test_recovery_count_fails_when_above_max():
    scenario = _scenario([{"recovery_count": {"max": 1}}])

    results = evaluate_assertions(
        scenario,
        metrics={"recovery_count": 2},
        duration_seconds=1.0,
    )

    assert results[0].status == "failed"
    assert results[0].message == "recovery_count=2 exceeds max 1."


def _scenario(assertions):
    return Scenario(
        path=Path("assertions.yaml"),
        document={
            "apiVersion": "nav2.scenario/v1alpha1",
            "kind": "Scenario",
            "metadata": {"name": "assertions"},
            "assertions": assertions,
        },
        scenario_id="assertions",
        name="assertions",
        tags=set(),
        step_count=0,
        assertion_count=len(assertions),
    )
