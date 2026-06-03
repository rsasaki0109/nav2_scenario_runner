from __future__ import annotations

from nav2_scenario_runner.report_view import (
    format_console_report,
    format_html_report,
    format_markdown_report,
    report_has_failures,
)


def test_console_report_formats_metrics_and_failures():
    report = {
        "mode": "attach",
        "generated_at": "2026-06-03T00:00:00+00:00",
        "total": 2,
        "passed": 1,
        "failed": 1,
        "scenarios": [
            {
                "scenario_id": "straight_line_goal",
                "name": "straight_line_goal",
                "status": "passed",
                "step_count": 4,
                "assertion_count": 3,
                "duration_seconds": 12.4,
                "metrics": {
                    "travel_time": 12.4,
                    "path_length_traveled": 10.8,
                    "recovery_count": 0,
                    "replanning_count": 1,
                    "collision_free": True,
                },
            },
            {
                "scenario_id": "dynamic_obstacle",
                "name": "dynamic_obstacle",
                "status": "failed",
                "step_count": 3,
                "assertion_count": 2,
                "duration_seconds": 60.0,
                "failure_reason": "timeout after 60s",
                "metrics": {
                    "travel_time": 60.0,
                    "path_length_traveled": 18.25,
                    "recovery_count": 3,
                    "replanning_count": 8,
                    "collision_free": False,
                    "artifact_dir": "reports/artifacts/dynamic_obstacle",
                },
                "steps": [
                    {
                        "index": 2,
                        "kind": "expect_goal_reached",
                        "status": "timeout",
                        "failure_reason": "timeout after 60s",
                    }
                ],
                "assertions": [
                    {
                        "index": 0,
                        "kind": "collision_free",
                        "status": "failed",
                        "message": "collision_free=false.",
                    }
                ],
            },
        ],
    }

    text = format_console_report(report)

    assert "Report FAIL: mode=attach total=2 passed=1 failed=1" in text
    assert "- PASS straight_line_goal status=passed duration=12.400s steps=4 assertions=3" in text
    assert "metrics: travel_time=12.4, path_length_traveled=10.8, recovery_count=0" in text
    assert "- FAIL dynamic_obstacle status=failed duration=60.000s steps=3 assertions=2" in text
    assert "artifacts: reports/artifacts/dynamic_obstacle" in text
    assert "reason: timeout after 60s" in text
    assert "step 2: expect_goal_reached timeout - timeout after 60s" in text
    assert "assertion 0: collision_free failed - collision_free=false." in text
    assert report_has_failures(report)


def test_markdown_report_includes_summary_table_and_failure_details():
    report = {
        "mode": "attach",
        "total": 1,
        "passed": 0,
        "failed": 1,
        "scenarios": [
            {
                "scenario_id": "blocked_path",
                "status": "failed",
                "duration_seconds": 30.0,
                "failure_reason": "path length regression",
                "metrics": {
                    "travel_time": 30.0,
                    "path_length_traveled": 14.5,
                    "recovery_count": 1,
                    "replanning_count": 4,
                    "collision_free": True,
                    "artifact_dir": "reports/artifacts/blocked_path",
                    "gazebo_log": "reports/artifacts/blocked_path/gazebo.log",
                    "metadata": "reports/artifacts/blocked_path/metadata.json",
                },
                "assertions": [
                    {
                        "index": 1,
                        "kind": "path_length",
                        "status": "warning",
                        "message": "path_length_traveled=14.5 exceeds max 12.0.",
                    }
                ],
            }
        ],
    }

    text = format_markdown_report(report)

    assert "# Nav2 Scenario Report" in text
    assert "- Result: `FAIL`" in text
    assert "| blocked_path | failed | 30.000s | 30 | 14.5 | 1 | 4 | true |" in text
    assert "## Scenario Details" in text
    assert "- Artifacts:" in text
    assert "Gazebo log: `reports/artifacts/blocked_path/gazebo.log`" in text
    assert "path_length_traveled=14.5 exceeds max 12.0." in text


def test_html_report_includes_table_details_and_escapes_values():
    report = {
        "mode": "attach",
        "generated_at": "2026-06-03T00:00:00+00:00",
        "total": 1,
        "passed": 0,
        "failed": 1,
        "scenarios": [
            {
                "scenario_id": "blocked_<path>",
                "status": "failed",
                "duration_seconds": 30.0,
                "failure_reason": "timeout < 30s",
                "metrics": {
                    "travel_time": 30.0,
                    "path_length_traveled": 14.5,
                    "recovery_count": 1,
                    "replanning_count": 4,
                    "collision_free": False,
                    "artifact_dir": "reports/artifacts/blocked_path",
                    "scenario_copy": "reports/artifacts/blocked_path/scenario.yaml",
                    "gazebo_log": "reports/artifacts/blocked_path/gazebo.log",
                    "metadata": "reports/artifacts/blocked_path/metadata.json",
                },
                "assertions": [
                    {
                        "index": 1,
                        "kind": "path_length",
                        "status": "warning",
                        "message": "path_length_traveled=14.5 exceeds max 12.0.",
                    }
                ],
            }
        ],
    }

    text = format_html_report(report)

    assert text.startswith("<!doctype html>")
    assert "<title>Nav2 Scenario Report</title>" in text
    assert '<span class="badge fail">FAIL</span>' in text
    assert "blocked_&lt;path&gt;" in text
    assert "timeout &lt; 30s" in text
    assert "<td class=\"num\">14.5</td>" in text
    assert "<h4>Artifacts</h4>" in text
    assert '<a href="reports/artifacts/blocked_path/gazebo.log"><code>reports/artifacts/blocked_path/gazebo.log</code></a>' in text
    assert '<a href="reports/artifacts/blocked_path/metadata.json"><code>reports/artifacts/blocked_path/metadata.json</code></a>' in text
    assert "path_length_traveled=14.5 exceeds max 12.0." in text
    assert "blocked_<path>" not in text


def test_html_report_shows_artifact_details_for_passing_scenario():
    report = {
        "mode": "gazebo_sim",
        "total": 1,
        "passed": 1,
        "failed": 0,
        "scenarios": [
            {
                "scenario_id": "straight_line_goal",
                "status": "passed",
                "duration_seconds": 1.0,
                "metrics": {
                    "artifact_dir": "reports/artifacts/straight_line_goal",
                    "gazebo_log": "reports/artifacts/straight_line_goal/gazebo.log",
                    "metadata": "reports/artifacts/straight_line_goal/metadata.json",
                    "trajectory": [
                        {"x": 0.0, "y": 0.0},
                        {"x": 1.0, "y": 0.0},
                    ],
                    "trajectory_point_count": 2,
                },
            }
        ],
    }

    text = format_html_report(report)

    assert "Scenario Details" in text
    assert "straight_line_goal" in text
    assert "<h4>Trajectory</h4>" in text
    assert "Robot trajectory" in text
    assert "<strong>2</strong>" in text
    assert "reports/artifacts/straight_line_goal/gazebo.log" in text
