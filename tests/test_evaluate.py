from __future__ import annotations

import json
from pathlib import Path

import pytest

from nav2_scenario_runner.evaluate import (
    ConfigEntry,
    MetricDirections,
    build_evaluation,
    evaluation_to_dict,
    format_evaluation_html,
    format_evaluation_markdown,
    load_entries,
    parse_entry,
)


def _report(scenarios: list[dict]) -> dict:
    return {
        "runner_version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "mode": "attach",
        "total": len(scenarios),
        "passed": sum(1 for s in scenarios if s.get("status") == "passed"),
        "failed": sum(1 for s in scenarios if s.get("status") != "passed"),
        "scenarios": scenarios,
    }


def _scenario(scenario_id: str, status: str, metrics: dict) -> dict:
    return {
        "scenario_id": scenario_id,
        "name": scenario_id,
        "path": f"{scenario_id}.yaml",
        "status": status,
        "metrics": metrics,
    }


def _two_config_entries() -> list[ConfigEntry]:
    fast = _report(
        [
            _scenario("straight", "passed", {"travel_time": 10.0, "path_length_traveled": 9.0, "recovery_count": 0}),
            _scenario("turn", "passed", {"travel_time": 20.0, "path_length_traveled": 18.0, "recovery_count": 1}),
        ]
    )
    slow = _report(
        [
            _scenario("straight", "passed", {"travel_time": 14.0, "path_length_traveled": 11.0, "recovery_count": 2}),
            _scenario("turn", "failed", {"travel_time": 30.0, "path_length_traveled": 25.0, "recovery_count": 3}),
        ]
    )
    return [
        ConfigEntry(label="fast", path="fast.json", report=fast),
        ConfigEntry(label="slow", path="slow.json", report=slow),
    ]


def test_parse_entry_splits_label_and_path():
    label, path = parse_entry("smac=reports/smac.json")
    assert label == "smac"
    assert path == Path("reports/smac.json")


def test_parse_entry_rejects_missing_separator():
    with pytest.raises(ValueError):
        parse_entry("reports/smac.json")


def test_parse_entry_rejects_empty_label():
    with pytest.raises(ValueError):
        parse_entry("=reports/smac.json")


def test_load_entries_requires_two(tmp_path: Path):
    report = tmp_path / "a.json"
    report.write_text(json.dumps(_report([])), encoding="utf-8")
    with pytest.raises(ValueError, match="at least two"):
        load_entries([("a", report)])


def test_load_entries_rejects_duplicate_labels(tmp_path: Path):
    report = tmp_path / "a.json"
    report.write_text(json.dumps(_report([])), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        load_entries([("a", report), ("a", report)])


def test_build_evaluation_ranks_better_config_first():
    evaluation = build_evaluation(_two_config_entries())
    assert [c.label for c in evaluation.configs] == ["fast", "slow"]
    assert evaluation.configs[0].rank == 1
    # fast passes both, slow passes one.
    assert evaluation.configs[0].pass_rate == 1.0
    assert evaluation.configs[1].pass_rate == 0.5


def test_build_evaluation_scores_best_config_higher():
    evaluation = build_evaluation(_two_config_entries())
    fast, slow = evaluation.configs
    # fast wins every lower-is-better metric, so it should score full marks.
    assert fast.composite == pytest.approx(1.0)
    assert slow.composite == pytest.approx(0.0)
    assert fast.wins > slow.wins


def test_normalization_marks_best_cell():
    evaluation = build_evaluation(_two_config_entries())
    straight = next(row for row in evaluation.rows if row.scenario_id == "straight")
    travel = straight.cells["travel_time"]
    assert travel["fast"].is_best is True
    assert travel["slow"].is_best is False


def test_metric_direction_override_flips_winner():
    directions = MetricDirections()
    directions.lower_is_better.discard("travel_time")
    directions.higher_is_better.add("travel_time")
    # Use only travel_time by stripping other metrics.
    entries = _two_config_entries()
    for entry in entries:
        for scenario in entry.report["scenarios"]:
            scenario["metrics"] = {"travel_time": scenario["metrics"]["travel_time"]}
            scenario["status"] = "passed"
    evaluation = build_evaluation(entries, directions)
    # Higher travel_time now wins -> slow should lead.
    assert evaluation.configs[0].label == "slow"


def test_evaluation_to_dict_shape():
    evaluation = build_evaluation(_two_config_entries())
    data = evaluation_to_dict(evaluation)
    assert data["scenario_count"] == 2
    assert data["leaderboard"][0]["label"] == "fast"
    assert data["leaderboard"][0]["rank"] == 1
    assert "travel_time" in data["metrics"]


def test_markdown_has_leaderboard_and_bolds_best():
    text = format_evaluation_markdown(build_evaluation(_two_config_entries()))
    assert "# Nav2 Evaluation" in text
    assert "Leaderboard" in text
    assert "**10**" in text  # fast's best travel_time bolded


def test_html_renders_dashboard_sections():
    entries = _two_config_entries()
    # Give one scenario a trajectory so the overlay section renders.
    entries[0].report["scenarios"][0]["metrics"]["trajectory"] = [
        {"x": 0.0, "y": 0.0},
        {"x": 1.0, "y": 0.5},
        {"x": 2.0, "y": 0.0},
    ]
    entries[1].report["scenarios"][0]["metrics"]["trajectory"] = [
        {"x": 0.0, "y": 0.0},
        {"x": 1.0, "y": -0.5},
        {"x": 2.0, "y": 0.0},
    ]
    html = format_evaluation_html(build_evaluation(entries))
    assert "<title>Nav2 Evaluation</title>" in html
    assert "Leaderboard" in html
    assert "Metric Comparison" in html
    assert "Trajectory Overlay" in html
    assert "<polyline" in html
    assert "fast" in html and "slow" in html


def test_absent_scenario_handled():
    entries = _two_config_entries()
    # Add a scenario only the first config ran.
    entries[0].report["scenarios"].append(
        _scenario("extra", "passed", {"travel_time": 5.0})
    )
    evaluation = build_evaluation(entries)
    assert "extra" in evaluation.scenario_ids
    extra = next(row for row in evaluation.rows if row.scenario_id == "extra")
    assert extra.statuses["slow"] == "absent"
    # slow has no value -> not best, fast is sole value so not counted as a win.
    assert extra.cells["travel_time"]["slow"].value is None
