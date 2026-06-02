from __future__ import annotations

import json
from xml.etree import ElementTree

from nav2_scenario_runner.reporting import write_junit_report, write_trace_report
from nav2_scenario_runner.runner import AssertionRunResult, RunReport, ScenarioRunResult, StepRunResult


def test_junit_report_marks_failed_scenario(tmp_path):
    report = RunReport(
        runner_version="0.1.0",
        generated_at="2026-06-03T00:00:00+00:00",
        mode="fake",
        total=1,
        passed=0,
        failed=1,
        scenarios=[
            ScenarioRunResult(
                scenario_id="unknown_step",
                name="unknown_step",
                path="unknown.yaml",
                tags=[],
                status="failed",
                step_count=1,
                assertion_count=0,
                duration_seconds=0.25,
                failure_reason="Unsupported executable step: custom_plugin_step",
                steps=[
                    StepRunResult(
                        index=0,
                        kind="custom_plugin_step",
                        status="failed",
                        duration_seconds=0.01,
                        failure_reason="Unsupported executable step: custom_plugin_step",
                    )
                ],
                assertions=[
                    AssertionRunResult(
                        index=0,
                        kind="travel_time",
                        status="failed",
                        message="travel_time=3 exceeds max 1.",
                        metric="travel_time",
                        actual=3.0,
                        expected=1.0,
                    )
                ],
            )
        ],
    )

    path = tmp_path / "junit.xml"
    write_junit_report(report, path)

    root = ElementTree.parse(path).getroot()
    assert root.attrib["tests"] == "1"
    assert root.attrib["failures"] == "1"

    testcase = root.find(".//testcase")
    assert testcase is not None
    assert testcase.attrib["classname"] == "unknown.yaml"
    assert testcase.attrib["name"] == "unknown_step"

    failure = root.find(".//failure")
    assert failure is not None
    assert failure.attrib["message"] == "Unsupported executable step: custom_plugin_step"
    assert "custom_plugin_step" in (failure.text or "")

    system_out = root.find(".//system-out")
    assert system_out is not None
    assert "step 0: custom_plugin_step failed" in (system_out.text or "")
    assert "assertion 0: travel_time failed" in (system_out.text or "")


def test_trace_report_writes_timeline_events(tmp_path):
    report = RunReport(
        runner_version="0.1.0",
        generated_at="2026-06-03T00:00:00+00:00",
        mode="fake",
        total=1,
        passed=0,
        failed=1,
        scenarios=[
            ScenarioRunResult(
                scenario_id="blocked_path",
                name="blocked_path",
                path="blocked.yaml",
                tags=["regression"],
                status="failed",
                step_count=1,
                assertion_count=1,
                duration_seconds=2.0,
                failure_reason="timeout after 2s",
                steps=[
                    StepRunResult(
                        index=0,
                        kind="expect_goal_reached",
                        status="timeout",
                        duration_seconds=1.25,
                        failure_reason="timeout after 2s",
                    )
                ],
                assertions=[
                    AssertionRunResult(
                        index=0,
                        kind="path_length",
                        status="failed",
                        severity="error",
                        message="path_length_traveled=14.5 exceeds max 12.0.",
                        metric="path_length_traveled",
                        actual=14.5,
                        expected=12.0,
                    )
                ],
                metrics={"path_length_traveled": 14.5, "collision_free": True},
            )
        ],
    )

    path = tmp_path / "trace.json"
    write_trace_report(report, path)

    trace = json.loads(path.read_text(encoding="utf-8"))
    assert trace["schema"] == "nav2_scenario_runner.trace/v1alpha1"
    assert trace["mode"] == "fake"

    scenario = trace["scenarios"][0]
    assert scenario["scenario_id"] == "blocked_path"
    assert scenario["duration_seconds"] == 2.0

    events = scenario["events"]
    event_types = [event["type"] for event in events]
    assert event_types == [
        "scenario.started",
        "step.started",
        "step.finished",
        "assertion.evaluated",
        "metric.recorded",
        "metric.recorded",
        "scenario.finished",
    ]
    assert events[2]["time_offset_seconds"] == 1.25
    assert events[2]["data"]["failure_reason"] == "timeout after 2s"
    assert events[3]["data"]["actual"] == 14.5
    assert events[3]["data"]["expected"] == 12.0
    assert events[-1]["data"]["failure_reason"] == "timeout after 2s"


def test_trace_report_preserves_explicit_parallel_step_offsets(tmp_path):
    report = RunReport(
        runner_version="0.1.0",
        generated_at="2026-06-03T00:00:00+00:00",
        mode="gazebo_sim",
        total=1,
        passed=1,
        failed=0,
        scenarios=[
            ScenarioRunResult(
                scenario_id="dynamic_obstacle",
                name="dynamic_obstacle",
                path="dynamic.yaml",
                tags=["regression"],
                status="passed",
                step_count=2,
                assertion_count=0,
                duration_seconds=3.0,
                steps=[
                    StepRunResult(
                        index=1,
                        kind="send_goal",
                        status="passed",
                        duration_seconds=2.0,
                        time_offset_seconds=1.0,
                    ),
                    StepRunResult(
                        index=0,
                        kind="gazebo_sim.parallel.obstacle.spawn_obstacle",
                        status="passed",
                        duration_seconds=0.25,
                        time_offset_seconds=0.5,
                    ),
                ],
                assertions=[],
                metrics={},
            )
        ],
    )

    path = tmp_path / "trace.json"
    write_trace_report(report, path)

    events = json.loads(path.read_text(encoding="utf-8"))["scenarios"][0]["events"]
    step_events = [event for event in events if event["type"].startswith("step.")]

    assert [
        (event["type"], event["time_offset_seconds"], event["data"]["kind"])
        for event in step_events
    ] == [
        ("step.started", 0.5, "gazebo_sim.parallel.obstacle.spawn_obstacle"),
        ("step.finished", 0.75, "gazebo_sim.parallel.obstacle.spawn_obstacle"),
        ("step.started", 1.0, "send_goal"),
        ("step.finished", 3.0, "send_goal"),
    ]
