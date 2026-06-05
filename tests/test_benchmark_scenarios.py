from __future__ import annotations

import json
from pathlib import Path

import yaml

from nav2_scenario_runner.cli import main

SCENARIO_DIR = Path("examples/benchmark/scenarios")
EXPECTED = {"straight_line", "narrow_corridor", "u_turn"}


def test_benchmark_scenarios_exist():
    names = {p.stem for p in SCENARIO_DIR.glob("*.yaml")}
    assert EXPECTED <= names


def test_benchmark_scenarios_lint(capsys):
    exit_code = main(["lint", str(SCENARIO_DIR)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OK" in captured.out
    assert "FAIL" not in captured.out


def test_benchmark_scenarios_dry_run(tmp_path, capsys):
    exit_code = main(["run", str(SCENARIO_DIR), "--dry-run", "--report-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code == 0

    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert {s["name"] for s in report["scenarios"]} == EXPECTED


def test_benchmark_scenario_names_match_the_leaderboard_suite():
    """Scenario ids must match the fixture configs so real runs slot into the
    same leaderboard/viewer rows."""

    for path in SCENARIO_DIR.glob("*.yaml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert document["metadata"]["name"] == path.stem
        assert document["simulator"]["type"] == "gazebo_sim"
        assert document["simulator"]["headless"] is True
