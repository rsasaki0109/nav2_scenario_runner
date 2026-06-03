from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import nav2_scenario_runner.cli as cli
from nav2_scenario_runner.cli import main
from nav2_scenario_runner.doctor import DoctorCheck, DoctorReport
from nav2_scenario_runner.runner import RunReport, ScenarioRunResult


def test_lint_accepts_example_scenario(capsys):
    exit_code = main(["lint", "examples/turtlebot3_gazebo/smoke.yaml"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OK   examples/turtlebot3_gazebo/smoke.yaml" in captured.out


def test_run_dry_run_writes_json_report(tmp_path, capsys):
    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--dry-run",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "DRY-RUN PASS straight_line_goal" in captured.out

    report_path = tmp_path / "results.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "dry_run"
    assert report["total"] == 1
    assert report["scenarios"][0]["name"] == "straight_line_goal"
    assert report["scenarios"][0]["status"] == "dry_run_passed"
    assert report["scenarios"][0]["steps"] == []

    junit_path = tmp_path / "junit.xml"
    junit = ElementTree.parse(junit_path)
    testcase = junit.find(".//testcase")
    assert testcase is not None
    assert testcase.attrib["name"] == "straight_line_goal"
    assert junit.find(".//failure") is None


def test_run_dry_run_writes_optional_reports_and_github_summary(tmp_path, capsys, monkeypatch):
    summary_path = tmp_path / "github_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--dry-run",
            "--report-dir",
            str(tmp_path),
            "--trace-report",
            "trace.json",
            "--markdown-report",
            "summary.md",
            "--html-report",
            "index.html",
            "--github-summary",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"Trace report: {tmp_path / 'trace.json'}" in captured.out
    assert f"Markdown report: {tmp_path / 'summary.md'}" in captured.out
    assert f"HTML report: {tmp_path / 'index.html'}" in captured.out
    assert f"GitHub summary: {summary_path}" in captured.out

    markdown = (tmp_path / "summary.md").read_text(encoding="utf-8")
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    trace = json.loads((tmp_path / "trace.json").read_text(encoding="utf-8"))
    github_summary = summary_path.read_text(encoding="utf-8")
    assert "# Nav2 Scenario Report" in markdown
    assert "<!doctype html>" in html
    assert "straight_line_goal" in html
    assert trace["schema"] == "nav2_scenario_runner.trace/v1alpha1"
    assert trace["scenarios"][0]["events"][0]["type"] == "scenario.started"
    assert "# Nav2 Scenario Report" in github_summary


def test_run_github_summary_requires_environment_but_still_writes_core_reports(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--dry-run",
            "--report-dir",
            str(tmp_path),
            "--github-summary",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "GitHub summary failed: GITHUB_STEP_SUMMARY is not set" in captured.err
    assert (tmp_path / "results.json").exists()
    assert (tmp_path / "junit.xml").exists()


def test_run_gazebo_sim_mode_uses_lifecycle_backend(tmp_path, capsys, monkeypatch):
    def fake_doctor(check_ros=False, check_gazebo=False):
        assert check_gazebo is True
        return DoctorReport(passed=True, checks=[], environment={})

    def fake_lifecycle(
        scenarios,
        report_dir,
        startup_timeout,
        preflight_skipped=False,
        wait_for_clock=False,
        clock_timeout=10.0,
        execute_nav2=False,
        launch_scenario_stack=False,
        wait_for_ros_graph=False,
        ros_graph_timeout=10.0,
        wait_for_nav2=False,
        nav2_timeout=30.0,
        wait_for_navigation_data=False,
        navigation_data_timeout=30.0,
        reset_world=False,
        world_reset_timeout=10.0,
        execute_simulator_steps=False,
        simulator_step_timeout=10.0,
        collect_contacts=False,
        contact_topics=None,
        contact_discovery_timeout=5.0,
    ):
        assert len(scenarios) == 1
        assert report_dir == tmp_path
        assert startup_timeout == 0.25
        assert preflight_skipped is False
        assert wait_for_clock is False
        assert clock_timeout == 10.0
        assert execute_nav2 is False
        assert launch_scenario_stack is False
        assert wait_for_ros_graph is False
        assert ros_graph_timeout == 10.0
        assert wait_for_nav2 is False
        assert nav2_timeout == 30.0
        assert wait_for_navigation_data is False
        assert navigation_data_timeout == 30.0
        assert reset_world is False
        assert world_reset_timeout == 10.0
        assert execute_simulator_steps is False
        assert simulator_step_timeout == 10.0
        assert collect_contacts is False
        assert (contact_topics or []) == []
        assert contact_discovery_timeout == 5.0
        return RunReport(
            runner_version="0.1.0",
            generated_at="2026-06-03T00:00:00+00:00",
            mode="gazebo_sim",
            total=1,
            passed=1,
            failed=0,
            scenarios=[
                ScenarioRunResult(
                    scenario_id="straight_line_goal",
                    name="straight_line_goal",
                    path="examples/turtlebot3_gazebo/smoke.yaml",
                    tags=["smoke"],
                    status="passed",
                    step_count=1,
                    assertion_count=0,
                    duration_seconds=0.1,
                    steps=[],
                    assertions=[],
                    metrics={"simulator_started": True},
                )
            ],
        )

    monkeypatch.setattr(cli, "run_doctor", fake_doctor)
    monkeypatch.setattr("nav2_scenario_runner.backends.gazebo_sim.run_gazebo_sim_lifecycle", fake_lifecycle)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--mode",
            "gazebo-sim",
            "--sim-startup-timeout",
            "0.25",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "GAZEBO-SIM PASS straight_line_goal" in captured.out
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert report["mode"] == "gazebo_sim"
    assert report["scenarios"][0]["metrics"]["simulator_started"] is True


def test_run_gazebo_sim_mode_stops_when_preflight_fails(tmp_path, capsys, monkeypatch):
    def fake_doctor(check_ros=False, check_gazebo=False):
        return DoctorReport(
            passed=False,
            checks=[
                DoctorCheck(
                    name="gazebo.gz",
                    status="fail",
                    required=True,
                    message="gz executable not found on PATH",
                )
            ],
            environment={},
        )

    monkeypatch.setattr(cli, "run_doctor", fake_doctor)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--mode",
            "gazebo-sim",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Gazebo Sim backend unavailable" in captured.err
    assert "gazebo.gz: gz executable not found on PATH" in captured.err
    assert not (tmp_path / "results.json").exists()


def test_run_gazebo_sim_mode_can_skip_preflight(tmp_path, capsys, monkeypatch):
    def fail_if_called(check_ros=False, check_gazebo=False):
        raise AssertionError("doctor preflight should not be called")

    def fake_lifecycle(
        scenarios,
        report_dir,
        startup_timeout,
        preflight_skipped=False,
        wait_for_clock=False,
        clock_timeout=10.0,
        execute_nav2=False,
        launch_scenario_stack=False,
        wait_for_ros_graph=False,
        ros_graph_timeout=10.0,
        wait_for_nav2=False,
        nav2_timeout=30.0,
        wait_for_navigation_data=False,
        navigation_data_timeout=30.0,
        reset_world=False,
        world_reset_timeout=10.0,
        execute_simulator_steps=False,
        simulator_step_timeout=10.0,
        collect_contacts=False,
        contact_topics=None,
        contact_discovery_timeout=5.0,
    ):
        assert preflight_skipped is True
        assert wait_for_clock is False
        assert clock_timeout == 10.0
        assert execute_nav2 is False
        assert launch_scenario_stack is False
        assert wait_for_ros_graph is False
        assert ros_graph_timeout == 10.0
        assert wait_for_nav2 is False
        assert nav2_timeout == 30.0
        assert wait_for_navigation_data is False
        assert navigation_data_timeout == 30.0
        assert reset_world is False
        assert world_reset_timeout == 10.0
        assert execute_simulator_steps is False
        assert simulator_step_timeout == 10.0
        assert collect_contacts is False
        assert (contact_topics or []) == []
        assert contact_discovery_timeout == 5.0
        return RunReport(
            runner_version="0.1.0",
            generated_at="2026-06-03T00:00:00+00:00",
            mode="gazebo_sim",
            total=1,
            passed=1,
            failed=0,
            scenarios=[
                ScenarioRunResult(
                    scenario_id="straight_line_goal",
                    name="straight_line_goal",
                    path="examples/turtlebot3_gazebo/smoke.yaml",
                    tags=["smoke"],
                    status="passed",
                    step_count=1,
                    assertion_count=0,
                    duration_seconds=0.1,
                    steps=[],
                    assertions=[],
                    metrics={"simulator_started": True},
                )
            ],
        )

    monkeypatch.setattr(cli, "run_doctor", fail_if_called)
    monkeypatch.setattr("nav2_scenario_runner.backends.gazebo_sim.run_gazebo_sim_lifecycle", fake_lifecycle)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--mode",
            "gazebo-sim",
            "--skip-gazebo-preflight",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "GAZEBO-SIM PASS straight_line_goal" in captured.out
    assert (tmp_path / "results.json").exists()


def test_run_gazebo_sim_mode_passes_clock_options(tmp_path, capsys, monkeypatch):
    def fake_doctor(check_ros=False, check_gazebo=False):
        assert check_gazebo is True
        return DoctorReport(passed=True, checks=[], environment={})

    def fake_lifecycle(
        scenarios,
        report_dir,
        startup_timeout,
        preflight_skipped=False,
        wait_for_clock=False,
        clock_timeout=10.0,
        execute_nav2=False,
        launch_scenario_stack=False,
        wait_for_ros_graph=False,
        ros_graph_timeout=10.0,
        wait_for_nav2=False,
        nav2_timeout=30.0,
        wait_for_navigation_data=False,
        navigation_data_timeout=30.0,
        reset_world=False,
        world_reset_timeout=10.0,
        execute_simulator_steps=False,
        simulator_step_timeout=10.0,
        collect_contacts=False,
        contact_topics=None,
        contact_discovery_timeout=5.0,
    ):
        assert len(scenarios) == 1
        assert report_dir == tmp_path
        assert startup_timeout == 0.0
        assert preflight_skipped is False
        assert wait_for_clock is True
        assert clock_timeout == 2.5
        assert execute_nav2 is False
        assert launch_scenario_stack is False
        assert wait_for_ros_graph is False
        assert ros_graph_timeout == 10.0
        assert wait_for_nav2 is False
        assert nav2_timeout == 30.0
        assert wait_for_navigation_data is False
        assert navigation_data_timeout == 30.0
        assert reset_world is False
        assert world_reset_timeout == 10.0
        assert execute_simulator_steps is False
        assert simulator_step_timeout == 10.0
        assert collect_contacts is False
        assert (contact_topics or []) == []
        assert contact_discovery_timeout == 5.0
        return RunReport(
            runner_version="0.1.0",
            generated_at="2026-06-03T00:00:00+00:00",
            mode="gazebo_sim",
            total=1,
            passed=1,
            failed=0,
            scenarios=[
                ScenarioRunResult(
                    scenario_id="straight_line_goal",
                    name="straight_line_goal",
                    path="examples/turtlebot3_gazebo/smoke.yaml",
                    tags=["smoke"],
                    status="passed",
                    step_count=1,
                    assertion_count=0,
                    duration_seconds=0.1,
                    steps=[],
                    assertions=[],
                    metrics={"simulator_started": True, "clock_ready": True},
                )
            ],
        )

    monkeypatch.setattr(cli, "run_doctor", fake_doctor)
    monkeypatch.setattr("nav2_scenario_runner.backends.gazebo_sim.run_gazebo_sim_lifecycle", fake_lifecycle)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--mode",
            "gazebo-sim",
            "--sim-startup-timeout",
            "0",
            "--wait-for-clock",
            "--clock-timeout",
            "2.5",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "GAZEBO-SIM PASS straight_line_goal" in captured.out
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert report["scenarios"][0]["metrics"]["clock_ready"] is True


def test_run_gazebo_sim_mode_passes_execute_nav2_option(tmp_path, capsys, monkeypatch):
    def fake_doctor(check_ros=False, check_gazebo=False):
        assert check_gazebo is True
        return DoctorReport(passed=True, checks=[], environment={})

    def fake_lifecycle(
        scenarios,
        report_dir,
        startup_timeout,
        preflight_skipped=False,
        wait_for_clock=False,
        clock_timeout=10.0,
        execute_nav2=False,
        launch_scenario_stack=False,
        wait_for_ros_graph=False,
        ros_graph_timeout=10.0,
        wait_for_nav2=False,
        nav2_timeout=30.0,
        wait_for_navigation_data=False,
        navigation_data_timeout=30.0,
        reset_world=False,
        world_reset_timeout=10.0,
        execute_simulator_steps=False,
        simulator_step_timeout=10.0,
        collect_contacts=False,
        contact_topics=None,
        contact_discovery_timeout=5.0,
    ):
        assert len(scenarios) == 1
        assert report_dir == tmp_path
        assert preflight_skipped is False
        assert wait_for_clock is False
        assert clock_timeout == 10.0
        assert execute_nav2 is True
        assert launch_scenario_stack is False
        assert wait_for_ros_graph is False
        assert ros_graph_timeout == 10.0
        assert wait_for_nav2 is False
        assert nav2_timeout == 30.0
        assert wait_for_navigation_data is False
        assert navigation_data_timeout == 30.0
        assert reset_world is False
        assert world_reset_timeout == 10.0
        assert execute_simulator_steps is False
        assert simulator_step_timeout == 10.0
        assert collect_contacts is False
        assert (contact_topics or []) == []
        assert contact_discovery_timeout == 5.0
        return RunReport(
            runner_version="0.1.0",
            generated_at="2026-06-03T00:00:00+00:00",
            mode="gazebo_sim",
            total=1,
            passed=1,
            failed=0,
            scenarios=[
                ScenarioRunResult(
                    scenario_id="straight_line_goal",
                    name="straight_line_goal",
                    path="examples/turtlebot3_gazebo/smoke.yaml",
                    tags=["smoke"],
                    status="passed",
                    step_count=1,
                    assertion_count=0,
                    duration_seconds=0.1,
                    steps=[],
                    assertions=[],
                    metrics={"simulator_started": True, "nav2_executed": True},
                )
            ],
        )

    monkeypatch.setattr(cli, "run_doctor", fake_doctor)
    monkeypatch.setattr("nav2_scenario_runner.backends.gazebo_sim.run_gazebo_sim_lifecycle", fake_lifecycle)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--mode",
            "gazebo-sim",
            "--execute-nav2",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "GAZEBO-SIM PASS straight_line_goal" in captured.out
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert report["scenarios"][0]["metrics"]["nav2_executed"] is True


def test_run_gazebo_sim_mode_passes_launch_stack_option(tmp_path, capsys, monkeypatch):
    def fake_doctor(check_ros=False, check_gazebo=False):
        assert check_gazebo is True
        return DoctorReport(passed=True, checks=[], environment={})

    def fake_lifecycle(
        scenarios,
        report_dir,
        startup_timeout,
        preflight_skipped=False,
        wait_for_clock=False,
        clock_timeout=10.0,
        execute_nav2=False,
        launch_scenario_stack=False,
        wait_for_ros_graph=False,
        ros_graph_timeout=10.0,
        wait_for_nav2=False,
        nav2_timeout=30.0,
        wait_for_navigation_data=False,
        navigation_data_timeout=30.0,
        reset_world=False,
        world_reset_timeout=10.0,
        execute_simulator_steps=False,
        simulator_step_timeout=10.0,
        collect_contacts=False,
        contact_topics=None,
        contact_discovery_timeout=5.0,
    ):
        assert len(scenarios) == 1
        assert report_dir == tmp_path
        assert preflight_skipped is False
        assert wait_for_clock is False
        assert clock_timeout == 10.0
        assert execute_nav2 is False
        assert launch_scenario_stack is True
        assert wait_for_ros_graph is False
        assert ros_graph_timeout == 10.0
        assert wait_for_nav2 is False
        assert nav2_timeout == 30.0
        assert wait_for_navigation_data is False
        assert navigation_data_timeout == 30.0
        assert reset_world is False
        assert world_reset_timeout == 10.0
        assert execute_simulator_steps is False
        assert simulator_step_timeout == 10.0
        assert collect_contacts is False
        assert (contact_topics or []) == []
        assert contact_discovery_timeout == 5.0
        return RunReport(
            runner_version="0.1.0",
            generated_at="2026-06-03T00:00:00+00:00",
            mode="gazebo_sim",
            total=1,
            passed=1,
            failed=0,
            scenarios=[
                ScenarioRunResult(
                    scenario_id="straight_line_goal",
                    name="straight_line_goal",
                    path="examples/turtlebot3_gazebo/smoke.yaml",
                    tags=["smoke"],
                    status="passed",
                    step_count=1,
                    assertion_count=0,
                    duration_seconds=0.1,
                    steps=[],
                    assertions=[],
                    metrics={"simulator_started": True, "launch_scenario_stack": True},
                )
            ],
        )

    monkeypatch.setattr(cli, "run_doctor", fake_doctor)
    monkeypatch.setattr("nav2_scenario_runner.backends.gazebo_sim.run_gazebo_sim_lifecycle", fake_lifecycle)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--mode",
            "gazebo-sim",
            "--launch-scenario-stack",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "GAZEBO-SIM PASS straight_line_goal" in captured.out
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert report["scenarios"][0]["metrics"]["launch_scenario_stack"] is True


def test_run_gazebo_sim_mode_passes_ros_graph_options(tmp_path, capsys, monkeypatch):
    def fake_doctor(check_ros=False, check_gazebo=False):
        assert check_gazebo is True
        return DoctorReport(passed=True, checks=[], environment={})

    def fake_lifecycle(
        scenarios,
        report_dir,
        startup_timeout,
        preflight_skipped=False,
        wait_for_clock=False,
        clock_timeout=10.0,
        execute_nav2=False,
        launch_scenario_stack=False,
        wait_for_ros_graph=False,
        ros_graph_timeout=10.0,
        wait_for_nav2=False,
        nav2_timeout=30.0,
        wait_for_navigation_data=False,
        navigation_data_timeout=30.0,
        reset_world=False,
        world_reset_timeout=10.0,
        execute_simulator_steps=False,
        simulator_step_timeout=10.0,
        collect_contacts=False,
        contact_topics=None,
        contact_discovery_timeout=5.0,
    ):
        assert len(scenarios) == 1
        assert report_dir == tmp_path
        assert preflight_skipped is False
        assert wait_for_clock is False
        assert clock_timeout == 10.0
        assert execute_nav2 is False
        assert launch_scenario_stack is False
        assert wait_for_ros_graph is True
        assert ros_graph_timeout == 4.5
        assert wait_for_nav2 is False
        assert nav2_timeout == 30.0
        assert wait_for_navigation_data is False
        assert navigation_data_timeout == 30.0
        assert reset_world is False
        assert world_reset_timeout == 10.0
        assert execute_simulator_steps is False
        assert simulator_step_timeout == 10.0
        assert collect_contacts is False
        assert (contact_topics or []) == []
        assert contact_discovery_timeout == 5.0
        return RunReport(
            runner_version="0.1.0",
            generated_at="2026-06-03T00:00:00+00:00",
            mode="gazebo_sim",
            total=1,
            passed=1,
            failed=0,
            scenarios=[
                ScenarioRunResult(
                    scenario_id="straight_line_goal",
                    name="straight_line_goal",
                    path="examples/turtlebot3_gazebo/smoke.yaml",
                    tags=["smoke"],
                    status="passed",
                    step_count=1,
                    assertion_count=0,
                    duration_seconds=0.1,
                    steps=[],
                    assertions=[],
                    metrics={"simulator_started": True, "ros_graph_ready": True},
                )
            ],
        )

    monkeypatch.setattr(cli, "run_doctor", fake_doctor)
    monkeypatch.setattr("nav2_scenario_runner.backends.gazebo_sim.run_gazebo_sim_lifecycle", fake_lifecycle)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--mode",
            "gazebo-sim",
            "--wait-for-ros-graph",
            "--ros-graph-timeout",
            "4.5",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "GAZEBO-SIM PASS straight_line_goal" in captured.out
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert report["scenarios"][0]["metrics"]["ros_graph_ready"] is True


def test_run_gazebo_sim_mode_passes_nav2_readiness_options(tmp_path, capsys, monkeypatch):
    def fake_doctor(check_ros=False, check_gazebo=False):
        assert check_gazebo is True
        return DoctorReport(passed=True, checks=[], environment={})

    def fake_lifecycle(
        scenarios,
        report_dir,
        startup_timeout,
        preflight_skipped=False,
        wait_for_clock=False,
        clock_timeout=10.0,
        execute_nav2=False,
        launch_scenario_stack=False,
        wait_for_ros_graph=False,
        ros_graph_timeout=10.0,
        wait_for_nav2=False,
        nav2_timeout=30.0,
        wait_for_navigation_data=False,
        navigation_data_timeout=30.0,
        reset_world=False,
        world_reset_timeout=10.0,
        execute_simulator_steps=False,
        simulator_step_timeout=10.0,
        collect_contacts=False,
        contact_topics=None,
        contact_discovery_timeout=5.0,
    ):
        assert len(scenarios) == 1
        assert report_dir == tmp_path
        assert preflight_skipped is False
        assert wait_for_clock is False
        assert clock_timeout == 10.0
        assert execute_nav2 is False
        assert launch_scenario_stack is False
        assert wait_for_ros_graph is False
        assert ros_graph_timeout == 10.0
        assert wait_for_nav2 is True
        assert nav2_timeout == 12.5
        assert wait_for_navigation_data is False
        assert navigation_data_timeout == 30.0
        assert reset_world is False
        assert world_reset_timeout == 10.0
        assert execute_simulator_steps is False
        assert simulator_step_timeout == 10.0
        assert collect_contacts is False
        assert (contact_topics or []) == []
        assert contact_discovery_timeout == 5.0
        return RunReport(
            runner_version="0.1.0",
            generated_at="2026-06-03T00:00:00+00:00",
            mode="gazebo_sim",
            total=1,
            passed=1,
            failed=0,
            scenarios=[
                ScenarioRunResult(
                    scenario_id="straight_line_goal",
                    name="straight_line_goal",
                    path="examples/turtlebot3_gazebo/smoke.yaml",
                    tags=["smoke"],
                    status="passed",
                    step_count=1,
                    assertion_count=0,
                    duration_seconds=0.1,
                    steps=[],
                    assertions=[],
                    metrics={"simulator_started": True, "nav2_ready": True},
                )
            ],
        )

    monkeypatch.setattr(cli, "run_doctor", fake_doctor)
    monkeypatch.setattr("nav2_scenario_runner.backends.gazebo_sim.run_gazebo_sim_lifecycle", fake_lifecycle)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--mode",
            "gazebo-sim",
            "--wait-for-nav2",
            "--nav2-timeout",
            "12.5",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "GAZEBO-SIM PASS straight_line_goal" in captured.out
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert report["scenarios"][0]["metrics"]["nav2_ready"] is True


def test_run_gazebo_sim_mode_passes_navigation_data_options(tmp_path, capsys, monkeypatch):
    def fake_doctor(check_ros=False, check_gazebo=False):
        assert check_gazebo is True
        return DoctorReport(passed=True, checks=[], environment={})

    def fake_lifecycle(
        scenarios,
        report_dir,
        startup_timeout,
        preflight_skipped=False,
        wait_for_clock=False,
        clock_timeout=10.0,
        execute_nav2=False,
        launch_scenario_stack=False,
        wait_for_ros_graph=False,
        ros_graph_timeout=10.0,
        wait_for_nav2=False,
        nav2_timeout=30.0,
        wait_for_navigation_data=False,
        navigation_data_timeout=30.0,
        reset_world=False,
        world_reset_timeout=10.0,
        execute_simulator_steps=False,
        simulator_step_timeout=10.0,
        collect_contacts=False,
        contact_topics=None,
        contact_discovery_timeout=5.0,
    ):
        assert len(scenarios) == 1
        assert report_dir == tmp_path
        assert preflight_skipped is False
        assert wait_for_clock is False
        assert clock_timeout == 10.0
        assert execute_nav2 is False
        assert launch_scenario_stack is False
        assert wait_for_ros_graph is False
        assert ros_graph_timeout == 10.0
        assert wait_for_nav2 is False
        assert nav2_timeout == 30.0
        assert wait_for_navigation_data is True
        assert navigation_data_timeout == 15.0
        assert reset_world is False
        assert world_reset_timeout == 10.0
        assert execute_simulator_steps is False
        assert simulator_step_timeout == 10.0
        assert collect_contacts is False
        assert (contact_topics or []) == []
        assert contact_discovery_timeout == 5.0
        return RunReport(
            runner_version="0.1.0",
            generated_at="2026-06-03T00:00:00+00:00",
            mode="gazebo_sim",
            total=1,
            passed=1,
            failed=0,
            scenarios=[
                ScenarioRunResult(
                    scenario_id="straight_line_goal",
                    name="straight_line_goal",
                    path="examples/turtlebot3_gazebo/smoke.yaml",
                    tags=["smoke"],
                    status="passed",
                    step_count=1,
                    assertion_count=0,
                    duration_seconds=0.1,
                    steps=[],
                    assertions=[],
                    metrics={"simulator_started": True, "navigation_data_ready": True},
                )
            ],
        )

    monkeypatch.setattr(cli, "run_doctor", fake_doctor)
    monkeypatch.setattr("nav2_scenario_runner.backends.gazebo_sim.run_gazebo_sim_lifecycle", fake_lifecycle)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--mode",
            "gazebo-sim",
            "--wait-for-navigation-data",
            "--navigation-data-timeout",
            "15",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "GAZEBO-SIM PASS straight_line_goal" in captured.out
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert report["scenarios"][0]["metrics"]["navigation_data_ready"] is True


def test_run_gazebo_sim_mode_passes_world_reset_options(tmp_path, capsys, monkeypatch):
    def fake_doctor(check_ros=False, check_gazebo=False):
        assert check_gazebo is True
        return DoctorReport(passed=True, checks=[], environment={})

    def fake_lifecycle(
        scenarios,
        report_dir,
        startup_timeout,
        preflight_skipped=False,
        wait_for_clock=False,
        clock_timeout=10.0,
        execute_nav2=False,
        launch_scenario_stack=False,
        wait_for_ros_graph=False,
        ros_graph_timeout=10.0,
        wait_for_nav2=False,
        nav2_timeout=30.0,
        wait_for_navigation_data=False,
        navigation_data_timeout=30.0,
        reset_world=False,
        world_reset_timeout=10.0,
        execute_simulator_steps=False,
        simulator_step_timeout=10.0,
        collect_contacts=False,
        contact_topics=None,
        contact_discovery_timeout=5.0,
    ):
        assert len(scenarios) == 1
        assert report_dir == tmp_path
        assert preflight_skipped is False
        assert wait_for_clock is False
        assert clock_timeout == 10.0
        assert execute_nav2 is False
        assert launch_scenario_stack is False
        assert wait_for_ros_graph is False
        assert ros_graph_timeout == 10.0
        assert wait_for_nav2 is False
        assert nav2_timeout == 30.0
        assert wait_for_navigation_data is False
        assert navigation_data_timeout == 30.0
        assert reset_world is True
        assert world_reset_timeout == 7.5
        assert execute_simulator_steps is False
        assert simulator_step_timeout == 10.0
        assert collect_contacts is False
        assert (contact_topics or []) == []
        assert contact_discovery_timeout == 5.0
        return RunReport(
            runner_version="0.1.0",
            generated_at="2026-06-03T00:00:00+00:00",
            mode="gazebo_sim",
            total=1,
            passed=1,
            failed=0,
            scenarios=[
                ScenarioRunResult(
                    scenario_id="straight_line_goal",
                    name="straight_line_goal",
                    path="examples/turtlebot3_gazebo/smoke.yaml",
                    tags=["smoke"],
                    status="passed",
                    step_count=1,
                    assertion_count=0,
                    duration_seconds=0.1,
                    steps=[],
                    assertions=[],
                    metrics={"simulator_started": True, "world_reset_succeeded": True},
                )
            ],
        )

    monkeypatch.setattr(cli, "run_doctor", fake_doctor)
    monkeypatch.setattr("nav2_scenario_runner.backends.gazebo_sim.run_gazebo_sim_lifecycle", fake_lifecycle)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--mode",
            "gazebo-sim",
            "--reset-world",
            "--world-reset-timeout",
            "7.5",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "GAZEBO-SIM PASS straight_line_goal" in captured.out
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert report["scenarios"][0]["metrics"]["world_reset_succeeded"] is True


def test_run_gazebo_sim_mode_passes_simulator_step_options(tmp_path, capsys, monkeypatch):
    def fake_doctor(check_ros=False, check_gazebo=False):
        assert check_gazebo is True
        return DoctorReport(passed=True, checks=[], environment={})

    def fake_lifecycle(
        scenarios,
        report_dir,
        startup_timeout,
        preflight_skipped=False,
        wait_for_clock=False,
        clock_timeout=10.0,
        execute_nav2=False,
        launch_scenario_stack=False,
        wait_for_ros_graph=False,
        ros_graph_timeout=10.0,
        wait_for_nav2=False,
        nav2_timeout=30.0,
        wait_for_navigation_data=False,
        navigation_data_timeout=30.0,
        reset_world=False,
        world_reset_timeout=10.0,
        execute_simulator_steps=False,
        simulator_step_timeout=10.0,
        collect_contacts=False,
        contact_topics=None,
        contact_discovery_timeout=5.0,
    ):
        assert len(scenarios) == 1
        assert report_dir == tmp_path
        assert preflight_skipped is False
        assert wait_for_clock is False
        assert clock_timeout == 10.0
        assert execute_nav2 is False
        assert launch_scenario_stack is False
        assert wait_for_ros_graph is False
        assert ros_graph_timeout == 10.0
        assert wait_for_nav2 is False
        assert nav2_timeout == 30.0
        assert wait_for_navigation_data is False
        assert navigation_data_timeout == 30.0
        assert reset_world is False
        assert world_reset_timeout == 10.0
        assert execute_simulator_steps is True
        assert simulator_step_timeout == 6.5
        assert collect_contacts is False
        assert (contact_topics or []) == []
        assert contact_discovery_timeout == 5.0
        return RunReport(
            runner_version="0.1.0",
            generated_at="2026-06-03T00:00:00+00:00",
            mode="gazebo_sim",
            total=1,
            passed=1,
            failed=0,
            scenarios=[
                ScenarioRunResult(
                    scenario_id="straight_line_goal",
                    name="straight_line_goal",
                    path="examples/turtlebot3_gazebo/smoke.yaml",
                    tags=["smoke"],
                    status="passed",
                    step_count=1,
                    assertion_count=0,
                    duration_seconds=0.1,
                    steps=[],
                    assertions=[],
                    metrics={"simulator_started": True, "simulator_steps_executed": 1},
                )
            ],
        )

    monkeypatch.setattr(cli, "run_doctor", fake_doctor)
    monkeypatch.setattr("nav2_scenario_runner.backends.gazebo_sim.run_gazebo_sim_lifecycle", fake_lifecycle)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--mode",
            "gazebo-sim",
            "--execute-simulator-steps",
            "--simulator-step-timeout",
            "6.5",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "GAZEBO-SIM PASS straight_line_goal" in captured.out
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert report["scenarios"][0]["metrics"]["simulator_steps_executed"] == 1


def test_run_gazebo_sim_mode_passes_contact_collection_options(tmp_path, capsys, monkeypatch):
    def fake_doctor(check_ros=False, check_gazebo=False):
        assert check_gazebo is True
        return DoctorReport(passed=True, checks=[], environment={})

    def fake_lifecycle(
        scenarios,
        report_dir,
        startup_timeout,
        preflight_skipped=False,
        wait_for_clock=False,
        clock_timeout=10.0,
        execute_nav2=False,
        launch_scenario_stack=False,
        wait_for_ros_graph=False,
        ros_graph_timeout=10.0,
        wait_for_nav2=False,
        nav2_timeout=30.0,
        wait_for_navigation_data=False,
        navigation_data_timeout=30.0,
        reset_world=False,
        world_reset_timeout=10.0,
        execute_simulator_steps=False,
        simulator_step_timeout=10.0,
        collect_contacts=False,
        contact_topics=None,
        contact_discovery_timeout=5.0,
    ):
        assert len(scenarios) == 1
        assert report_dir == tmp_path
        assert preflight_skipped is False
        assert wait_for_clock is False
        assert clock_timeout == 10.0
        assert execute_nav2 is False
        assert launch_scenario_stack is False
        assert wait_for_ros_graph is False
        assert ros_graph_timeout == 10.0
        assert wait_for_nav2 is False
        assert nav2_timeout == 30.0
        assert wait_for_navigation_data is False
        assert navigation_data_timeout == 30.0
        assert reset_world is False
        assert world_reset_timeout == 10.0
        assert execute_simulator_steps is False
        assert simulator_step_timeout == 10.0
        assert collect_contacts is True
        assert contact_topics == ["/contacts", "/contacts2"]
        assert contact_discovery_timeout == 2.5
        return RunReport(
            runner_version="0.1.0",
            generated_at="2026-06-03T00:00:00+00:00",
            mode="gazebo_sim",
            total=1,
            passed=1,
            failed=0,
            scenarios=[
                ScenarioRunResult(
                    scenario_id="straight_line_goal",
                    name="straight_line_goal",
                    path="examples/turtlebot3_gazebo/smoke.yaml",
                    tags=["smoke"],
                    status="passed",
                    step_count=1,
                    assertion_count=0,
                    duration_seconds=0.1,
                    steps=[],
                    assertions=[],
                    metrics={"simulator_started": True, "collision_count": 0, "collision_free": True},
                )
            ],
        )

    monkeypatch.setattr(cli, "run_doctor", fake_doctor)
    monkeypatch.setattr("nav2_scenario_runner.backends.gazebo_sim.run_gazebo_sim_lifecycle", fake_lifecycle)

    exit_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--mode",
            "gazebo-sim",
            "--collect-contacts",
            "--contact-topic",
            "/contacts",
            "--contact-topic",
            "/contacts2",
            "--contact-discovery-timeout",
            "2.5",
            "--report-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "GAZEBO-SIM PASS straight_line_goal" in captured.out
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert report["scenarios"][0]["metrics"]["collision_free"] is True


def test_report_cli_renders_generated_json_report(tmp_path, capsys):
    run_code = main(
        [
            "run",
            "examples/turtlebot3_gazebo/smoke.yaml",
            "--dry-run",
            "--report-dir",
            str(tmp_path),
        ]
    )
    capsys.readouterr()
    assert run_code == 0

    exit_code = main(["report", str(tmp_path / "results.json")])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Report PASS: mode=dry_run total=1 passed=1 failed=0" in captured.out
    assert "straight_line_goal status=dry_run_passed" in captured.out


def test_report_cli_writes_markdown_and_can_fail_on_failed_report(tmp_path, capsys):
    report_path = tmp_path / "results.json"
    output_path = tmp_path / "summary.md"
    report_path.write_text(
        json.dumps(
            {
                "mode": "attach",
                "total": 1,
                "passed": 0,
                "failed": 1,
                "scenarios": [
                    {
                        "scenario_id": "blocked_path",
                        "name": "blocked_path",
                        "status": "failed",
                        "duration_seconds": 30.0,
                        "failure_reason": "timeout after 30s",
                        "metrics": {"travel_time": 30.0, "collision_free": True},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "report",
            str(report_path),
            "--format",
            "markdown",
            "--output",
            str(output_path),
            "--fail-on-failure",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert f"Report summary: {output_path}" in captured.out

    markdown = output_path.read_text(encoding="utf-8")
    assert "# Nav2 Scenario Report" in markdown
    assert "- Result: `FAIL`" in markdown
    assert "- Reason: timeout after 30s" in markdown


def test_report_cli_writes_html_report(tmp_path, capsys):
    report_path = tmp_path / "results.json"
    output_path = tmp_path / "index.html"
    report_path.write_text(
        json.dumps(
            {
                "mode": "attach",
                "total": 1,
                "passed": 1,
                "failed": 0,
                "scenarios": [
                    {
                        "scenario_id": "straight_line_goal",
                        "status": "passed",
                        "duration_seconds": 12.4,
                        "metrics": {
                            "travel_time": 12.4,
                            "path_length_traveled": 10.8,
                            "collision_free": True,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["report", str(report_path), "--format", "html", "--output", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"Report summary: {output_path}" in captured.out

    html = output_path.read_text(encoding="utf-8")
    assert "<!doctype html>" in html
    assert "Nav2 Scenario Report" in html
    assert "straight_line_goal" in html
    assert "<td class=\"num\">10.8</td>" in html


def test_report_cli_appends_github_step_summary(tmp_path, capsys, monkeypatch):
    report_path = tmp_path / "results.json"
    summary_path = tmp_path / "github_summary.md"
    report_path.write_text(
        json.dumps(
            {
                "mode": "dry_run",
                "total": 1,
                "passed": 1,
                "failed": 0,
                "scenarios": [
                    {
                        "scenario_id": "straight_line_goal",
                        "name": "straight_line_goal",
                        "status": "dry_run_passed",
                        "duration_seconds": 0.0,
                        "metrics": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    summary_path.write_text("existing summary\n\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    exit_code = main(["report", str(report_path), "--github-summary"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Report PASS: mode=dry_run total=1 passed=1 failed=0" in captured.out
    assert f"GitHub summary: {summary_path}" in captured.out

    summary = summary_path.read_text(encoding="utf-8")
    assert summary.startswith("existing summary\n\n")
    assert "# Nav2 Scenario Report" in summary
    assert "| straight_line_goal | dry_run_passed | 0.000s | - | - | - | - | - |" in summary


def test_report_cli_requires_github_summary_environment(tmp_path, capsys, monkeypatch):
    report_path = tmp_path / "results.json"
    report_path.write_text(json.dumps({"scenarios": []}), encoding="utf-8")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    exit_code = main(["report", str(report_path), "--github-summary"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "GITHUB_STEP_SUMMARY is not set" in captured.err


def test_lint_rejects_invalid_yaml(tmp_path, capsys):
    bad_scenario = tmp_path / "bad.yaml"
    bad_scenario.write_text("apiVersion: wrong\nkind: Scenario\n", encoding="utf-8")

    exit_code = main(["lint", str(bad_scenario)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "FAIL" in captured.out
    assert "apiVersion" in captured.out


def test_init_creates_starter_project(tmp_path, capsys):
    exit_code = main(["init", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Initialized" in captured.out

    scenario_path = tmp_path / "scenarios/smoke.yaml"
    world_path = tmp_path / "scenarios/worlds/empty.sdf"
    workflow_path = tmp_path / ".github/workflows/nav2_scenario_tests.yaml"
    assert scenario_path.exists()
    assert world_path.exists()
    assert workflow_path.exists()
    assert "world: worlds/empty.sdf" in scenario_path.read_text(encoding="utf-8")
    assert "<world name=\"empty\">" in world_path.read_text(encoding="utf-8")
    workflow = workflow_path.read_text(encoding="utf-8")
    assert "nav2_scenario_runner run scenarios/" in workflow
    assert "--trace-report trace.json" in workflow
    assert "--html-report index.html" in workflow
    assert "--github-summary" in workflow
    assert workflow.count("if: always()") == 1

    lint_code = main(["lint", str(tmp_path / "scenarios")])
    lint_output = capsys.readouterr()
    assert lint_code == 0
    assert f"OK   {scenario_path}" in lint_output.out

    run_code = main(["run", str(tmp_path / "scenarios"), "--dry-run", "--report-dir", str(tmp_path / "reports")])
    run_output = capsys.readouterr()
    assert run_code == 0
    assert "DRY-RUN PASS straight_line_goal" in run_output.out
    assert (tmp_path / "reports/results.json").exists()
    assert (tmp_path / "reports/junit.xml").exists()


def test_init_refuses_overwrite_without_force(tmp_path, capsys):
    scenario_dir = tmp_path / "scenarios"
    scenario_dir.mkdir()
    existing = scenario_dir / "smoke.yaml"
    existing.write_text("already here\n", encoding="utf-8")

    exit_code = main(["init", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Refusing to overwrite existing files" in captured.err
    assert existing.read_text(encoding="utf-8") == "already here\n"

    force_code = main(["init", str(tmp_path), "--force"])
    force_output = capsys.readouterr()
    assert force_code == 0
    assert "Initialized" in force_output.out
    assert "apiVersion: nav2.scenario/v1alpha1" in existing.read_text(encoding="utf-8")


def test_doctor_cli_writes_json_report(tmp_path, capsys):
    report_path = tmp_path / "doctor.json"

    exit_code = main(["doctor", "--json", str(report_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Doctor PASS" in captured.out
    assert report_path.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert any(check["name"] == "schema.v1alpha1" for check in report["checks"])
    assert "python_version" in report["environment"]


def test_compare_cli_writes_report_and_fails_on_metric_regression(tmp_path, capsys, monkeypatch):
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    output = tmp_path / "compare.json"
    markdown_output = tmp_path / "compare.md"
    github_summary = tmp_path / "github_summary.md"
    github_summary.write_text("existing\n\n", encoding="utf-8")
    baseline.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario_id": "straight_line_goal",
                        "name": "straight_line_goal",
                        "status": "passed",
                        "metrics": {"travel_time": 10.0},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    current.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario_id": "straight_line_goal",
                        "name": "straight_line_goal",
                        "status": "passed",
                        "metrics": {"travel_time": 13.0},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(github_summary))
    exit_code = main(
        [
            "compare",
            str(current),
            "--baseline",
            str(baseline),
            "--max-increase-percent",
            "travel_time=20",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown_output),
            "--github-summary",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Compare FAIL" in captured.out
    assert "travel_time increased" in captured.out
    assert f"Compare Markdown: {markdown_output}" in captured.out
    assert f"Compare GitHub summary: {github_summary}" in captured.out

    compare_report = json.loads(output.read_text(encoding="utf-8"))
    assert not compare_report["passed"]
    assert compare_report["issues"][0]["kind"] == "metric_regression"

    markdown = markdown_output.read_text(encoding="utf-8")
    summary = github_summary.read_text(encoding="utf-8")
    assert "# Nav2 Scenario Regression" in markdown
    assert "- Result: `FAIL`" in markdown
    assert "travel_time increased" in markdown
    assert summary.startswith("existing\n\n")
    assert "# Nav2 Scenario Regression" in summary
