from __future__ import annotations

import pytest

from nav2_scenario_runner.badges import KINDS, build_badge


def _evaluation(score: float = 73.8, passed: int = 3, total: int = 3) -> dict:
    return {
        "scenario_count": total,
        "leaderboard": [
            {"rank": 1, "label": "navfn", "score": score, "passed": passed, "total": total, "wins": 5},
            {"rank": 2, "label": "smac", "score": 60.0, "passed": 3, "total": 3, "wins": 3},
        ],
    }


def _trend(regressions: int = 2) -> dict:
    deltas = {
        "travel_time": {
            f"s{i}": {"latest": 1.0, "delta": 1.0, "improved": False} for i in range(regressions)
        },
        "collision_free": {"s0": {"latest": 1.0, "delta": 0.0, "improved": None}},
    }
    return {"runs": 3, "latest_deltas": deltas}


def test_winner_badge_uses_medal_and_blue():
    badge = build_badge("winner", _evaluation())
    assert badge["schemaVersion"] == 1
    assert "navfn" in badge["message"] and "🥇" in badge["message"]
    assert badge["color"] == "blue"


def test_score_badge_message_and_color_thresholds():
    assert build_badge("score", _evaluation(score=85))["color"] == "brightgreen"
    assert build_badge("score", _evaluation(score=73.8))["color"] == "green"
    assert build_badge("score", _evaluation(score=45))["color"] == "yellowgreen"
    assert build_badge("score", _evaluation(score=25))["color"] == "orange"
    assert build_badge("score", _evaluation(score=5))["color"] == "red"
    assert build_badge("score", _evaluation(score=73.8))["message"] == "73.8/100"


def test_passrate_badge():
    assert build_badge("passrate", _evaluation(passed=3, total=3))["message"] == "100%"
    assert build_badge("passrate", _evaluation(passed=3, total=3))["color"] == "brightgreen"
    assert build_badge("passrate", _evaluation(passed=1, total=3))["color"] == "red"


def test_regressions_badge_counts_and_colors():
    assert build_badge("regressions", _evaluation(), _trend(0))["message"] == "0"
    assert build_badge("regressions", _evaluation(), _trend(0))["color"] == "brightgreen"
    assert build_badge("regressions", _evaluation(), _trend(2))["color"] == "yellow"
    assert build_badge("regressions", _evaluation(), _trend(5))["color"] == "red"


def test_regressions_badge_requires_trend():
    with pytest.raises(ValueError, match="requires trend"):
        build_badge("regressions", _evaluation())


def test_unknown_kind_rejected():
    with pytest.raises(ValueError, match="unknown badge kind"):
        build_badge("bogus", _evaluation())


def test_empty_leaderboard_rejected():
    with pytest.raises(ValueError, match="empty leaderboard"):
        build_badge("score", {"leaderboard": []})


def test_all_kinds_listed():
    assert set(KINDS) == {"winner", "score", "passrate", "regressions"}
