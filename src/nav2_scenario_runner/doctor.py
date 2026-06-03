from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


REQUIRED_PYTHON_MODULES = ["yaml", "jsonschema"]
ROS_MODULES = [
    "rclpy",
    "action_msgs.msg",
    "geometry_msgs.msg",
    "nav2_msgs.action",
    "nav_msgs.msg",
]
GAZEBO_ROS_PACKAGES = ["ros_gz_bridge"]


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    required: bool
    message: str


@dataclass(frozen=True)
class DoctorReport:
    passed: bool
    checks: list[DoctorCheck]
    environment: dict[str, str | None]


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
ExecutableFinder = Callable[[str], str | None]


def run_doctor(
    check_ros: bool = False,
    check_gazebo: bool = False,
    check_ros_graph: bool = False,
    command_runner: CommandRunner | None = None,
    executable_finder: ExecutableFinder | None = None,
) -> DoctorReport:
    command_runner = command_runner or _run_command
    executable_finder = executable_finder or shutil.which
    checks: list[DoctorCheck] = [
        DoctorCheck(
            name="python.version",
            status="pass",
            required=True,
            message=f"{platform.python_version()} ({sys.executable})",
        )
    ]

    checks.extend(_module_checks(REQUIRED_PYTHON_MODULES, required=True, group="python"))
    checks.append(_schema_check())
    checks.extend(_module_checks(ROS_MODULES, required=check_ros, group="ros"))
    if check_gazebo:
        checks.extend(_gazebo_checks(command_runner=command_runner, executable_finder=executable_finder))
    if check_ros_graph:
        checks.extend(_ros_graph_checks(command_runner=command_runner, executable_finder=executable_finder))

    passed = all(check.status == "pass" for check in checks if check.required)
    return DoctorReport(passed=passed, checks=checks, environment=_environment())


def write_doctor_report(report: DoctorReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")


def _module_checks(module_names: list[str], required: bool, group: str) -> list[DoctorCheck]:
    checks = []
    for module_name in module_names:
        found = _module_is_available(module_name)
        status = "pass" if found else ("fail" if required else "warn")
        requirement = "required" if required else "optional"
        message = "importable" if found else f"not importable ({requirement})"
        checks.append(
            DoctorCheck(
                name=f"{group}.{module_name}",
                status=status,
                required=required,
                message=message,
            )
        )
    return checks


def _module_is_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _schema_check() -> DoctorCheck:
    from .schema import default_schema_path

    schema_path = default_schema_path()
    exists = schema_path.exists()
    return DoctorCheck(
        name="schema.v1alpha1",
        status="pass" if exists else "fail",
        required=True,
        message=str(schema_path) if exists else f"not found: {schema_path}",
    )


def _gazebo_checks(command_runner: CommandRunner, executable_finder: ExecutableFinder) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    gz_path = executable_finder("gz")
    checks.append(
        DoctorCheck(
            name="gazebo.gz",
            status="pass" if gz_path else "fail",
            required=True,
            message=gz_path or "gz executable not found on PATH",
        )
    )
    if gz_path:
        checks.append(
            _command_check(
                name="gazebo.gz_sim",
                command=["gz", "sim", "--help"],
                command_runner=command_runner,
                success_message="gz sim is available",
            )
        )

    ros2_path = executable_finder("ros2")
    checks.append(
        DoctorCheck(
            name="gazebo.ros2",
            status="pass" if ros2_path else "fail",
            required=True,
            message=ros2_path or "ros2 executable not found on PATH",
        )
    )
    if ros2_path:
        for package_name in GAZEBO_ROS_PACKAGES:
            checks.append(
                _command_check(
                    name=f"gazebo.{package_name}",
                    command=["ros2", "pkg", "prefix", package_name],
                    command_runner=command_runner,
                    success_message=f"{package_name} package is available",
                )
            )
    return checks


def _ros_graph_checks(command_runner: CommandRunner, executable_finder: ExecutableFinder) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    ros2_path = executable_finder("ros2")
    checks.append(
        DoctorCheck(
            name="ros_graph.ros2",
            status="pass" if ros2_path else "fail",
            required=True,
            message=ros2_path or "ros2 executable not found on PATH",
        )
    )
    if ros2_path:
        checks.append(
            _command_check(
                name="ros_graph.node_list",
                command=["ros2", "node", "list"],
                command_runner=command_runner,
                success_message="ros2 node list succeeded",
            )
        )
        checks.append(
            _command_check(
                name="ros_graph.topic_list",
                command=["ros2", "topic", "list"],
                command_runner=command_runner,
                success_message="ros2 topic list succeeded",
            )
        )
    return checks


def _command_check(
    name: str,
    command: list[str],
    command_runner: CommandRunner,
    success_message: str,
) -> DoctorCheck:
    try:
        result = command_runner(command)
    except (OSError, subprocess.SubprocessError) as exc:
        return DoctorCheck(
            name=name,
            status="fail",
            required=True,
            message=str(exc),
        )

    output = (result.stdout or result.stderr or "").strip()
    if result.returncode == 0:
        return DoctorCheck(
            name=name,
            status="pass",
            required=True,
            message=output.splitlines()[0] if output else success_message,
        )
    return DoctorCheck(
        name=name,
        status="fail",
        required=True,
        message=output.splitlines()[0] if output else f"command failed: {' '.join(command)}",
    )


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)


def _environment() -> dict[str, str | None]:
    return {
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "ros_distro": os.environ.get("ROS_DISTRO"),
        "ros_domain_id": os.environ.get("ROS_DOMAIN_ID"),
        "rmw_implementation": os.environ.get("RMW_IMPLEMENTATION"),
    }
