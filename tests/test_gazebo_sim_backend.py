from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from nav2_scenario_runner.backends.fake import FakeNav2Backend
from nav2_scenario_runner.backends.gazebo_sim import (
    GazeboSimError,
    gazebo_delete_entity_command,
    gazebo_set_entity_pose_command,
    gazebo_sim_command,
    gazebo_spawn_obstacle_command,
    gazebo_world_reset_command,
    run_gazebo_sim_lifecycle,
)
from nav2_scenario_runner.execution import StepExecutionError
from nav2_scenario_runner.scenario import Scenario


class FakeProcess:
    def __init__(self, return_code: int | None = None):
        self.return_code = return_code
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True
        self.return_code = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.return_code or 0

    def kill(self) -> None:
        self.killed = True
        self.return_code = -9


class UnavailableNav2Backend(FakeNav2Backend):
    def wait_for_nav2_active(self, timeout: float) -> None:
        self.operations.append(f"wait_for_nav2_active:{timeout:g}")
        raise StepExecutionError(f"Nav2 NavigateToPose action server not available after {timeout:g}s")


def test_gazebo_sim_command_uses_headless_server_mode(tmp_path):
    world = tmp_path / "worlds/empty.sdf"
    world.parent.mkdir()
    world.write_text("<sdf version='1.9'></sdf>\n", encoding="utf-8")
    scenario = _scenario(tmp_path / "smoke.yaml", world="worlds/empty.sdf", headless=True)

    command = gazebo_sim_command(scenario)

    assert command == ["gz", "sim", "-s", str(world)]


def test_gazebo_world_reset_command_uses_sdf_world_name(tmp_path):
    _write_world(tmp_path / "worlds/renamed_file.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml", world="worlds/renamed_file.sdf")

    command = gazebo_world_reset_command(scenario, timeout=7.5)

    assert command == [
        "gz",
        "service",
        "-s",
        "/world/empty/control",
        "--reqtype",
        "gz.msgs.WorldControl",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        "7500",
        "--req",
        "reset: {all: true}",
    ]


def test_gazebo_spawn_obstacle_command_creates_box_sdf_request(tmp_path):
    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")

    command = gazebo_spawn_obstacle_command(
        scenario,
        {
            "name": "crate_1",
            "type": "box",
            "pose": {"x": 2.0, "y": -0.5, "yaw": 1.57},
            "size": {"x": 0.8, "y": 0.6, "z": 1.2},
        },
        timeout=6.5,
    )

    assert command[:10] == [
        "gz",
        "service",
        "-s",
        "/world/empty/create",
        "--reqtype",
        "gz.msgs.EntityFactory",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        "6500",
    ]
    assert command[10] == "--req"
    assert command[11].startswith('sdf: "')
    assert '<model name=\\"crate_1\\">' in command[11]
    assert "<pose>2 -0.5 0.6 0 0 1.57</pose>" in command[11]
    assert "<size>0.8 0.6 1.2</size>" in command[11]


def test_gazebo_delete_entity_command_targets_model_remove_service(tmp_path):
    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")

    command = gazebo_delete_entity_command(scenario, {"name": "crate_1"}, timeout=4.0)

    assert command == [
        "gz",
        "service",
        "-s",
        "/world/empty/remove",
        "--reqtype",
        "gz.msgs.Entity",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        "4000",
        "--req",
        'name: "crate_1" type: MODEL',
    ]


def test_gazebo_set_entity_pose_command_targets_world_set_pose(tmp_path):
    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")

    command = gazebo_set_entity_pose_command(
        scenario,
        name="crate_1",
        pose={"x": 2.0, "y": -0.5, "yaw": 1.57079632679},
        timeout=4.0,
        default_z=0.6,
    )

    assert command == [
        "gz",
        "service",
        "-s",
        "/world/empty/set_pose",
        "--reqtype",
        "gz.msgs.Pose",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        "4000",
        "--req",
        (
            'name: "crate_1" '
            "position: {x: 2 y: -0.5 z: 0.6} "
            "orientation: {x: 0 y: 0 z: 0.707107 w: 0.707107}"
        ),
    ]


