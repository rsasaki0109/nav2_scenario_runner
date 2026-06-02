from __future__ import annotations

import json

from nav2_scenario_runner.compare import (
    MetricRule,
    compare_reports,
    format_compare_markdown,
    parse_metric_rule,
)


def test_compare_detects_status_regression():
    baseline = _report(_scenario("straight_line_goal", "passed"))
    current = _report(_scenario("straight_line_goal", "failed"))

    report = compare_reports(
        current=current,
        baseline=baseline,
        current_path=_path("current.json"),
        baseline_path=_path("baseline.json"),
        rules=[],
    )

    assert not report.passed
    assert report.issues[0].kind == "status_regression"
    assert report.issues[0].scenario_id == "straight_line_goal"


def test_compare_detects_missing_scenario_by_default():
    baseline = _report(_scenario("straight_line_goal", "passed"))
    current = _report()

    report = compare_reports(
        current=current,
        baseline=baseline,
        current_path=_path("current.json"),
        baseline_path=_path("baseline.json"),
        rules=[],
    )

    assert not report.passed
    assert report.missing_scenarios == ["straight_line_goal"]
    assert report.issues[0].kind == "missing_scenario"


def test_compare_can_allow_missing_scenario():
    baseline = _report(_scenario("straight_line_goal", "passed"))
    current = _report()

    report = compare_reports(
        current=current,
        baseline=baseline,
        current_path=_path("current.json"),
        baseline_path=_path("baseline.json"),
        rules=[],
        allow_missing=True,
    )

    assert report.passed
    assert report.missing_scenarios == ["straight_line_goal"]
    assert report.issues == []


def test_compare_detects_metric_percent_regression():
    baseline = _report(_scenario("straight_line_goal", "passed", metrics={"path_length_traveled": 10.0}))
    current = _report(_scenario("straight_line_goal", "passed", metrics={"path_length_traveled": 12.0}))

    report = compare_reports(
        current=current,
        baseline=baseline,
        current_path=_path("current.json"),
        baseline_path=_path("baseline.json"),
        rules=[MetricRule(kind="max_increase_percent", metric="path_length_traveled", limit=10.0)],
    )

    assert not report.passed
    assert report.issues[0].kind == "metric_regression"
    assert "path_length_traveled increased" in report.issues[0].message


def test_compare_metric_delta_passes_within_limit():
    baseline = _report(_scenario("straight_line_goal", "passed", metrics={"recovery_count": 1}))
    current = _report(_scenario("straight_line_goal", "passed", metrics={"recovery_count": 2}))

    report = compare_reports(
        current=current,
        baseline=baseline,
        current_path=_path("current.json"),
        baseline_path=_path("baseline.json"),
        rules=[MetricRule(kind="max_delta", metric="recovery_count", limit=1.0)],
    )

    assert report.passed


def test_compare_reads_top_level_duration_metric():
    baseline = _report(_scenario("straight_line_goal", "passed", duration_seconds=10.0))
    current = _report(_scenario("straight_line_goal", "passed", duration_seconds=12.0))

    report = compare_reports(
        current=current,
        baseline=baseline,
        current_path=_path("current.json"),
        baseline_path=_path("baseline.json"),
        rules=[MetricRule(kind="max_increase_percent", metric="duration_seconds", limit=10.0)],
    )

    assert not report.passed
    assert "duration_seconds increased" in report.issues[0].message


def test_parse_metric_rule_requires_metric_and_numeric_value():
    rule = parse_metric_rule("travel_time=15", kind="max_increase_percent")

    assert rule.metric == "travel_time"
    assert rule.limit == 15.0


def test_compare_markdown_summarizes_regressions_and_scenario_sets():
    baseline = _report(
        _scenario("straight_line_goal", "passed", metrics={"travel_time": 10.0}),
        _scenario("missing_goal", "passed"),
    )
    current = _report(
        _scenario("straight_line_goal", "passed", metrics={"travel_time": 13.0}),
        _scenario("new_goal", "passed"),
    )

    report = compare_reports(
        current=current,
        baseline=baseline,
        current_path=_path("current.json"),
        baseline_path=_path("baseline.json"),
        rules=[MetricRule(kind="max_increase_percent", metric="travel_time", limit=20.0)],
    )

    markdown = format_compare_markdown(report)

    assert "# Nav2 Scenario Regression" in markdown
    assert "- Result: `FAIL`" in markdown
    assert "| straight_line_goal | metric_regression | travel_time increased" in markdown
    assert "travel_time:max_increase_percent=20" in markdown
    assert "## New Scenarios" in markdown
    assert "`new_goal`" in markdown
    assert "## Missing Scenarios" in markdown
    assert "`missing_goal`" in markdown


def _report(*scenarios):
    return {
        "runner_version": "0.1.0",
        "generated_at": "2026-06-03T00:00:00+00:00",
        "mode": "fake",
        "total": len(scenarios),
        "passed": sum(1 for scenario in scenarios if scenario["status"] == "passed"),
        "failed": sum(1 for scenario in scenarios if scenario["status"] != "passed"),
        "scenarios": list(scenarios),
    }


def _scenario(scenario_id: str, status: str, metrics=None, duration_seconds=0.0):
    return {
        "scenario_id": scenario_id,
        "name": scenario_id,
        "path": f"{scenario_id}.yaml",
        "tags": [],
        "status": status,
        "step_count": 1,
        "assertion_count": 0,
        "duration_seconds": duration_seconds,
        "failure_reason": None,
        "steps": [],
        "metrics": metrics or {},
    }


def _path(name: str):
    from pathlib import Path

    return Path(name)
