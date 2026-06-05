"""Guard the committed public-benchmark fixtures and the docs site generation.

These fixtures drive the GitHub Pages dashboards built by
``scripts/build_dashboards.sh``. The tests make sure they stay loadable and that
the evaluate/trend/replay renderers still produce the expected artifacts, so the
published benchmark cannot silently rot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nav2_scenario_runner.evaluate import (
    ConfigEntry,
    build_evaluation,
    format_evaluation_html,
)
from nav2_scenario_runner.history import build_trend, format_trend_html, load_history
from nav2_scenario_runner.replay import format_replay_html, load_map, load_replay_scenarios

BENCH = Path(__file__).resolve().parents[1] / "examples" / "benchmark"
CONFIG_LABELS = ("navfn", "smac", "teb")


def _load(label: str) -> ConfigEntry:
    path = BENCH / f"{label}.json"
    return ConfigEntry(label=label, path=str(path), report=json.loads(path.read_text(encoding="utf-8")))


def test_benchmark_reports_exist():
    for label in CONFIG_LABELS:
        assert (BENCH / f"{label}.json").is_file(), f"missing benchmark report for {label}"
    assert (BENCH / "history.jsonl").is_file()
    assert (BENCH / "maps" / "warehouse.yaml").is_file()
    assert (BENCH / "maps" / "warehouse.pgm").is_file()


def test_evaluate_fixture_builds_full_leaderboard():
    evaluation = build_evaluation([_load(label) for label in CONFIG_LABELS])
    assert {config.label for config in evaluation.configs} == set(CONFIG_LABELS)
    assert evaluation.configs[0].rank == 1
    # Every config ran all three scenarios.
    assert len(evaluation.scenario_ids) == 3
    html = format_evaluation_html(evaluation)
    assert "Leaderboard" in html and "Trajectory Overlay" in html


def test_trend_fixture_builds_six_runs():
    trend = build_trend(load_history(BENCH / "history.jsonl"))
    assert len(trend.labels) == 6
    assert "travel_time" in trend.metrics
    assert "<polyline" in format_trend_html(trend)


def test_replay_fixture_overlays_on_map():
    report = json.loads((BENCH / "smac.json").read_text(encoding="utf-8"))
    scenarios = load_replay_scenarios(report)
    assert len(scenarios) == 3  # all three scenarios carry trajectories
    map_image = load_map(BENCH / "maps" / "warehouse.yaml")
    html = format_replay_html(scenarios, map_image)
    assert "data:image/png;base64," in html
    assert "<animateMotion" in html


def test_benchmark_trajectories_fit_the_map_bounds():
    """Every trajectory point must project inside the warehouse map image."""

    map_image = load_map(BENCH / "maps" / "warehouse.yaml")
    for label in CONFIG_LABELS:
        report = json.loads((BENCH / f"{label}.json").read_text(encoding="utf-8"))
        for scenario in load_replay_scenarios(report):
            for point in scenario.points:
                x, y = map_image.project(point["x"], point["y"])
                assert -1.0 <= x <= map_image.width + 1.0, f"{label}/{scenario.scenario_id} x out of bounds"
                assert -1.0 <= y <= map_image.height + 1.0, f"{label}/{scenario.scenario_id} y out of bounds"


SUBMISSIONS = sorted((BENCH / "submissions").glob("*.json"))
CORE_SCENARIO_IDS = {"straight_line", "narrow_corridor", "u_turn"}


@pytest.mark.parametrize("submission", SUBMISSIONS, ids=lambda p: p.stem)
def test_community_submissions_are_valid(submission: Path):
    """Each merged submission must load and cover the core scenario ids.

    Submissions are auto-included on the public leaderboard, so a malformed one
    would break the deployed dashboard. This guards every file under
    submissions/ at once.
    """

    report = json.loads(submission.read_text(encoding="utf-8"))
    ids = {scenario["scenario_id"] for scenario in report["scenarios"]}
    assert CORE_SCENARIO_IDS <= ids, f"{submission.name} is missing core scenarios"

    map_image = load_map(BENCH / "maps" / "warehouse.yaml")
    for scenario in load_replay_scenarios(report):
        for point in scenario.points:
            x, y = map_image.project(point["x"], point["y"])
            assert -1.0 <= x <= map_image.width + 1.0, f"{submission.name} x out of bounds"
            assert -1.0 <= y <= map_image.height + 1.0, f"{submission.name} y out of bounds"


def test_evaluate_includes_submissions_on_leaderboard():
    labels = list(CONFIG_LABELS) + [p.stem for p in SUBMISSIONS]
    evaluation = build_evaluation([_load_any(label) for label in labels])
    assert {config.label for config in evaluation.configs} == set(labels)


def _load_any(label: str) -> ConfigEntry:
    for base in (BENCH, BENCH / "submissions"):
        path = base / f"{label}.json"
        if path.is_file():
            return ConfigEntry(label=label, path=str(path), report=json.loads(path.read_text(encoding="utf-8")))
    raise AssertionError(f"no report found for {label}")
