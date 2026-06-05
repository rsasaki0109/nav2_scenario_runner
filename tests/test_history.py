from __future__ import annotations

import json
from pathlib import Path

import pytest

from nav2_scenario_runner.history import (
    append_history,
    build_trend,
    format_trend_html,
    format_trend_markdown,
    load_history,
    summarize_report,
    trend_to_dict,
)


def _report(label_metrics: dict, status: str = "passed", generated_at: str = "2026-06-05T00:00:00+00:00") -> dict:
    return {
        "runner_version": "0.1.0",
        "generated_at": generated_at,
        "mode": "attach",
        "total": 1,
        "passed": 1 if status == "passed" else 0,
        "failed": 0 if status == "passed" else 1,
        "scenarios": [
            {
                "scenario_id": "straight",
                "name": "straight",
                "path": "straight.yaml",
                "status": status,
                "metrics": label_metrics,
            }
        ],
    }


def test_summarize_report_keeps_scalar_metrics_only():
    report = _report({"travel_time": 12.0, "collision_free": True, "trajectory": [{"x": 0, "y": 0}], "artifact_dir": "x/"})
    entry = summarize_report(report, label="abc123", timestamp=None)
    metrics = entry.scenarios["straight"]["metrics"]
    assert metrics == {"travel_time": 12.0, "collision_free": 1.0}
    assert "trajectory" not in metrics
    assert "artifact_dir" not in metrics


def test_summarize_report_defaults_timestamp_to_generated_at():
    entry = summarize_report(_report({"travel_time": 1.0}), label="abc", timestamp=None)
    assert entry.timestamp == "2026-06-05T00:00:00+00:00"


def test_append_and_load_roundtrip(tmp_path: Path):
    history = tmp_path / "history.jsonl"
    append_history(history, summarize_report(_report({"travel_time": 10.0}), label="r1", timestamp=None))
    append_history(history, summarize_report(_report({"travel_time": 12.0}), label="r2", timestamp=None))
    entries = load_history(history)
    assert [entry.label for entry in entries] == ["r1", "r2"]
    assert entries[1].scenarios["straight"]["metrics"]["travel_time"] == 12.0


def test_load_history_skips_blank_lines(tmp_path: Path):
    history = tmp_path / "history.jsonl"
    history.write_text(
        json.dumps({"label": "r1", "scenarios": {}}) + "\n\n" + json.dumps({"label": "r2", "scenarios": {}}) + "\n",
        encoding="utf-8",
    )
    assert [entry.label for entry in load_history(history)] == ["r1", "r2"]


def test_load_history_rejects_malformed_line(tmp_path: Path):
    history = tmp_path / "history.jsonl"
    history.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid history line"):
        load_history(history)


def _trend_with_two_runs():
    entries = [
        summarize_report(_report({"travel_time": 10.0}), label="r1", timestamp=None),
        summarize_report(_report({"travel_time": 13.0}), label="r2", timestamp=None),
    ]
    return build_trend(entries)


def test_build_trend_aligns_series_with_labels():
    trend = _trend_with_two_runs()
    assert trend.labels == ["r1", "r2"]
    assert trend.series["travel_time"]["straight"] == [10.0, 13.0]
    assert trend.pass_rates == [1.0, 1.0]


def test_build_trend_requires_entries():
    with pytest.raises(ValueError, match="at least one"):
        build_trend([])


def test_build_trend_handles_absent_metric_in_a_run():
    entries = [
        summarize_report(_report({"travel_time": 10.0}), label="r1", timestamp=None),
        summarize_report(_report({"recovery_count": 2}), label="r2", timestamp=None),
    ]
    trend = build_trend(entries)
    assert trend.series["travel_time"]["straight"] == [10.0, None]
    assert trend.series["recovery_count"]["straight"] == [None, 2.0]


def test_trend_to_dict_flags_regression():
    # travel_time is lower-is-better; going 10 -> 13 is worse.
    data = trend_to_dict(_trend_with_two_runs())
    assert data["runs"] == 2
    delta = data["latest_deltas"]["travel_time"]["straight"]
    assert delta["delta"] == 3.0
    assert delta["improved"] is False


def test_markdown_has_pass_rate_and_metric_sections():
    text = format_trend_markdown(_trend_with_two_runs())
    assert "# Nav2 Trend" in text
    assert "Pass Rate" in text
    assert "travel_time" in text
    assert "worse" in text  # regression marker


def test_html_renders_charts():
    html = format_trend_html(_trend_with_two_runs())
    assert "<title>Nav2 Trend</title>" in html
    assert "Pass Rate" in html
    assert "Metric Trends" in html
    assert "<polyline" in html


def test_single_run_renders_without_error():
    entries = [summarize_report(_report({"travel_time": 10.0}), label="solo", timestamp=None)]
    trend = build_trend(entries)
    html = format_trend_html(trend)
    assert "<polyline" in html  # single point still draws a marker/segment
    data = trend_to_dict(trend)
    # No previous run -> no deltas.
    assert data["latest_deltas"] == {}