def test_gazebo_sim_lifecycle_starts_logs_and_stops_process(tmp_path):
    processes: list[FakeProcess] = []
    commands = []

    def process_factory(command, **kwargs):
        commands.append((command, kwargs))
        process = FakeProcess(return_code=None)
        processes.append(process)
        return process

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        preflight_skipped=True,
        process_factory=process_factory,
    )

    assert report.mode == "gazebo_sim"
    assert report.passed == 1
    assert report.failed == 0
    result = report.scenarios[0]
    assert result.status == "passed"
    assert result.steps[0].kind == "gazebo_sim.launch"
    assert result.metrics["simulator_started"] is True
    assert result.metrics["preflight_skipped"] is True
    assert result.metrics["error_type"] == ""
    assert result.metrics["simulator_command"] == f"gz sim -s {tmp_path / 'worlds/empty.sdf'}"
    artifact_dir = Path(result.metrics["artifact_dir"])
    gazebo_log = artifact_dir / "gazebo.log"
    scenario_copy = artifact_dir / "scenario.yaml"
    metadata_path = artifact_dir / "metadata.json"
    assert result.metrics["gazebo_log"] == str(gazebo_log)
    assert result.metrics["simulator_log"] == str(gazebo_log)
    assert result.metrics["scenario_copy"] == str(scenario_copy)
    assert result.metrics["metadata"] == str(metadata_path)
    assert result.metrics["world"] == str(tmp_path / "worlds/empty.sdf")
    assert gazebo_log.exists()
    assert scenario_copy.exists()
    assert metadata_path.exists()
    assert f"command: gz sim -s {tmp_path / 'worlds/empty.sdf'}" in gazebo_log.read_text(encoding="utf-8")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["scenario_id"] == "straight_line_goal"
    assert metadata["status"] == "passed"
    assert metadata["error_type"] is None
    assert metadata["preflight_skipped"] is True
    assert metadata["command"] == ["gz", "sim", "-s", str(tmp_path / "worlds/empty.sdf")]
    assert metadata["world"] == str(tmp_path / "worlds/empty.sdf")
    assert metadata["exit_code"] == 0
    assert metadata["world_reset_requested"] is False
    assert metadata["world_reset_command"] is None
    assert metadata["world_reset_timeout"] is None
    assert metadata["world_reset_succeeded"] is None
    assert metadata["world_reset_error"] is None
    assert processes[0].terminated
    assert commands[0][0] == ["gz", "sim", "-s", str(tmp_path / "worlds/empty.sdf")]


def test_gazebo_sim_lifecycle_can_reset_world(tmp_path):
    reset_commands = []

    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        reset_commands.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, stdout="true\n", stderr="")

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        reset_world=True,
        world_reset_timeout=7.5,
        process_factory=process_factory,
        command_runner=command_runner,
    )

    result = report.scenarios[0]
    expected_command = [
        "gz",
        "service",
        "-s",
        "/world/empty/control",
        "--reqtype",
        "gz.msgs.WorldControl",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        "7500",
        "--req",
        "reset: {all: true}",
    ]
    assert result.status == "passed"
    assert [step.kind for step in result.steps or []] == ["gazebo_sim.launch", "gazebo_sim.reset_world"]
    assert result.steps[1].status == "passed"
    assert reset_commands == [(expected_command, 7.5)]
    assert result.metrics["world_reset_requested"] is True
    assert result.metrics["world_reset_succeeded"] is True
    assert result.metrics["world_reset_timeout"] == 7.5
    assert result.metrics["world_reset_command"] == " ".join(expected_command)
    assert result.metrics["world_reset_error"] == ""
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["world_reset_requested"] is True
    assert metadata["world_reset_command"] == expected_command
    assert metadata["world_reset_timeout"] == 7.5
    assert metadata["world_reset_succeeded"] is True
    assert metadata["world_reset_error"] is None


def test_gazebo_sim_lifecycle_reports_world_reset_failure(tmp_path):
    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="reset failed\n")

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        reset_world=True,
        world_reset_timeout=7.5,
        process_factory=process_factory,
        command_runner=command_runner,
    )

    result = report.scenarios[0]
    assert result.status == "failed"
    assert result.failure_reason == "Gazebo world reset failed: reset failed"
    assert result.steps is not None
    assert result.steps[0].status == "passed"
    assert result.steps[1].kind == "gazebo_sim.reset_world"
    assert result.steps[1].status == "failed"
    assert result.steps[1].failure_reason == "Gazebo world reset failed: reset failed"
    assert result.metrics["simulator_started"] is True
    assert result.metrics["error_type"] == "world_reset_failed"
    assert result.metrics["world_reset_requested"] is True
    assert result.metrics["world_reset_succeeded"] is False
    assert result.metrics["world_reset_timeout"] == 7.5
    assert result.metrics["world_reset_error"] == "world_reset_failed"
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["error_type"] == "world_reset_failed"
    assert metadata["world_reset_succeeded"] is False
    assert metadata["world_reset_error"] == "world_reset_failed"


