from __future__ import annotations

import subprocess

from nav2_scenario_runner.doctor import run_doctor


def test_doctor_required_checks_pass_without_ros_requirement():
    report = run_doctor(check_ros=False)

    assert report.passed
    assert any(check.name == "python.yaml" and check.status == "pass" for check in report.checks)
    assert any(check.name == "python.jsonschema" and check.status == "pass" for check in report.checks)
    assert any(check.name == "schema.v1alpha1" and check.status == "pass" for check in report.checks)
    ros_checks = [check for check in report.checks if check.name.startswith("ros.")]
    assert ros_checks
    assert all(not check.required for check in ros_checks)
    assert not any(check.name.startswith("gazebo.") for check in report.checks)


def test_doctor_can_require_ros_modules():
    report = run_doctor(check_ros=True)

    ros_checks = [check for check in report.checks if check.name.startswith("ros.")]
    assert ros_checks
    assert all(check.required for check in ros_checks)
    if any(check.status == "fail" for check in ros_checks):
        assert not report.passed


def test_doctor_can_require_gazebo_preflight_with_injected_commands():
    commands = []

    def finder(name: str) -> str | None:
        if name in {"gz", "ros2"}:
            return f"/usr/bin/{name}"
        return None

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    report = run_doctor(
        check_gazebo=True,
        command_runner=runner,
        executable_finder=finder,
    )

    gazebo_checks = [check for check in report.checks if check.name.startswith("gazebo.")]
    assert report.passed
    assert {check.name for check in gazebo_checks} == {
        "gazebo.gz",
        "gazebo.gz_sim",
        "gazebo.ros2",
        "gazebo.ros_gz_bridge",
    }
    assert all(check.required for check in gazebo_checks)
    assert all(check.status == "pass" for check in gazebo_checks)
    assert commands == [["gz", "sim", "--help"], ["ros2", "pkg", "prefix", "ros_gz_bridge"]]


def test_doctor_gazebo_preflight_fails_when_commands_are_missing():
    def finder(name: str) -> str | None:
        return None

    report = run_doctor(check_gazebo=True, executable_finder=finder)

    gazebo_checks = [check for check in report.checks if check.name.startswith("gazebo.")]
    assert not report.passed
    assert {check.name for check in gazebo_checks} == {"gazebo.gz", "gazebo.ros2"}
    assert all(check.required for check in gazebo_checks)
    assert all(check.status == "fail" for check in gazebo_checks)


def test_doctor_can_require_ros_graph_with_injected_commands():
    commands = []

    def finder(name: str) -> str | None:
        return "/usr/bin/ros2" if name == "ros2" else None

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="/clock\n", stderr="")

    report = run_doctor(
        check_ros_graph=True,
        command_runner=runner,
        executable_finder=finder,
    )

    graph_checks = [check for check in report.checks if check.name.startswith("ros_graph.")]
    assert report.passed
    assert {check.name for check in graph_checks} == {
        "ros_graph.ros2",
        "ros_graph.node_list",
        "ros_graph.topic_list",
    }
    assert all(check.required for check in graph_checks)
    assert all(check.status == "pass" for check in graph_checks)
    assert commands == [["ros2", "node", "list"], ["ros2", "topic", "list"]]


def test_doctor_ros_graph_fails_without_ros2_cli():
    def finder(name: str) -> str | None:
        return None

    report = run_doctor(check_ros_graph=True, executable_finder=finder)

    graph_checks = [check for check in report.checks if check.name.startswith("ros_graph.")]
    assert not report.passed
    assert {check.name for check in graph_checks} == {"ros_graph.ros2"}
    assert graph_checks[0].status == "fail"
