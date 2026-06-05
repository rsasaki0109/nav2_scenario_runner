"""Unit tests for community benchmark submission validation and review comments."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nav2_scenario_runner.replay import load_map
from nav2_scenario_runner.submission import (
    CORE_SCENARIO_IDS,
    REVIEW_MARKER,
    build_review_comment,
    validate_submission,
)

BENCH = Path(__file__).resolve().parents[1] / "examples" / "benchmark"
WAREHOUSE = BENCH / "maps" / "warehouse.yaml"


def _report(scenario_ids, *, metrics=True, trajectory=None):
    scenarios = []
    for sid in scenario_ids:
        scenario = {"scenario_id": sid, "name": sid, "status": "passed", "metrics": {}}
        if metrics:
            scenario["metrics"]["travel_time"] = 9.0
        if trajectory is not None:
            scenario["metrics"]["trajectory"] = trajectory
        scenarios.append(scenario)
    return {
        "runner_version": "0",
        "generated_at": "2026-01-01T00:00:00Z",
        "mode": "gazebo-sim",
        "total": len(scenarios),
        "passed": len(scenarios),
        "failed": 0,
        "scenarios": scenarios,
    }


def test_valid_submission_passes():
    report = _report(CORE_SCENARIO_IDS)
    check = validate_submission("acme-smac-tuned", report)
    assert check.ok
    assert not check.errors
    assert set(check.scenario_ids) == set(CORE_SCENARIO_IDS)


def test_committed_example_submission_is_valid():
    report = json.loads((BENCH / "submissions" / "community-dwb.json").read_text(encoding="utf-8"))
    map_image = load_map(WAREHOUSE)
    check = validate_submission("community-dwb", report, map_image=map_image)
    assert check.ok, check.errors
    assert check.trajectory_scenarios >= 1


def test_missing_core_scenarios_is_error():
    report = _report(["straight_line"])  # missing two cores
    check = validate_submission("partial", report)
    assert not check.ok
    assert any("Missing core scenario" in error for error in check.errors)


def test_non_kebab_label_is_error():
    report = _report(CORE_SCENARIO_IDS)
    check = validate_submission("Acme_SMAC", report)
    assert not check.ok
    assert any("kebab-case" in error for error in check.errors)


def test_duplicate_label_is_error():
    report = _report(CORE_SCENARIO_IDS)
    check = validate_submission("smac", report, existing_labels={"smac", "navfn"})
    assert not check.ok
    assert any("collides" in error for error in check.errors)


def test_out_of_bounds_trajectory_is_error():
    report = _report(CORE_SCENARIO_IDS, trajectory=[{"x": 0.0, "y": 0.0}, {"x": 9999.0, "y": 9999.0}])
    check = validate_submission("runaway", report, map_image=load_map(WAREHOUSE))
    assert not check.ok
    assert any("outside the warehouse map bounds" in error for error in check.errors)


def test_missing_metrics_is_warning_not_error():
    report = _report(CORE_SCENARIO_IDS, metrics=False)
    check = validate_submission("no-metrics", report)
    assert check.ok  # warning only
    assert any("No numeric metrics" in warning for warning in check.warnings)


def test_malformed_report_is_error():
    check = validate_submission("garbage", {"not": "a report"})
    assert not check.ok
    assert any("scenarios" in error for error in check.errors)


def test_review_comment_all_valid_has_marker_and_preview():
    checks = [validate_submission("acme", _report(CORE_SCENARIO_IDS))]
    leaderboard = [
        {"rank": 1, "label": "acme", "score": 88.0, "passed": 3, "total": 3, "wins": 5},
        {"rank": 2, "label": "smac", "score": 70.0, "passed": 3, "total": 3, "wins": 4},
    ]
    body = build_review_comment(checks, leaderboard=leaderboard, submitted_labels={"acme"})
    assert body.startswith(REVIEW_MARKER)
    assert "All 1 submission(s) valid" in body
    assert "Leaderboard preview" in body
    assert "**acme** ⬅️ your entry" in body


def test_review_comment_with_failure_skips_preview():
    checks = [validate_submission("Bad_One", _report(["straight_line"]))]
    leaderboard = [{"rank": 1, "label": "x", "score": 1.0, "passed": 1, "total": 1, "wins": 0}]
    body = build_review_comment(checks, leaderboard=leaderboard, submitted_labels=set())
    assert "need changes" in body
    assert "Leaderboard preview" not in body
    assert "problem(s) must be fixed" in body


def test_review_comment_requires_checks():
    with pytest.raises(ValueError):
        build_review_comment([])