def test_gazebo_sim_lifecycle_can_execute_simulator_steps(tmp_path):
    service_calls = []
    sleeps = []

    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        service_calls.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, stdout="true\n", stderr="")

    def sleeper(seconds):
        sleeps.append(seconds)

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(
        tmp_path / "smoke.yaml",
        steps=[
            {"wait_for_nav2_active": {"timeout": 30}},
            {
                "spawn_obstacle": {
                    "name": "crate_1",
                    "pose": {"x": 2.0, "y": -0.5, "yaw": 0.0},
                    "size": {"x": 0.8, "y": 0.6, "z": 1.2},
                }
            },
            {"wait": {"seconds": 1.5}},
            {
                "move_entity": {
                    "name": "crate_1",
                    "trajectory": [
                        {"at": 0.0, "pose": {"x": 2.0, "y": -0.5, "yaw": 0.0}},
                        {"at": 2.0, "pose": {"x": 2.0, "y": 0.5, "yaw": 1.57}},
                    ],
                }
            },
            {"delete_entity": {"name": "crate_1"}},
            {"send_goal": {"name": "main_goal", "pose": {"x": 10, "y": 0, "yaw": 0}}},
        ],
    )

    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        execute_simulator_steps=True,
        simulator_step_timeout=6.5,
        process_factory=process_factory,
        command_runner=command_runner,
        sleeper=sleeper,
    )

    result = report.scenarios[0]
    assert result.status == "passed"
    assert [step.kind for step in result.steps or []] == [
        "gazebo_sim.launch",
        "gazebo_sim.spawn_obstacle",
        "gazebo_sim.wait",
        "gazebo_sim.move_entity",
        "gazebo_sim.delete_entity",
    ]
    assert [timeout for _command, timeout in service_calls] == [6.5, 6.5, 6.5, 6.5]
    assert service_calls[0][0][3] == "/world/empty/create"
    assert service_calls[1][0][3] == "/world/empty/set_pose"
    assert service_calls[2][0][3] == "/world/empty/set_pose"
    assert service_calls[3][0][3] == "/world/empty/remove"
    assert "position: {x: 2 y: -0.5 z: 0.6}" in service_calls[1][0][11]
    assert "position: {x: 2 y: 0.5 z: 0.6}" in service_calls[2][0][11]
    assert sleeps == [1.5, 2.0]
    assert result.metrics["execute_simulator_steps"] is True
    assert result.metrics["simulator_steps_executed"] == 4
    assert result.metrics["simulator_steps_skipped"] == 2
    assert result.metrics["simulator_step_timeout"] == 6.5
    assert result.metrics["simulator_step_error"] == ""
    assert result.metrics["spawned_entities"] == "crate_1"
    assert result.metrics["moved_entities"] == "crate_1"
    assert result.metrics["deleted_entities"] == "crate_1"
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["execute_simulator_steps"] is True
    assert metadata["simulator_steps_executed"] == 4
    assert metadata["simulator_steps_skipped"] == 2
    assert metadata["spawned_entities"] == ["crate_1"]
    assert metadata["moved_entities"] == ["crate_1"]
    assert metadata["deleted_entities"] == ["crate_1"]
    assert len(metadata["simulator_step_commands"]) == 4


def test_gazebo_sim_lifecycle_reports_simulator_step_failure(tmp_path):
    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="spawn failed\n")

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(
        tmp_path / "smoke.yaml",
        steps=[
            {
                "spawn_obstacle": {
                    "name": "crate_1",
                    "pose": {"x": 2.0, "y": -0.5, "yaw": 0.0},
                }
            }
        ],
    )

    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        execute_simulator_steps=True,
        simulator_step_timeout=6.5,
        wait_for_clock=True,
        process_factory=process_factory,
        command_runner=command_runner,
    )

    result = report.scenarios[0]
    assert result.status == "failed"
    assert result.failure_reason == "Gazebo spawn_obstacle failed for crate_1: spawn failed"
    assert [step.kind for step in result.steps or []] == [
        "gazebo_sim.launch",
        "gazebo_sim.spawn_obstacle",
        "gazebo_sim.clock",
    ]
    assert result.steps[1].status == "failed"
    assert result.steps[2].status == "failed"
    assert result.metrics["error_type"] == "spawn_obstacle_failed"
    assert result.metrics["simulator_step_error"] == "spawn_obstacle_failed"
    assert result.metrics["simulator_steps_executed"] == 0
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["simulator_step_error"] == "spawn_obstacle_failed"
    assert metadata["simulator_steps_executed"] == 0


def test_gazebo_sim_lifecycle_collects_contacts_and_fails_collision_assertion(tmp_path):
    contact_log = """
contact {
  collision1 {
    name: "robot::base_link::collision"
  }
  collision2 {
    name: "crate_1::link::collision"
  }
}
"""

    def process_factory(command, **kwargs):
        stdout = kwargs.get("stdout")
        if command[:3] == ["gz", "topic", "-e"] and stdout is not None:
            stdout.write(contact_log)
            stdout.flush()
        return FakeProcess(return_code=None)

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(
        tmp_path / "smoke.yaml",
        assertions=[{"collision_free": {}}],
    )

    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        collect_contacts=True,
        contact_topics=["/world/empty/model/robot/link/base_link/sensor/contact/contact"],
        process_factory=process_factory,
    )

    result = report.scenarios[0]
    assert result.status == "failed"
    assert result.failure_reason == "Collision detected; collision_count=1."
    assert [step.kind for step in result.steps or []] == [
        "gazebo_sim.launch",
        "gazebo_sim.contact_collection",
    ]
    assert result.steps[1].status == "passed"
    assert result.metrics["contact_collection_requested"] is True
    assert result.metrics["contact_collection_ready"] is True
    assert result.metrics["collision_count"] == 1
    assert result.metrics["collision_free"] is False
    assert result.metrics["contact_pairs"] == "robot::base_link::collision <-> crate_1::link::collision"
    assert result.metrics["error_type"] == "assertion_failed"
    assert result.assertions is not None
    assert result.assertions[0].kind == "collision_free"
    assert result.assertions[0].status == "failed"
    contact_log_path = Path(result.metrics["contact_logs"])
    assert contact_log_path.exists()
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["error_type"] == "assertion_failed"
    assert metadata["collision_count"] == 1
    assert metadata["collision_free"] is False
    assert metadata["contact_pairs"] == [
        "robot::base_link::collision <-> crate_1::link::collision"
    ]


