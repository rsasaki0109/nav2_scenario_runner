from __future__ import annotations

import pytest

from nav2_scenario_runner.pr_comment import (
    COMMENT_MARKER,
    build_comment,
    summarize_trend,
)


def _evaluation() -> dict:
    return {
        "schema": "nav2_scenario_runner.evaluation/v1alpha1",
        "scenario_count": 3,
        "metrics": ["travel_time", "recovery_count"],
        "leaderboard": [
            {"rank": 1, "label": "navfn", "score": 73.8, "pass_rate": 1.0, "passed": 3, "total": 3, "wins": 5},
            {"rank": 2, "label": "smac", "score": 73.3, "pass_rate": 1.0, "passed": 3, "total": 3, "wins": 11},
            {"rank": 3, "label": "teb", "score": 46.7, "pass_rate": 2 / 3, "passed": 2, "total": 3, "wins": 7},
        ],
    }


def _trend(runs: int = 6) -> dict:
    return {
        "schema": "nav2_scenario_runner.trend/v1alpha1",
        "runs": runs,
        "labels": [f"r{i}" for i in range(runs)],
        "pass_rates": [1.0] * runs,
        "metrics": ["travel_time", "recovery_count"],
        "latest_deltas": {
            "travel_time": {
                "narrow_corridor": {"latest": 28.0, "delta": 1.6, "improved": False},
                "straight_line": {"latest": 12.0, "delta": -0.5, "improved": True},
            },
            "recovery_count": {
                "narrow_corridor": {"latest": 3.0, "delta": 1.0, "improved": False},
            },
            "collision_free": {
                "narrow_corridor": {"latest": 1.0, "delta": 0.0, "improved": None},
            },
        },
    }


def test_summarize_trend_counts_and_sorts():
    summary = summarize_trend(_trend())
    assert summary["regressions"] == 2
    assert summary["improvements"] == 1
    # Sorted by absolute delta, largest first; null-improved entries excluded.
    assert [r["metric"] for r in summary["rows"]] == ["travel_time", "recovery_count"]
    assert summary["rows"][0]["scenario"] == "narrow_corridor"


def test_build_comment_has_marker_and_winner():
    body = build_comment(_evaluation())
    assert body.startswith(COMMENT_MARKER)
    assert "Winner: `navfn`" in body
    assert "73.8 / 100" in body


def test_build_comment_bolds_winner_and_uses_medals():
    body = build_comment(_evaluation())
    assert "🥇 | **navfn**" in body
    assert "🥈 | smac" in body
    assert "🥉 | teb" in body


def test_build_comment_renders_pass_fraction():
    body = build_comment(_evaluation())
    assert "100% (3/3)" in body
    assert "67% (2/3)" in body


def test_build_comment_includes_trend_regressions():
    body = build_comment(_evaluation(), _trend())
    assert "Trend vs previous run" in body
    assert "2 regression(s)" in body
    assert "1 improvement(s)" in body
    assert "<details><summary>Regressions</summary>" in body
    assert "| travel_time | narrow_corridor | +1.60 | 28.00 |" in body


def test_build_comment_first_run_has_no_comparison():
    body = build_comment(_evaluation(), _trend(runs=1))
    assert "First recorded run" in body
    assert "regression(s)" not in body


def test_build_comment_dashboard_link_optional():
    assert "full dashboard" not in build_comment(_evaluation())
    body = build_comment(_evaluation(), dashboard_url="https://example.com/d")
    assert "[full dashboard](https://example.com/d)" in body


def test_build_comment_rejects_empty_leaderboard():
    with pytest.raises(ValueError, match="empty leaderboard"):
        build_comment({"leaderboard": [], "scenario_count": 0})


def test_build_comment_collapses_many_regressions():
    trend = {
        "runs": 2,
        "latest_deltas": {
            "m": {
                f"s{i}": {"latest": float(i), "delta": float(i + 1), "improved": False}
                for i in range(12)
            }
        },
    }
    body = build_comment(_evaluation(), trend)
    assert "and 4 more regression(s)" in body  # 12 rows - 8 shown