def test_gazebo_sim_lifecycle_discovers_contact_topics_and_passes_when_no_contacts(tmp_path):
    process_commands = []
    discovery_commands = []

    def process_factory(command, **kwargs):
        process_commands.append(command)
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        discovery_commands.append((command, timeout))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="/clock\n/world/empty/model/robot/link/base/sensor/contact/contact\n",
            stderr="",
        )

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(
        tmp_path / "smoke.yaml",
        assertions=[{"collision_free": {}}],
    )

    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        collect_contacts=True,
        contact_discovery_timeout=2.5,
        process_factory=process_factory,
        command_runner=command_runner,
    )

    result = report.scenarios[0]
    assert result.status == "passed"
    assert discovery_commands == [(["gz", "topic", "-l"], 2.5)]
    assert process_commands[1] == [
        "gz",
        "topic",
        "-e",
        "-t",
        "/world/empty/model/robot/link/base/sensor/contact/contact",
    ]
    assert result.metrics["collision_count"] == 0
    assert result.metrics["collision_free"] is True
    assert result.assertions is not None
    assert result.assertions[0].status == "passed"


def test_gazebo_sim_lifecycle_fails_when_contact_topics_unavailable(tmp_path):
    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        return subprocess.CompletedProcess(command, 0, stdout="/clock\n", stderr="")

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")

    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        collect_contacts=True,
        process_factory=process_factory,
        command_runner=command_runner,
    )

    result = report.scenarios[0]
    assert result.status == "failed"
    assert result.failure_reason == (
        "No Gazebo contact topics were found. Configure --contact-topic or add contact sensors."
    )
    assert result.steps is not None
    assert result.steps[1].kind == "gazebo_sim.contact_collection"
    assert result.steps[1].status == "failed"
    assert result.metrics["error_type"] == "contact_topics_unavailable"
    assert result.metrics["contact_collection_ready"] is False


def test_gazebo_sim_lifecycle_rejects_unsupported_simulator_step(tmp_path):
    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(
        tmp_path / "smoke.yaml",
        steps=[
            {
                "spawn_person": {
                    "name": "person_1",
                    "pose": {"x": 1.0, "y": 2.0, "yaw": 0.0},
                }
            }
        ],
    )

    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        execute_simulator_steps=True,
        process_factory=process_factory,
    )

    result = report.scenarios[0]
    assert result.status == "failed"
    assert result.failure_reason == "Gazebo Sim simulator step is not supported yet: spawn_person."
    assert result.steps is not None
    assert result.steps[1].kind == "gazebo_sim.spawn_person"
    assert result.steps[1].status == "failed"
    assert result.metrics["error_type"] == "GazeboSimError"
    assert result.metrics["simulator_step_error"] == "GazeboSimError"


def test_gazebo_sim_lifecycle_launches_scenario_stack_processes(tmp_path):
    processes: list[FakeProcess] = []
    commands = []

    def process_factory(command, **kwargs):
        commands.append((command, kwargs))
        process = FakeProcess(return_code=None)
        processes.append(process)
        return process

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(
        tmp_path / "smoke.yaml",
        runtime={"use_sim_time": True},
        simulator_launch={
            "package": "my_robot_bringup",
            "file": "sim.launch.py",
            "args": {"robot": "tb3", "world": "warehouse"},
        },
        nav2={
            "bringup": {
                "package": "nav2_bringup",
                "file": "bringup_launch.py",
                "args": {"namespace": "robot1"},
            },
            "params": "config/nav2_params.yaml",
            "map": "maps/warehouse.yaml",
            "autostart": True,
        },
    )

    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        launch_scenario_stack=True,
        process_factory=process_factory,
    )

    result = report.scenarios[0]
    artifact_dir = Path(result.metrics["artifact_dir"])
    assert result.status == "passed"
    assert [step.kind for step in result.steps or []] == [
        "gazebo_sim.launch",
        "simulator.launch",
        "nav2.bringup",
    ]
    assert [step.index for step in result.steps or []] == [0, 1, 2]
    assert commands[0][0] == ["gz", "sim", "-s", str(tmp_path / "worlds/empty.sdf")]
    assert commands[1][0] == [
        "ros2",
        "launch",
        "my_robot_bringup",
        "sim.launch.py",
        "robot:=tb3",
        "world:=warehouse",
    ]
    assert commands[2][0] == [
        "ros2",
        "launch",
        "nav2_bringup",
        "bringup_launch.py",
        "autostart:=true",
        "map:=maps/warehouse.yaml",
        "namespace:=robot1",
        "params_file:=config/nav2_params.yaml",
        "use_sim_time:=true",
    ]
    assert result.metrics["launch_scenario_stack"] is True
    assert result.metrics["launch_stack_started"] is True
    assert result.metrics["launch_process_count"] == 2
    assert result.metrics["simulator_launch_log"] == str(artifact_dir / "simulator_launch.log")
    assert result.metrics["nav2_bringup_log"] == str(artifact_dir / "nav2_bringup.log")
    assert (artifact_dir / "simulator_launch.log").exists()
    assert (artifact_dir / "nav2_bringup.log").exists()
    assert all(process.terminated for process in processes)
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["launch_scenario_stack"] is True
    assert metadata["launch_stack_started"] is True
    assert metadata["launch_processes"] == [
        {
            "name": "simulator.launch",
            "command": commands[1][0],
            "log": str(artifact_dir / "simulator_launch.log"),
            "exit_code": 0,
        },
        {
            "name": "nav2.bringup",
            "command": commands[2][0],
            "log": str(artifact_dir / "nav2_bringup.log"),
            "exit_code": 0,
        },
    ]


def test_gazebo_sim_lifecycle_can_wait_for_clock(tmp_path):
    clock_commands = []

    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        clock_commands.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, stdout="clock\n", stderr="")

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        wait_for_clock=True,
        clock_timeout=3.0,
        process_factory=process_factory,
        command_runner=command_runner,
    )

    result = report.scenarios[0]
    assert result.status == "passed"
    assert [step.kind for step in result.steps] == ["gazebo_sim.launch", "gazebo_sim.clock"]
    assert result.steps[1].status == "passed"
    assert result.metrics["simulator_started"] is True
    assert result.metrics["clock_requested"] is True
    assert result.metrics["clock_ready"] is True
    assert result.metrics["clock_timeout"] == 3.0
    assert result.metrics["clock_command"] == "ros2 topic echo /clock --once"
    assert clock_commands == [(["ros2", "topic", "echo", "/clock", "--once"], 3.0)]
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["clock_requested"] is True
    assert metadata["clock_ready"] is True
    assert metadata["clock_timeout"] == 3.0
    assert metadata["clock_command"] == ["ros2", "topic", "echo", "/clock", "--once"]
    assert metadata["clock_error"] is None


def test_gazebo_sim_lifecycle_can_wait_for_ros_graph(tmp_path):
    graph_commands = []

    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        graph_commands.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, stdout="/demo\n", stderr="")

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        wait_for_ros_graph=True,
        ros_graph_timeout=4.0,
        process_factory=process_factory,
        command_runner=command_runner,
    )

    result = report.scenarios[0]
    assert result.status == "passed"
    assert [step.kind for step in result.steps or []] == [
        "gazebo_sim.launch",
        "ros_graph.readiness",
    ]
    assert result.steps[1].status == "passed"
    assert graph_commands == [
        (["ros2", "node", "list"], 2.0),
        (["ros2", "topic", "list"], 2.0),
    ]
    assert result.metrics["ros_graph_requested"] is True
    assert result.metrics["ros_graph_ready"] is True
    assert result.metrics["ros_graph_timeout"] == 4.0
    assert result.metrics["ros_graph_commands"] == "ros2 node list; ros2 topic list"
    assert result.metrics["ros_graph_error"] == ""
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["ros_graph_requested"] is True
    assert metadata["ros_graph_ready"] is True
    assert metadata["ros_graph_timeout"] == 4.0
    assert metadata["ros_graph_commands"] == [["ros2", "node", "list"], ["ros2", "topic", "list"]]
    assert metadata["ros_graph_error"] is None


def test_gazebo_sim_lifecycle_reports_ros_graph_timeout(tmp_path):
    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        raise subprocess.TimeoutExpired(command, timeout)

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        wait_for_ros_graph=True,
        ros_graph_timeout=4.0,
        process_factory=process_factory,
        command_runner=command_runner,
    )

    result = report.scenarios[0]
    assert result.status == "failed"
    assert result.failure_reason == "Timed out waiting for ROS graph after 4s."
    assert result.steps is not None
    assert result.steps[0].status == "passed"
    assert result.steps[1].kind == "ros_graph.readiness"
    assert result.steps[1].status == "failed"
    assert result.metrics["simulator_started"] is True
    assert result.metrics["error_type"] == "ros_graph_timeout"
    assert result.metrics["ros_graph_ready"] is False
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["error_type"] == "ros_graph_timeout"
    assert metadata["ros_graph_ready"] is False
    assert metadata["ros_graph_error"] == "ros_graph_timeout"


def test_gazebo_sim_lifecycle_can_wait_for_nav2_readiness(tmp_path):
    backend = FakeNav2Backend()

    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        wait_for_nav2=True,
        nav2_timeout=12.0,
        process_factory=process_factory,
        nav2_backend_factory=lambda _scenario: backend,
    )

    result = report.scenarios[0]
    assert result.status == "passed"
    assert [step.kind for step in result.steps or []] == [
        "gazebo_sim.launch",
        "nav2.readiness",
    ]
    assert result.steps[1].status == "passed"
    assert backend.operations == ["wait_for_nav2_active:12", "close"]
    assert result.metrics["nav2_readiness_requested"] is True
    assert result.metrics["nav2_ready"] is True
    assert result.metrics["nav2_timeout"] == 12.0
    assert result.metrics["nav2_error"] == ""
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["nav2_readiness_requested"] is True
    assert metadata["nav2_ready"] is True
    assert metadata["nav2_timeout"] == 12.0
    assert metadata["nav2_error"] is None


def test_gazebo_sim_lifecycle_reports_nav2_readiness_failure(tmp_path):
    backend = UnavailableNav2Backend()

    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        wait_for_nav2=True,
        nav2_timeout=12.0,
        process_factory=process_factory,
        nav2_backend_factory=lambda _scenario: backend,
    )

    result = report.scenarios[0]
    assert result.status == "failed"
    assert result.failure_reason == "Nav2 NavigateToPose action server not available after 12s"
    assert result.steps is not None
    assert result.steps[0].status == "passed"
    assert result.steps[1].kind == "nav2.readiness"
    assert result.steps[1].status == "failed"
    assert backend.operations == ["wait_for_nav2_active:12", "close"]
    assert result.metrics["simulator_started"] is True
    assert result.metrics["error_type"] == "StepExecutionError"
    assert result.metrics["nav2_ready"] is False
    assert result.metrics["nav2_error"] == "StepExecutionError"
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["error_type"] == "StepExecutionError"
    assert metadata["nav2_ready"] is False
    assert metadata["nav2_error"] == "StepExecutionError"


def test_gazebo_sim_lifecycle_can_wait_for_navigation_data(tmp_path):
    topic_commands = []

    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        topic_commands.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, stdout="data\n", stderr="")

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(
        tmp_path / "smoke.yaml",
        runtime={"isolation": {"namespace": "/robot1"}},
    )
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        wait_for_navigation_data=True,
        navigation_data_timeout=15.0,
        process_factory=process_factory,
        command_runner=command_runner,
    )

    result = report.scenarios[0]
    expected_commands = [
        ["ros2", "topic", "echo", "/tf", "--once"],
        ["ros2", "topic", "echo", "/robot1/map", "--once"],
        ["ros2", "topic", "echo", "/robot1/global_costmap/costmap", "--once"],
        ["ros2", "topic", "echo", "/robot1/local_costmap/costmap", "--once"],
    ]
    assert result.status == "passed"
    assert [step.kind for step in result.steps or []] == [
        "gazebo_sim.launch",
        "navigation_data.readiness",
    ]
    assert result.steps[1].status == "passed"
    assert [command for command, _timeout in topic_commands] == expected_commands
    assert all(0 < timeout <= 15.0 for _command, timeout in topic_commands)
    assert result.metrics["navigation_data_requested"] is True
    assert result.metrics["navigation_data_ready"] is True
    assert result.metrics["navigation_data_timeout"] == 15.0
    assert result.metrics["navigation_data_topics"] == (
        "/tf, /robot1/map, /robot1/global_costmap/costmap, /robot1/local_costmap/costmap"
    )
    assert result.metrics["navigation_data_error"] == ""
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["navigation_data_requested"] is True
    assert metadata["navigation_data_ready"] is True
    assert metadata["navigation_data_timeout"] == 15.0
    assert metadata["navigation_data_topics"] == [
        "/tf",
        "/robot1/map",
        "/robot1/global_costmap/costmap",
        "/robot1/local_costmap/costmap",
    ]
    assert metadata["navigation_data_commands"] == expected_commands
    assert metadata["navigation_data_error"] is None


def test_gazebo_sim_lifecycle_uses_configured_navigation_data_topics(tmp_path):
    topic_commands = []

    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        topic_commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="data\n", stderr="")

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(
        tmp_path / "smoke.yaml",
        runtime={"isolation": {"namespace": "/robot1"}},
        robot={
            "topics": {
                "tf": "/tf_static",
                "map": "/map",
                "global_costmap": "shared/global_costmap",
                "local_costmap": "/robot1/local_costmap/costmap_raw",
            }
        },
    )
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        wait_for_navigation_data=True,
        navigation_data_timeout=15.0,
        process_factory=process_factory,
        command_runner=command_runner,
    )

    result = report.scenarios[0]
    assert result.status == "passed"
    assert topic_commands == [
        ["ros2", "topic", "echo", "/tf_static", "--once"],
        ["ros2", "topic", "echo", "/map", "--once"],
        ["ros2", "topic", "echo", "/robot1/shared/global_costmap", "--once"],
        ["ros2", "topic", "echo", "/robot1/local_costmap/costmap_raw", "--once"],
    ]


def test_gazebo_sim_lifecycle_reports_navigation_data_timeout(tmp_path):
    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        raise subprocess.TimeoutExpired(command, timeout)

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        wait_for_navigation_data=True,
        navigation_data_timeout=15.0,
        process_factory=process_factory,
        command_runner=command_runner,
    )

    result = report.scenarios[0]
    assert result.status == "failed"
    assert result.failure_reason == "Timed out waiting for navigation data topic /tf after 15s."
    assert result.steps is not None
    assert result.steps[0].status == "passed"
    assert result.steps[1].kind == "navigation_data.readiness"
    assert result.steps[1].status == "failed"
    assert result.metrics["simulator_started"] is True
    assert result.metrics["error_type"] == "navigation_data_timeout"
    assert result.metrics["navigation_data_ready"] is False
    assert result.metrics["navigation_data_error"] == "navigation_data_timeout"
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["error_type"] == "navigation_data_timeout"
    assert metadata["navigation_data_ready"] is False
    assert metadata["navigation_data_error"] == "navigation_data_timeout"


def test_gazebo_sim_lifecycle_reports_clock_timeout(tmp_path):
    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        raise subprocess.TimeoutExpired(command, timeout)

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        wait_for_clock=True,
        clock_timeout=3.0,
        process_factory=process_factory,
        command_runner=command_runner,
    )

    result = report.scenarios[0]
    assert result.status == "failed"
    assert result.failure_reason == "Timed out waiting for /clock after 3s."
    assert result.steps[0].status == "passed"
    assert result.steps[1].status == "failed"
    assert result.steps[1].failure_reason == "Timed out waiting for /clock after 3s."
    assert result.metrics["simulator_started"] is True
    assert result.metrics["error_type"] == "clock_timeout"
    assert result.metrics["clock_ready"] is False
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["error_type"] == "clock_timeout"
    assert metadata["clock_ready"] is False
    assert metadata["clock_error"] == "clock_timeout"


def test_gazebo_sim_lifecycle_can_execute_nav2_steps_while_process_runs(tmp_path):
    backend = FakeNav2Backend()

    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(
        tmp_path / "smoke.yaml",
        steps=[
            {"wait_for_nav2_active": {"timeout": 30}},
            {"set_initial_pose": {"x": 0, "y": 0, "yaw": 0}},
            {"send_goal": {"name": "main_goal", "pose": {"x": 10, "y": 0, "yaw": 0}}},
            {"expect_goal_reached": {"goal": "main_goal", "timeout": 60}},
        ],
        assertions=[
            {"collision_free": {}},
            {"path_length": {"max": 13.0}},
            {"travel_time": {"max": 60.0}},
            {"recovery_count": {"max": 0}},
        ],
    )

    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        execute_nav2=True,
        process_factory=process_factory,
        nav2_backend_factory=lambda _scenario: backend,
    )

    result = report.scenarios[0]
    assert result.status == "passed"
    assert [step.kind for step in result.steps or []] == [
        "gazebo_sim.launch",
        "wait_for_nav2_active",
        "set_initial_pose",
        "send_goal",
        "expect_goal_reached",
    ]
    assert [step.index for step in result.steps or []] == [0, 1, 2, 3, 4]
    assert backend.operations[-1] == "close"
    assert result.assertions is not None
    assert [assertion.status for assertion in result.assertions] == ["passed", "passed", "passed", "passed"]
    assert result.metrics["simulator_started"] is True
    assert result.metrics["nav2_executed"] is True
    assert result.metrics["nav2_status"] == "passed"
    assert result.metrics["goal_reached"] is True
    assert result.metrics["path_length_traveled"] == 10.0
    assert result.metrics["collision_free"] is True
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["execute_nav2"] is True
    assert metadata["nav2_status"] == "passed"


def test_gazebo_sim_lifecycle_runs_parallel_simulator_branch_during_nav2_execution(tmp_path):
    backend = FakeNav2Backend()
    service_calls = []
    sleeps = []

    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def command_runner(command, timeout):
        service_calls.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, stdout="true\n", stderr="")

    def sleeper(seconds):
        sleeps.append(seconds)

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(
        tmp_path / "dynamic.yaml",
        steps=[
            {"wait_for_nav2_active": {"timeout": 30}},
            {"set_initial_pose": {"x": 0, "y": 0, "yaw": 0}},
            {
                "parallel": {
                    "join": "all",
                    "branches": [
                        {
                            "name": "navigation",
                            "steps": [
                                {
                                    "send_goal": {
                                        "name": "main_goal",
                                        "pose": {"x": 10, "y": 0, "yaw": 0},
                                    }
                                },
                                {"expect_goal_reached": {"goal": "main_goal", "timeout": 90}},
                            ],
                        },
                        {
                            "name": "obstacle",
                            "steps": [
                                {"wait": {"seconds": 8}},
                                {
                                    "spawn_obstacle": {
                                        "name": "crossing_box",
                                        "pose": {"x": 5.0, "y": -1.0, "yaw": 0.0},
                                        "size": {"x": 0.7, "y": 0.7, "z": 1.0},
                                    }
                                },
                                {
                                    "move_entity": {
                                        "name": "crossing_box",
                                        "trajectory": [
                                            {"at": 0.0, "pose": {"x": 5.0, "y": -1.0, "yaw": 0.0}},
                                            {"at": 4.0, "pose": {"x": 5.0, "y": 1.0, "yaw": 0.0}},
                                        ],
                                    }
                                },
                            ],
                        },
                    ],
                }
            },
        ],
        assertions=[
            {"collision_free": {}},
            {"path_length": {"max": 13.0}},
            {"travel_time": {"max": 90.0}},
            {"recovery_count": {"max": 0}},
        ],
    )

    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        execute_nav2=True,
        execute_simulator_steps=True,
        simulator_step_timeout=6.5,
        process_factory=process_factory,
        command_runner=command_runner,
        sleeper=sleeper,
        nav2_backend_factory=lambda _scenario: backend,
    )

    result = report.scenarios[0]
    step_kinds = [step.kind for step in result.steps or []]
    assert result.status == "passed"
    assert "gazebo_sim.parallel.obstacle.wait" in step_kinds
    assert "gazebo_sim.parallel.obstacle.spawn_obstacle" in step_kinds
    assert "gazebo_sim.parallel.obstacle.move_entity" in step_kinds
    assert step_kinds[-4:] == [
        "wait_for_nav2_active",
        "set_initial_pose",
        "send_goal",
        "expect_goal_reached",
    ]
    assert backend.operations[:4] == [
        "wait_for_nav2_active:30",
        "set_initial_pose:0,0,0",
        "send_goal:main_goal:10,0,0",
        "reset_path_length_traveled",
    ]
    assert [command[3] for command, _timeout in service_calls] == [
        "/world/empty/create",
        "/world/empty/set_pose",
        "/world/empty/set_pose",
    ]
    assert [timeout for _command, timeout in service_calls] == [6.5, 6.5, 6.5]
    assert sleeps == [8.0, 4.0]
    assert result.metrics["scheduled_simulator_steps"] is True
    assert result.metrics["simulator_steps_executed"] == 3
    assert result.metrics["simulator_steps_skipped"] == 3
    assert result.metrics["spawned_entities"] == "crossing_box"
    assert result.metrics["moved_entities"] == "crossing_box"
    assert result.metrics["nav2_status"] == "passed"
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["scheduled_simulator_steps"] is True
    assert metadata["simulator_steps_executed"] == 3
    assert metadata["simulator_steps_skipped"] == 3
    assert metadata["spawned_entities"] == ["crossing_box"]
    assert len(metadata["simulator_step_commands"]) == 3


def test_gazebo_sim_lifecycle_reports_nav2_execution_failure(tmp_path):
    def process_factory(command, **kwargs):
        return FakeProcess(return_code=None)

    def nav2_backend_factory(_scenario):
        raise RuntimeError("Nav2 graph is not ready")

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        execute_nav2=True,
        process_factory=process_factory,
        nav2_backend_factory=nav2_backend_factory,
    )

    result = report.scenarios[0]
    assert result.status == "failed"
    assert result.failure_reason == "Nav2 graph is not ready"
    assert result.steps is not None
    assert result.steps[0].status == "passed"
    assert result.metrics["simulator_started"] is True
    assert result.metrics["nav2_executed"] is True
    assert result.metrics["nav2_status"] == "failed"
    assert result.metrics["error_type"] == "RuntimeError"
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["execute_nav2"] is True
    assert metadata["nav2_status"] == "failed"


def test_gazebo_sim_lifecycle_reports_startup_exit(tmp_path):
    def process_factory(command, **kwargs):
        return FakeProcess(return_code=2)

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        process_factory=process_factory,
    )

    assert report.passed == 0
    assert report.failed == 1
    result = report.scenarios[0]
    assert result.status == "failed"
    assert result.failure_reason == "Gazebo Sim exited during startup with code 2."
    assert result.metrics["simulator_started"] is False
    assert result.metrics["error_type"] == "startup_exit"
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["error_type"] == "startup_exit"
    assert metadata["failure_reason"] == "Gazebo Sim exited during startup with code 2."
    assert metadata["exit_code"] == 2


def test_gazebo_sim_lifecycle_records_process_launch_exception(tmp_path):
    def process_factory(command, **kwargs):
        raise FileNotFoundError("missing gz")

    _write_world(tmp_path / "worlds/empty.sdf")
    scenario = _scenario(tmp_path / "smoke.yaml")
    report = run_gazebo_sim_lifecycle(
        [scenario],
        report_dir=tmp_path / "reports",
        startup_timeout=0,
        preflight_skipped=True,
        process_factory=process_factory,
    )

    result = report.scenarios[0]
    assert result.status == "failed"
    assert result.metrics["preflight_skipped"] is True
    assert result.metrics["error_type"] == "FileNotFoundError"
    metadata = json.loads(Path(result.metrics["metadata"]).read_text(encoding="utf-8"))
    assert metadata["error_type"] == "FileNotFoundError"
    assert metadata["preflight_skipped"] is True
    assert metadata["command"] == ["gz", "sim", "-s", str(tmp_path / "worlds/empty.sdf")]
    assert metadata["world"] == str(tmp_path / "worlds/empty.sdf")


def test_gazebo_sim_command_rejects_missing_local_world(tmp_path):
    scenario = _scenario(tmp_path / "smoke.yaml", world="worlds/missing.sdf")

    with pytest.raises(GazeboSimError, match="world file does not exist"):
        gazebo_sim_command(scenario)


def test_gazebo_sim_command_allows_resource_uri_world(tmp_path):
    scenario = _scenario(tmp_path / "smoke.yaml", world="model://demo_world")

    assert gazebo_sim_command(scenario) == ["gz", "sim", "-s", "model://demo_world"]


def _scenario(
    path: Path,
    world: str = "worlds/empty.sdf",
    headless: bool = True,
    runtime: dict | None = None,
    simulator_launch: dict | None = None,
    nav2: dict | None = None,
    robot: dict | None = None,
    steps: list[dict] | None = None,
    assertions: list[dict] | None = None,
) -> Scenario:
    simulator = {
        "type": "gazebo_sim",
        "headless": headless,
        "world": world,
    }
    if simulator_launch is not None:
        simulator["launch"] = simulator_launch

    document = {
        "simulator": simulator,
        "steps": steps or [],
        "assertions": assertions or [],
    }
    if runtime is not None:
        document["runtime"] = runtime
    if nav2 is not None:
        document["nav2"] = nav2
    if robot is not None:
        document["robot"] = robot

    return Scenario(
        path=path,
        document=document,
        scenario_id="straight_line_goal",
        name="straight_line_goal",
        tags={"smoke"},
        step_count=len(steps or []),
        assertion_count=len(assertions or []),
    )


def _write_world(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<sdf version='1.9'><world name='empty'></world></sdf>\n", encoding="utf-8")
