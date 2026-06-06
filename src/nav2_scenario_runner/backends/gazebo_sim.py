from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol, TextIO

from nav2_scenario_runner import __version__
from nav2_scenario_runner.assertions import assertion_results_passed, evaluate_assertions, first_failed_assertion
from nav2_scenario_runner.execution import ExecutionEngine, parse_steps
from nav2_scenario_runner.runner import RunReport, ScenarioRunResult, StepRunResult
from nav2_scenario_runner.scenario import Scenario


class GazeboSimError(RuntimeError):
    """Raised when a Gazebo Sim lifecycle smoke run cannot be prepared."""


class ProcessLike(Protocol):
    def poll(self) -> int | None:
        ...

    def terminate(self) -> None:
        ...

    def wait(self, timeout: float | None = None) -> int:
        ...

    def kill(self) -> None:
        ...


ProcessFactory = Callable[..., ProcessLike]
CommandRunner = Callable[[list[str], float], subprocess.CompletedProcess[str]]
Nav2BackendFactory = Callable[[Scenario], object]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]

NAV2_EXECUTABLE_STEP_KINDS = frozenset(
    {
        "wait_for_nav2_active",
        "set_initial_pose",
        "send_goal",
        "expect_goal_reached",
        "send_waypoints",
        "cancel_goal",
        "clear_costmaps",
        "select_planner",
        "select_controller",
    }
)

UNSUPPORTED_GAZEBO_SIMULATOR_STEP_KINDS = frozenset(
    {
        "spawn_person",
        "set_door",
        "parallel",
        "on_event",
        "wait_until",
        "wait_for_topic",
        "wait_for_transform",
        "if",
        "call_service",
    }
)


@dataclass
class ManagedProcess:
    name: str
    command: list[str]
    process: ProcessLike
    log_path: Path
    log_handle: TextIO
    exit_code: int | None = None


@dataclass(frozen=True)
class LaunchProcessSpec:
    name: str
    command: list[str]
    log_path: Path


@dataclass
class GazeboSimulatorStepsResult:
    steps: list[StepRunResult]
    commands: list[list[str]]
    spawned_entities: list[str]
    moved_entities: list[str]
    deleted_entities: list[str]
    executed_count: int = 0
    skipped_count: int = 0
    error_type: str | None = None
    failure_reason: str | None = None


@dataclass
class ContactCollectionResult:
    requested: bool
    topics: list[str]
    commands: list[list[str]]
    logs: list[str]
    collision_count: int | None = None
    collision_free: bool | None = None
    contact_pairs: list[str] | None = None
    ready: bool | None = None
    error_type: str | None = None
    failure_reason: str | None = None
    duration_seconds: float | None = None


def run_gazebo_sim_lifecycle(
    scenarios: list[Scenario],
    report_dir: Path,
    startup_timeout: float = 5.0,
    preflight_skipped: bool = False,
    wait_for_clock: bool = False,
    clock_timeout: float = 10.0,
    execute_nav2: bool = False,
    launch_scenario_stack: bool = False,
    wait_for_ros_graph: bool = False,
    ros_graph_timeout: float = 10.0,
    wait_for_nav2: bool = False,
    nav2_timeout: float = 30.0,
    wait_for_navigation_data: bool = False,
    navigation_data_timeout: float = 30.0,
    reset_world: bool = False,
    world_reset_timeout: float = 10.0,
    execute_simulator_steps: bool = False,
    simulator_step_timeout: float = 10.0,
    collect_contacts: bool = False,
    contact_topics: list[str] | None = None,
    contact_discovery_timeout: float = 5.0,
    process_factory: ProcessFactory | None = None,
    command_runner: CommandRunner | None = None,
    nav2_backend_factory: Nav2BackendFactory | None = None,
    clock: Clock = time.monotonic,
    sleeper: Sleeper = time.sleep,
) -> RunReport:
    process_factory = process_factory or subprocess.Popen
    command_runner = command_runner or _default_command_runner
    nav2_backend_factory = nav2_backend_factory or _default_nav2_backend_factory
    results = [
        _run_one_scenario(
            scenario=scenario,
            report_dir=report_dir,
            startup_timeout=startup_timeout,
            preflight_skipped=preflight_skipped,
            wait_for_clock=wait_for_clock,
            clock_timeout=clock_timeout,
            execute_nav2=execute_nav2,
            launch_scenario_stack=launch_scenario_stack,
            wait_for_ros_graph=wait_for_ros_graph,
            ros_graph_timeout=ros_graph_timeout,
            wait_for_nav2=wait_for_nav2,
            nav2_timeout=nav2_timeout,
            wait_for_navigation_data=wait_for_navigation_data,
            navigation_data_timeout=navigation_data_timeout,
            reset_world=reset_world,
            world_reset_timeout=world_reset_timeout,
            execute_simulator_steps=execute_simulator_steps,
            simulator_step_timeout=simulator_step_timeout,
            collect_contacts=collect_contacts,
            contact_topics=contact_topics or [],
            contact_discovery_timeout=contact_discovery_timeout,
            process_factory=process_factory,
            command_runner=command_runner,
            nav2_backend_factory=nav2_backend_factory,
            clock=clock,
            sleeper=sleeper,
        )
        for scenario in scenarios
    ]
    failed = sum(1 for result in results if result.status != "passed")
    return RunReport(
        runner_version=__version__,
        generated_at=datetime.now(timezone.utc).isoformat(),
        mode="gazebo_sim",
        total=len(results),
        passed=len(results) - failed,
        failed=failed,
        scenarios=results,
    )


def gazebo_sim_command(scenario: Scenario) -> list[str]:
    simulator = scenario.document.get("simulator")
    if not isinstance(simulator, dict):
        raise GazeboSimError("Gazebo Sim mode requires a simulator mapping.")
    if simulator.get("type") != "gazebo_sim":
        raise GazeboSimError("Gazebo Sim mode requires simulator.type: gazebo_sim.")

    world = simulator.get("world")
    if not world:
        raise GazeboSimError("Gazebo Sim mode requires simulator.world.")

    world_arg = _resolve_world_arg(scenario, str(world))
    command = ["gz", "sim"]
    # ``-r`` starts the simulation running instead of paused. A paused server
    # never advances /clock, so use_sim_time consumers (Nav2) would hang; real
    # navigation scenarios set ``simulator.run: true`` to drive the sim forward.
    if bool(simulator.get("run", False)):
        command.append("-r")
    if bool(simulator.get("headless", True)):
        command.append("-s")
    command.append(world_arg)
    return command


def gazebo_world_reset_command(scenario: Scenario, timeout: float = 10.0) -> list[str]:
    command = gazebo_sim_command(scenario)
    world_name = _world_name_from_world_arg(command[-1])
    timeout_ms = max(1, int(timeout * 1000))
    return [
        "gz",
        "service",
        "-s",
        f"/world/{world_name}/control",
        "--reqtype",
        "gz.msgs.WorldControl",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        str(timeout_ms),
        "--req",
        "reset: {all: true}",
    ]


def gazebo_spawn_obstacle_command(scenario: Scenario, params: dict, timeout: float = 10.0) -> list[str]:
    name = _required_name(params, "spawn_obstacle")
    obstacle_type = str(params.get("type", "box"))
    if obstacle_type != "box":
        raise GazeboSimError(
            f"Gazebo Sim spawn_obstacle currently supports type: box only, got {obstacle_type}."
        )
    world_name = _scenario_world_name(scenario)
    timeout_ms = max(1, int(timeout * 1000))
    sdf = _box_obstacle_sdf(name=name, params=params)
    return [
        "gz",
        "service",
        "-s",
        f"/world/{world_name}/create",
        "--reqtype",
        "gz.msgs.EntityFactory",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        str(timeout_ms),
        "--req",
        f"sdf: {_protobuf_string(sdf)}",
    ]


def gazebo_delete_entity_command(scenario: Scenario, params: dict, timeout: float = 10.0) -> list[str]:
    name = _required_name(params, "delete_entity")
    world_name = _scenario_world_name(scenario)
    timeout_ms = max(1, int(timeout * 1000))
    return [
        "gz",
        "service",
        "-s",
        f"/world/{world_name}/remove",
        "--reqtype",
        "gz.msgs.Entity",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        str(timeout_ms),
        "--req",
        f"name: {_protobuf_string(name)} type: MODEL",
    ]


def gazebo_set_entity_pose_command(
    scenario: Scenario,
    name: str,
    pose: dict,
    timeout: float = 10.0,
    default_z: float = 0.0,
) -> list[str]:
    world_name = _scenario_world_name(scenario)
    timeout_ms = max(1, int(timeout * 1000))
    x = _float_value(pose.get("x"), "move_entity.pose.x")
    y = _float_value(pose.get("y"), "move_entity.pose.y")
    z = _float_value(pose.get("z", default_z), "move_entity.pose.z")
    yaw = _float_value(pose.get("yaw"), "move_entity.pose.yaw")
    qz = math.sin(yaw / 2.0)
    qw = math.cos(yaw / 2.0)
    return [
        "gz",
        "service",
        "-s",
        f"/world/{world_name}/set_pose",
        "--reqtype",
        "gz.msgs.Pose",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        str(timeout_ms),
        "--req",
        (
            f"name: {_protobuf_string(name)} "
            f"position: {{x: {x:g} y: {y:g} z: {z:g}}} "
            f"orientation: {{x: 0 y: 0 z: {qz:g} w: {qw:g}}}"
        ),
    ]


def scenario_stack_launch_specs(scenario: Scenario, artifact_dir: Path) -> list[LaunchProcessSpec]:
    specs: list[LaunchProcessSpec] = []
    simulator = scenario.document.get("simulator")
    if isinstance(simulator, dict) and isinstance(simulator.get("launch"), dict):
        specs.append(
            LaunchProcessSpec(
                name="simulator.launch",
                command=_ros2_launch_command(simulator["launch"]),
                log_path=artifact_dir / "simulator_launch.log",
            )
        )

    nav2 = scenario.document.get("nav2")
    if isinstance(nav2, dict) and isinstance(nav2.get("bringup"), dict):
        specs.append(
            LaunchProcessSpec(
                name="nav2.bringup",
                command=_ros2_launch_command(nav2["bringup"], extra_args=_nav2_bringup_args(scenario, nav2)),
                log_path=artifact_dir / "nav2_bringup.log",
            )
        )

    return specs


def _ros2_launch_command(launch: dict, extra_args: dict[str, object] | None = None) -> list[str]:
    package = launch.get("package")
    launch_file = launch.get("file")
    if not package or not launch_file:
        raise GazeboSimError("ROS launch blocks require package and file.")

    args: dict[str, object] = {}
    if extra_args:
        args.update(extra_args)
    raw_args = launch.get("args") or {}
    if not isinstance(raw_args, dict):
        raise GazeboSimError("ROS launch block args must be a mapping.")
    args.update(raw_args)

    command = ["ros2", "launch", str(package), str(launch_file)]
    for key in sorted(args):
        value = args[key]
        if value is None:
            continue
        command.append(f"{key}:={_launch_arg_value(value)}")
    return command


def _nav2_bringup_args(scenario: Scenario, nav2: dict) -> dict[str, object]:
    args: dict[str, object] = {}
    if nav2.get("params") is not None:
        args["params_file"] = nav2["params"]
    if nav2.get("map") is not None:
        args["map"] = nav2["map"]
    if nav2.get("autostart") is not None:
        args["autostart"] = nav2["autostart"]

    runtime = scenario.document.get("runtime") or {}
    if isinstance(runtime, dict) and runtime.get("use_sim_time") is not None:
        args["use_sim_time"] = runtime["use_sim_time"]
    return args


def _launch_arg_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _start_managed_process(spec: LaunchProcessSpec, process_factory: ProcessFactory) -> ManagedProcess:
    spec.log_path.parent.mkdir(parents=True, exist_ok=True)
    log = spec.log_path.open("w", encoding="utf-8")
    try:
        _write_log_header(log, spec.command)
        process = process_factory(
            spec.command,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception:
        log.close()
        raise
    return ManagedProcess(
        name=spec.name,
        command=spec.command,
        process=process,
        log_path=spec.log_path,
        log_handle=log,
    )


def _run_one_scenario(
    scenario: Scenario,
    report_dir: Path,
    startup_timeout: float,
    preflight_skipped: bool,
    wait_for_clock: bool,
    clock_timeout: float,
    execute_nav2: bool,
    launch_scenario_stack: bool,
    wait_for_ros_graph: bool,
    ros_graph_timeout: float,
    wait_for_nav2: bool,
    nav2_timeout: float,
    wait_for_navigation_data: bool,
    navigation_data_timeout: float,
    reset_world: bool,
    world_reset_timeout: float,
    execute_simulator_steps: bool,
    simulator_step_timeout: float,
    collect_contacts: bool,
    contact_topics: list[str],
    contact_discovery_timeout: float,
    process_factory: ProcessFactory,
    command_runner: CommandRunner,
    nav2_backend_factory: Nav2BackendFactory,
    clock: Clock,
    sleeper: Sleeper,
) -> ScenarioRunResult:
    started = clock()
    artifact_dir = _artifact_dir(report_dir, scenario)
    log_path = artifact_dir / "gazebo.log"
    scenario_copy_path = artifact_dir / "scenario.yaml"
    metadata_path = artifact_dir / "metadata.json"
    process: ProcessLike | None = None
    status = "passed"
    failure_reason: str | None = None
    error_type: str | None = None
    command: list[str] | None = None
    world_arg: str | None = None
    exit_code: int | None = None
    started_at = datetime.now(timezone.utc).isoformat()
    launch_status = "passed"
    launch_failure_reason: str | None = None
    launch_duration = 0.0
    clock_command = _clock_echo_command() if wait_for_clock else None
    clock_ready: bool | None = None
    clock_wait_seconds: float | None = None
    clock_error: str | None = None
    clock_failure_reason: str | None = None
    nav2_status: str | None = None
    nav2_execution_offset: float | None = None
    nav2_steps: list[StepRunResult] = []
    nav2_assertions = []
    nav2_metrics = {}
    managed_processes: list[ManagedProcess] = []
    launch_process_metadata: list[dict] = []
    launch_process_steps: list[StepRunResult] = []
    launch_stack_started = False
    launch_specs: list[LaunchProcessSpec] = []
    ros_graph_ready: bool | None = None
    ros_graph_wait_seconds: float | None = None
    ros_graph_error: str | None = None
    ros_graph_failure_reason: str | None = None
    ros_graph_commands = _ros_graph_commands() if wait_for_ros_graph else []
    nav2_ready: bool | None = None
    nav2_wait_seconds: float | None = None
    nav2_error: str | None = None
    nav2_failure_reason: str | None = None
    navigation_data_topics = _navigation_data_topics(scenario) if wait_for_navigation_data else []
    navigation_data_commands = [
        _topic_echo_once_command(topic) for topic in navigation_data_topics
    ]
    navigation_data_ready: bool | None = None
    navigation_data_wait_seconds: float | None = None
    navigation_data_error: str | None = None
    navigation_data_failure_reason: str | None = None
    world_reset_command: list[str] | None = None
    world_reset_succeeded: bool | None = None
    world_reset_seconds: float | None = None
    world_reset_error: str | None = None
    world_reset_failure_reason: str | None = None
    simulator_steps_result: GazeboSimulatorStepsResult | None = None
    scheduled_simulator_steps_result: GazeboSimulatorStepsResult | None = None
    contact_collection: ContactCollectionResult | None = None
    contact_processes: list[ManagedProcess] = []
    contact_started: float | None = None

    try:
        command = gazebo_sim_command(scenario)
        world_arg = command[-1]
        if reset_world:
            world_reset_command = gazebo_world_reset_command(scenario, timeout=world_reset_timeout)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        _copy_scenario_file(scenario, scenario_copy_path)
        if launch_scenario_stack:
            launch_specs = scenario_stack_launch_specs(scenario, artifact_dir)
            if not launch_specs:
                raise GazeboSimError(
                    "--launch-scenario-stack requires simulator.launch or nav2.bringup in the scenario."
                )
        with log_path.open("w", encoding="utf-8") as log:
            _write_log_header(log, command)
            process = process_factory(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for spec in launch_specs:
                managed_processes.append(_start_managed_process(spec, process_factory))
            launch_stack_started = bool(managed_processes)
            if startup_timeout > 0:
                sleeper(startup_timeout)
            return_code = process.poll()
            if return_code is not None:
                exit_code = return_code
                status = "failed"
                error_type = "startup_exit"
                failure_reason = f"Gazebo Sim exited during startup with code {return_code}."
                launch_status = "failed"
                launch_failure_reason = failure_reason
            for managed in managed_processes:
                managed_return_code = managed.process.poll()
                if managed_return_code is not None:
                    managed.exit_code = managed_return_code
                    launch_process_steps.append(
                        StepRunResult(
                            index=len(launch_process_steps),
                            kind=managed.name,
                            status="failed",
                            duration_seconds=clock() - started,
                            failure_reason=(
                                f"Scenario launch process {managed.name} exited during "
                                f"startup with code {managed_return_code}."
                            ),
                        )
                    )
                    if status == "passed":
                        status = "failed"
                        error_type = f"{_safe_name(managed.name)}_exit"
                        failure_reason = launch_process_steps[-1].failure_reason
                else:
                    launch_process_steps.append(
                        StepRunResult(
                            index=len(launch_process_steps),
                            kind=managed.name,
                            status="passed",
                            duration_seconds=clock() - started,
                            failure_reason=None,
                        )
                    )
            launch_duration = clock() - started
            if status == "passed" and reset_world:
                world_reset_started = clock()
                (
                    world_reset_succeeded,
                    world_reset_error,
                    world_reset_failure_reason,
                ) = _reset_gazebo_world(
                    command_runner=command_runner,
                    command=world_reset_command or gazebo_world_reset_command(scenario, timeout=world_reset_timeout),
                    timeout=world_reset_timeout,
                )
                world_reset_seconds = clock() - world_reset_started
                if not world_reset_succeeded:
                    status = "failed"
                    error_type = world_reset_error
                    failure_reason = world_reset_failure_reason
            if status == "passed" and collect_contacts:
                contact_started = clock()
                contact_collection, contact_processes = _start_contact_collection(
                    scenario=scenario,
                    artifact_dir=artifact_dir,
                    topics=contact_topics,
                    discovery_timeout=contact_discovery_timeout,
                    command_runner=command_runner,
                    process_factory=process_factory,
                )
                if contact_collection.failure_reason:
                    status = "failed"
                    error_type = contact_collection.error_type
                    failure_reason = contact_collection.failure_reason
            if status == "passed" and execute_simulator_steps:
                simulator_steps_result = _execute_gazebo_simulator_steps(
                    scenario=scenario,
                    command_runner=command_runner,
                    timeout=simulator_step_timeout,
                    clock=clock,
                    sleeper=sleeper,
                    skip_parallel=execute_nav2,
                    scenario_started_at=started,
                )
                if simulator_steps_result.failure_reason:
                    status = "failed"
                    error_type = simulator_steps_result.error_type
                    failure_reason = simulator_steps_result.failure_reason
            if status == "passed" and wait_for_ros_graph:
                ros_graph_started = clock()
                ros_graph_ready, ros_graph_error, ros_graph_failure_reason = _wait_for_ros_graph(
                    command_runner=command_runner,
                    timeout=ros_graph_timeout,
                    clock=clock,
                    sleeper=sleeper,
                )
                ros_graph_wait_seconds = clock() - ros_graph_started
                if not ros_graph_ready:
                    status = "failed"
                    error_type = ros_graph_error
                    failure_reason = ros_graph_failure_reason
            if status == "passed" and wait_for_clock:
                clock_started = clock()
                clock_ready, clock_error, clock_failure_reason = _wait_for_clock(
                    command_runner=command_runner,
                    timeout=clock_timeout,
                )
                clock_wait_seconds = clock() - clock_started
                if not clock_ready:
                    status = "failed"
                    error_type = clock_error
                    failure_reason = clock_failure_reason
            if status == "passed" and wait_for_nav2:
                nav2_started = clock()
                nav2_ready, nav2_error, nav2_failure_reason = _wait_for_nav2_active(
                    scenario=scenario,
                    nav2_backend_factory=nav2_backend_factory,
                    timeout=nav2_timeout,
                )
                nav2_wait_seconds = clock() - nav2_started
                if not nav2_ready:
                    status = "failed"
                    error_type = nav2_error
                    failure_reason = nav2_failure_reason
            if status == "passed" and wait_for_navigation_data:
                navigation_data_started = clock()
                (
                    navigation_data_ready,
                    navigation_data_error,
                    navigation_data_failure_reason,
                ) = _wait_for_navigation_data(
                    command_runner=command_runner,
                    topics=navigation_data_topics,
                    timeout=navigation_data_timeout,
                    clock=clock,
                )
                navigation_data_wait_seconds = clock() - navigation_data_started
                if not navigation_data_ready:
                    status = "failed"
                    error_type = navigation_data_error
                    failure_reason = navigation_data_failure_reason
            if status == "passed" and execute_nav2:
                scheduled_runner: _ScheduledSimulatorRunner | None = None
                try:
                    if execute_simulator_steps:
                        scheduled_runner = _ScheduledSimulatorRunner(
                            scenario=scenario,
                            command_runner=command_runner,
                            timeout=simulator_step_timeout,
                            clock=clock,
                            sleeper=sleeper,
                            scenario_started_at=started,
                        )
                        if scheduled_runner.has_work:
                            scheduled_runner.start()
                        else:
                            scheduled_runner = None
                    nav2_scenario = _nav2_execution_scenario(scenario)
                    nav2_execution_offset = max(0.0, clock() - started)
                    nav2_result = ExecutionEngine(
                        nav2_backend_factory(nav2_scenario),
                        clock=clock,
                    ).run(nav2_scenario)
                    nav2_status = nav2_result.status
                    nav2_steps = nav2_result.steps or []
                    nav2_assertions = nav2_result.assertions or []
                    nav2_metrics = nav2_result.metrics or {}
                    if nav2_result.status != "passed":
                        status = "failed"
                        error_type = "nav2_execution_failed"
                        failure_reason = nav2_result.failure_reason
                except Exception as exc:
                    status = "failed"
                    error_type = type(exc).__name__
                    failure_reason = str(exc)
                    nav2_status = "failed"
                finally:
                    if scheduled_runner is not None:
                        scheduled_simulator_steps_result = scheduled_runner.join()
                        if (
                            scheduled_simulator_steps_result is not None
                            and scheduled_simulator_steps_result.failure_reason
                            and status == "passed"
                        ):
                            status = "failed"
                            error_type = scheduled_simulator_steps_result.error_type
                            failure_reason = scheduled_simulator_steps_result.failure_reason
    except Exception as exc:
        status = "failed"
        error_type = type(exc).__name__
        failure_reason = str(exc)
        launch_status = "failed"
        launch_failure_reason = failure_reason
        launch_duration = clock() - started
    finally:
        for managed in reversed(contact_processes):
            stopped_code = _stop_process(managed.process)
            if managed.exit_code is None:
                managed.exit_code = stopped_code
            managed.log_handle.close()
        for managed in reversed(managed_processes):
            stopped_code = _stop_process(managed.process)
            if managed.exit_code is None:
                managed.exit_code = stopped_code
            managed.log_handle.close()
        if process is not None:
            stopped_code = _stop_process(process)
            if exit_code is None:
                exit_code = stopped_code

    duration = clock() - started
    if contact_collection is not None and contact_collection.failure_reason is None:
        contact_collection = _finish_contact_collection(
            contact_collection,
            duration_seconds=clock() - contact_started if contact_started is not None else 0.0,
        )
    combined_simulator_steps_result = _combine_simulator_steps_results(
        simulator_steps_result,
        scheduled_simulator_steps_result,
    )
    launch_process_metadata = [
        {
            "name": managed.name,
            "command": managed.command,
            "log": str(managed.log_path),
            "exit_code": managed.exit_code,
        }
        for managed in managed_processes
    ]
    metadata = {
        "scenario_id": scenario.scenario_id,
        "scenario_name": scenario.name,
        "scenario_path": str(scenario.path),
        "mode": "gazebo_sim",
        "status": status,
        "error_type": error_type,
        "failure_reason": failure_reason,
        "preflight_skipped": preflight_skipped,
        "command": command,
        "world": world_arg,
        "started_at": started_at,
        "duration_seconds": round(float(duration), 6),
        "exit_code": exit_code,
        "artifact_dir": str(artifact_dir),
        "scenario_copy": str(scenario_copy_path),
        "gazebo_log": str(log_path),
        "clock_requested": wait_for_clock,
        "clock_command": clock_command,
        "clock_timeout": clock_timeout if wait_for_clock else None,
        "clock_ready": clock_ready,
        "clock_wait_seconds": (
            round(float(clock_wait_seconds), 6) if clock_wait_seconds is not None else None
        ),
        "clock_error": clock_error,
        "execute_nav2": execute_nav2,
        "nav2_status": nav2_status,
        "launch_scenario_stack": launch_scenario_stack,
        "launch_stack_started": launch_stack_started,
        "launch_processes": launch_process_metadata,
        "ros_graph_requested": wait_for_ros_graph,
        "ros_graph_commands": ros_graph_commands,
        "ros_graph_timeout": ros_graph_timeout if wait_for_ros_graph else None,
        "ros_graph_ready": ros_graph_ready,
        "ros_graph_wait_seconds": (
            round(float(ros_graph_wait_seconds), 6) if ros_graph_wait_seconds is not None else None
        ),
        "ros_graph_error": ros_graph_error,
        "nav2_readiness_requested": wait_for_nav2,
        "nav2_timeout": nav2_timeout if wait_for_nav2 else None,
        "nav2_ready": nav2_ready,
        "nav2_wait_seconds": (
            round(float(nav2_wait_seconds), 6) if nav2_wait_seconds is not None else None
        ),
        "nav2_error": nav2_error,
        "navigation_data_requested": wait_for_navigation_data,
        "navigation_data_topics": navigation_data_topics,
        "navigation_data_commands": navigation_data_commands,
        "navigation_data_timeout": navigation_data_timeout if wait_for_navigation_data else None,
        "navigation_data_ready": navigation_data_ready,
        "navigation_data_wait_seconds": (
            round(float(navigation_data_wait_seconds), 6)
            if navigation_data_wait_seconds is not None
            else None
        ),
        "navigation_data_error": navigation_data_error,
        "world_reset_requested": reset_world,
        "world_reset_command": world_reset_command,
        "world_reset_timeout": world_reset_timeout if reset_world else None,
        "world_reset_succeeded": world_reset_succeeded,
        "world_reset_seconds": (
            round(float(world_reset_seconds), 6) if world_reset_seconds is not None else None
        ),
        "world_reset_error": world_reset_error,
        "execute_simulator_steps": execute_simulator_steps,
        "simulator_step_timeout": simulator_step_timeout if execute_simulator_steps else None,
        "scheduled_simulator_steps": scheduled_simulator_steps_result is not None,
        "simulator_steps_executed": (
            combined_simulator_steps_result.executed_count if combined_simulator_steps_result else 0
        ),
        "simulator_steps_skipped": (
            combined_simulator_steps_result.skipped_count if combined_simulator_steps_result else 0
        ),
        "simulator_step_commands": (
            combined_simulator_steps_result.commands if combined_simulator_steps_result else []
        ),
        "simulator_step_error": (
            combined_simulator_steps_result.error_type if combined_simulator_steps_result else None
        ),
        "spawned_entities": (
            combined_simulator_steps_result.spawned_entities if combined_simulator_steps_result else []
        ),
        "moved_entities": (
            combined_simulator_steps_result.moved_entities if combined_simulator_steps_result else []
        ),
        "deleted_entities": (
            combined_simulator_steps_result.deleted_entities if combined_simulator_steps_result else []
        ),
        "contact_collection_requested": collect_contacts,
        "contact_topics": contact_collection.topics if contact_collection else contact_topics,
        "contact_commands": contact_collection.commands if contact_collection else [],
        "contact_logs": contact_collection.logs if contact_collection else [],
        "contact_discovery_timeout": contact_discovery_timeout if collect_contacts else None,
        "contact_collection_ready": contact_collection.ready if contact_collection else None,
        "contact_collection_seconds": (
            round(float(contact_collection.duration_seconds), 6)
            if contact_collection and contact_collection.duration_seconds is not None
            else None
        ),
        "contact_collection_error": (
            contact_collection.error_type if contact_collection else None
        ),
        "contact_pairs": contact_collection.contact_pairs if contact_collection else [],
        "collision_count": contact_collection.collision_count if contact_collection else None,
        "collision_free": contact_collection.collision_free if contact_collection else None,
    }

    steps = [
        StepRunResult(
            index=0,
            kind="gazebo_sim.launch",
            status=launch_status,
            duration_seconds=launch_duration,
            failure_reason=launch_failure_reason,
        )
    ]
    steps.extend(_offset_steps(launch_process_steps, offset=len(steps)))
    if reset_world:
        steps.append(
            StepRunResult(
                index=len(steps),
                kind="gazebo_sim.reset_world",
                status="passed" if world_reset_succeeded else "failed",
                duration_seconds=world_reset_seconds or 0.0,
                failure_reason=world_reset_failure_reason,
            )
        )
    if execute_simulator_steps and simulator_steps_result is not None:
        steps.extend(_offset_steps(simulator_steps_result.steps, offset=len(steps)))
    if execute_simulator_steps and scheduled_simulator_steps_result is not None:
        steps.extend(_offset_steps(scheduled_simulator_steps_result.steps, offset=len(steps)))
    if collect_contacts:
        steps.append(
            StepRunResult(
                index=len(steps),
                kind="gazebo_sim.contact_collection",
                status=(
                    "passed"
                    if contact_collection is not None and contact_collection.failure_reason is None
                    else "failed"
                ),
                duration_seconds=(
                    contact_collection.duration_seconds
                    if contact_collection and contact_collection.duration_seconds is not None
                    else 0.0
                ),
                failure_reason=(
                    contact_collection.failure_reason if contact_collection else "Contact collection did not start."
                ),
            )
        )
    if wait_for_ros_graph:
        steps.append(
            StepRunResult(
                index=len(steps),
                kind="ros_graph.readiness",
                status="passed" if ros_graph_ready else "failed",
                duration_seconds=ros_graph_wait_seconds or 0.0,
                failure_reason=ros_graph_failure_reason,
            )
        )
    if wait_for_clock:
        steps.append(
            StepRunResult(
                index=len(steps),
                kind="gazebo_sim.clock",
                status="passed" if clock_ready else "failed",
                duration_seconds=clock_wait_seconds or 0.0,
                failure_reason=clock_failure_reason,
            )
        )
    if wait_for_nav2:
        steps.append(
            StepRunResult(
                index=len(steps),
                kind="nav2.readiness",
                status="passed" if nav2_ready else "failed",
                duration_seconds=nav2_wait_seconds or 0.0,
                failure_reason=nav2_failure_reason,
            )
        )
    if wait_for_navigation_data:
        steps.append(
            StepRunResult(
                index=len(steps),
                kind="navigation_data.readiness",
                status="passed" if navigation_data_ready else "failed",
                duration_seconds=navigation_data_wait_seconds or 0.0,
                failure_reason=navigation_data_failure_reason,
            )
        )
    if execute_nav2:
        steps.extend(
            _offset_steps(
                nav2_steps,
                offset=len(steps),
                time_offset_delta=nav2_execution_offset or 0.0,
            )
        )

    metrics = {
        "simulator_started": launch_status == "passed",
        "simulator_backend": "gazebo_sim",
        "preflight_skipped": preflight_skipped,
        "error_type": error_type or "",
        "artifact_dir": str(artifact_dir),
        "gazebo_log": str(log_path),
        "scenario_copy": str(scenario_copy_path),
        "metadata": str(metadata_path),
        "world": world_arg or "",
        "simulator_log": str(log_path),
        "clock_requested": wait_for_clock,
        "nav2_executed": execute_nav2 and nav2_status is not None,
        "nav2_status": nav2_status or "",
        "launch_scenario_stack": launch_scenario_stack,
        "launch_stack_started": launch_stack_started,
        "launch_process_count": len(launch_process_metadata),
        "ros_graph_requested": wait_for_ros_graph,
        "nav2_readiness_requested": wait_for_nav2,
        "navigation_data_requested": wait_for_navigation_data,
        "world_reset_requested": reset_world,
        "execute_simulator_steps": execute_simulator_steps,
        "contact_collection_requested": collect_contacts,
    }
    if reset_world:
        metrics.update(
            {
                "world_reset_succeeded": bool(world_reset_succeeded),
                "world_reset_seconds": round(float(world_reset_seconds or 0.0), 6),
                "world_reset_timeout": world_reset_timeout,
                "world_reset_command": " ".join(world_reset_command or []),
                "world_reset_error": world_reset_error or "",
            }
        )
    if execute_simulator_steps:
        simulator_metrics_result = combined_simulator_steps_result or GazeboSimulatorStepsResult(
            steps=[],
            commands=[],
            spawned_entities=[],
            moved_entities=[],
            deleted_entities=[],
        )
        metrics.update(
            {
                "scheduled_simulator_steps": scheduled_simulator_steps_result is not None,
                "simulator_steps_executed": simulator_metrics_result.executed_count,
                "simulator_steps_skipped": simulator_metrics_result.skipped_count,
                "simulator_step_timeout": simulator_step_timeout,
                "simulator_step_error": simulator_metrics_result.error_type or "",
                "simulator_step_commands": "; ".join(
                    " ".join(command) for command in simulator_metrics_result.commands
                ),
                "spawned_entities": ", ".join(simulator_metrics_result.spawned_entities),
                "moved_entities": ", ".join(simulator_metrics_result.moved_entities),
                "deleted_entities": ", ".join(simulator_metrics_result.deleted_entities),
            }
        )
    if collect_contacts:
        contact_collection = contact_collection or ContactCollectionResult(
            requested=True,
            topics=contact_topics,
            commands=[],
            logs=[],
            error_type="contact_collection_not_started",
            failure_reason="Contact collection did not start.",
        )
        metrics.update(
            {
                "contact_collection_ready": bool(contact_collection.ready),
                "contact_topics": ", ".join(contact_collection.topics),
                "contact_commands": "; ".join(" ".join(command) for command in contact_collection.commands),
                "contact_logs": ", ".join(contact_collection.logs),
                "contact_discovery_timeout": contact_discovery_timeout,
                "contact_collection_seconds": round(float(contact_collection.duration_seconds or 0.0), 6),
                "contact_collection_error": contact_collection.error_type or "",
                "contact_pairs": ", ".join(contact_collection.contact_pairs or []),
            }
        )
        if contact_collection.collision_count is not None:
            metrics["collision_count"] = contact_collection.collision_count
            metrics["collision_free"] = bool(contact_collection.collision_free)
    if wait_for_ros_graph:
        metrics.update(
            {
                "ros_graph_ready": bool(ros_graph_ready),
                "ros_graph_wait_seconds": round(float(ros_graph_wait_seconds or 0.0), 6),
                "ros_graph_timeout": ros_graph_timeout,
                "ros_graph_commands": "; ".join(" ".join(command) for command in ros_graph_commands),
                "ros_graph_error": ros_graph_error or "",
            }
        )
    if wait_for_nav2:
        metrics.update(
            {
                "nav2_ready": bool(nav2_ready),
                "nav2_wait_seconds": round(float(nav2_wait_seconds or 0.0), 6),
                "nav2_timeout": nav2_timeout,
                "nav2_error": nav2_error or "",
            }
        )
    if wait_for_navigation_data:
        metrics.update(
            {
                "navigation_data_ready": bool(navigation_data_ready),
                "navigation_data_wait_seconds": round(float(navigation_data_wait_seconds or 0.0), 6),
                "navigation_data_timeout": navigation_data_timeout,
                "navigation_data_topics": ", ".join(navigation_data_topics),
                "navigation_data_commands": "; ".join(
                    " ".join(command) for command in navigation_data_commands
                ),
                "navigation_data_error": navigation_data_error or "",
            }
        )
    for launch_metadata in launch_process_metadata:
        metrics[f"{_metric_key(str(launch_metadata['name']))}_log"] = str(launch_metadata["log"])
    if wait_for_clock:
        metrics.update(
            {
                "clock_ready": bool(clock_ready),
                "clock_wait_seconds": round(float(clock_wait_seconds or 0.0), 6),
                "clock_timeout": clock_timeout,
                "clock_command": " ".join(clock_command or []),
            }
        )
    if command:
        metrics["simulator_command"] = " ".join(command)
    metrics.update(nav2_metrics)
    if collect_contacts and contact_collection is not None and contact_collection.collision_count is not None:
        metrics["collision_count"] = contact_collection.collision_count
        metrics["collision_free"] = bool(contact_collection.collision_free)

    assertion_results = nav2_assertions
    if collect_contacts:
        assertion_results = _merge_assertions(
            assertion_results,
            _evaluate_collision_free_assertions(scenario, metrics),
        )
        if status == "passed" and not assertion_results_passed(assertion_results):
            status = "failed"
            failed_assertion = first_failed_assertion(assertion_results)
            failure_reason = failed_assertion.message if failed_assertion else "Assertion failed."
            error_type = "assertion_failed"
            metrics["error_type"] = error_type

    metadata["status"] = status
    metadata["error_type"] = error_type
    metadata["failure_reason"] = failure_reason
    _write_metadata(metadata, metadata_path)

    return ScenarioRunResult(
        scenario_id=scenario.scenario_id,
        name=scenario.name,
        path=str(scenario.path),
        tags=sorted(scenario.tags),
        status=status,
        step_count=scenario.step_count,
        assertion_count=scenario.assertion_count,
        duration_seconds=duration,
        failure_reason=failure_reason,
        steps=steps,
        assertions=assertion_results,
        metrics=metrics,
    )


def _clock_echo_command() -> list[str]:
    return ["ros2", "topic", "echo", "/clock", "--once"]


def _topic_echo_once_command(topic: str) -> list[str]:
    return ["ros2", "topic", "echo", topic, "--once"]


def _ros_graph_commands() -> list[list[str]]:
    return [
        ["ros2", "node", "list"],
        ["ros2", "topic", "list"],
    ]


def _default_command_runner(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def _default_nav2_backend_factory(scenario: Scenario) -> object:
    from nav2_scenario_runner.backends.ros import RosAttachBackend

    return RosAttachBackend.from_scenario(scenario)


def _offset_steps(
    steps: list[StepRunResult],
    offset: int,
    time_offset_delta: float = 0.0,
) -> list[StepRunResult]:
    return [
        StepRunResult(
            index=step.index + offset,
            kind=step.kind,
            status=step.status,
            duration_seconds=step.duration_seconds,
            failure_reason=step.failure_reason,
            time_offset_seconds=(
                step.time_offset_seconds + time_offset_delta
                if step.time_offset_seconds is not None
                else None
            ),
        )
        for step in steps
    ]


def _wait_for_clock(
    command_runner: CommandRunner,
    timeout: float,
) -> tuple[bool, str | None, str | None]:
    command = _clock_echo_command()
    try:
        completed = command_runner(command, timeout)
    except subprocess.TimeoutExpired:
        return False, "clock_timeout", f"Timed out waiting for /clock after {timeout:g}s."
    except Exception as exc:
        return False, type(exc).__name__, str(exc)

    if completed.returncode == 0:
        return True, None, None

    reason = (
        _first_output_line(completed.stderr)
        or _first_output_line(completed.stdout)
        or f"ros2 topic echo /clock --once exited with code {completed.returncode}."
    )
    return False, "clock_unavailable", f"Clock topic did not become ready: {reason}"


def _wait_for_ros_graph(
    command_runner: CommandRunner,
    timeout: float,
    clock: Clock,
    sleeper: Sleeper,
) -> tuple[bool, str | None, str | None]:
    deadline = clock() + timeout
    commands = _ros_graph_commands()
    last_reason = ""

    while True:
        remaining = deadline - clock()
        if remaining < 0:
            break
        command_timeout = max(0.1, min(remaining, 2.0))
        all_ready = True
        for command in commands:
            try:
                completed = command_runner(command, command_timeout)
            except subprocess.TimeoutExpired:
                return False, "ros_graph_timeout", f"Timed out waiting for ROS graph after {timeout:g}s."
            except Exception as exc:
                return False, type(exc).__name__, str(exc)

            if completed.returncode != 0:
                all_ready = False
                last_reason = (
                    _first_output_line(completed.stderr)
                    or _first_output_line(completed.stdout)
                    or f"{' '.join(command)} exited with code {completed.returncode}."
                )
                break

        if all_ready:
            return True, None, None

        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(0.25, remaining))

    reason = f"Timed out waiting for ROS graph after {timeout:g}s."
    if last_reason:
        reason = f"{reason} Last error: {last_reason}"
    return False, "ros_graph_timeout", reason


def _wait_for_nav2_active(
    scenario: Scenario,
    nav2_backend_factory: Nav2BackendFactory,
    timeout: float,
) -> tuple[bool, str | None, str | None]:
    backend = None
    failure: tuple[bool, str | None, str | None] | None = None
    try:
        backend = nav2_backend_factory(scenario)
        backend.wait_for_nav2_active(timeout=timeout)
        failure = (True, None, None)
    except Exception as exc:
        failure = (False, type(exc).__name__, str(exc))
    finally:
        if backend is not None:
            try:
                backend.close()
            except Exception as exc:
                if failure is not None and failure[0]:
                    failure = (False, type(exc).__name__, str(exc))

    if failure is None:
        return False, "nav2_unavailable", "Nav2 backend was not created."
    return failure


def _wait_for_navigation_data(
    command_runner: CommandRunner,
    topics: list[str],
    timeout: float,
    clock: Clock,
) -> tuple[bool, str | None, str | None]:
    deadline = clock() + timeout
    for topic in topics:
        remaining = deadline - clock()
        if remaining <= 0:
            return False, "navigation_data_timeout", (
                f"Timed out waiting for navigation data after {timeout:g}s."
            )
        command = _topic_echo_once_command(topic)
        try:
            completed = command_runner(command, max(0.1, remaining))
        except subprocess.TimeoutExpired:
            return False, "navigation_data_timeout", (
                f"Timed out waiting for navigation data topic {topic} after {timeout:g}s."
            )
        except Exception as exc:
            return False, type(exc).__name__, str(exc)

        if completed.returncode != 0:
            reason = (
                _first_output_line(completed.stderr)
                or _first_output_line(completed.stdout)
                or f"{' '.join(command)} exited with code {completed.returncode}."
            )
            return False, "navigation_data_unavailable", (
                f"Navigation data topic {topic} did not become ready: {reason}"
            )

    return True, None, None


def _reset_gazebo_world(
    command_runner: CommandRunner,
    command: list[str],
    timeout: float,
) -> tuple[bool, str | None, str | None]:
    try:
        completed = command_runner(command, timeout)
    except subprocess.TimeoutExpired:
        return False, "world_reset_timeout", f"Timed out resetting Gazebo world after {timeout:g}s."
    except Exception as exc:
        return False, type(exc).__name__, str(exc)

    if completed.returncode == 0:
        return True, None, None

    reason = (
        _first_output_line(completed.stderr)
        or _first_output_line(completed.stdout)
        or f"{' '.join(command)} exited with code {completed.returncode}."
    )
    return False, "world_reset_failed", f"Gazebo world reset failed: {reason}"


def _start_contact_collection(
    scenario: Scenario,
    artifact_dir: Path,
    topics: list[str],
    discovery_timeout: float,
    command_runner: CommandRunner,
    process_factory: ProcessFactory,
) -> tuple[ContactCollectionResult, list[ManagedProcess]]:
    selected_topics = list(topics)
    commands: list[list[str]] = []
    logs: list[str] = []
    processes: list[ManagedProcess] = []

    if not selected_topics:
        discovered, error_type, failure_reason = _discover_contact_topics(
            command_runner=command_runner,
            timeout=discovery_timeout,
        )
        if failure_reason:
            return (
                ContactCollectionResult(
                    requested=True,
                    topics=[],
                    commands=[],
                    logs=[],
                    ready=False,
                    error_type=error_type,
                    failure_reason=failure_reason,
                ),
                [],
            )
        selected_topics = discovered

    if not selected_topics:
        return (
            ContactCollectionResult(
                requested=True,
                topics=[],
                commands=[],
                logs=[],
                ready=False,
                error_type="contact_topics_unavailable",
                failure_reason="No Gazebo contact topics were found. Configure --contact-topic or add contact sensors.",
            ),
            [],
        )

    for topic in selected_topics:
        command = _contact_echo_command(topic)
        log_path = artifact_dir / f"contacts_{_safe_name(topic)}.log"
        commands.append(command)
        logs.append(str(log_path))
        try:
            processes.append(
                _start_managed_process(
                    LaunchProcessSpec(
                        name=f"contacts:{topic}",
                        command=command,
                        log_path=log_path,
                    ),
                    process_factory=process_factory,
                )
            )
        except Exception as exc:
            for process in reversed(processes):
                _stop_process(process.process)
                process.log_handle.close()
            return (
                ContactCollectionResult(
                    requested=True,
                    topics=selected_topics,
                    commands=commands,
                    logs=logs,
                    ready=False,
                    error_type=type(exc).__name__,
                    failure_reason=str(exc),
                ),
                [],
            )

    return (
        ContactCollectionResult(
            requested=True,
            topics=selected_topics,
            commands=commands,
            logs=logs,
            ready=True,
        ),
        processes,
    )


def _finish_contact_collection(
    result: ContactCollectionResult,
    duration_seconds: float,
) -> ContactCollectionResult:
    contact_count = 0
    contact_pairs: list[str] = []
    for log in result.logs:
        text = Path(log).read_text(encoding="utf-8") if Path(log).exists() else ""
        parsed_count, parsed_pairs = _parse_contact_log(text)
        contact_count += parsed_count
        contact_pairs.extend(parsed_pairs)

    return ContactCollectionResult(
        requested=result.requested,
        topics=result.topics,
        commands=result.commands,
        logs=result.logs,
        collision_count=contact_count,
        collision_free=contact_count == 0,
        contact_pairs=_dedupe(contact_pairs),
        ready=result.ready,
        error_type=result.error_type,
        failure_reason=result.failure_reason,
        duration_seconds=duration_seconds,
    )


def _discover_contact_topics(
    command_runner: CommandRunner,
    timeout: float,
) -> tuple[list[str], str | None, str | None]:
    command = ["gz", "topic", "-l"]
    try:
        completed = command_runner(command, timeout)
    except subprocess.TimeoutExpired:
        return [], "contact_topic_discovery_timeout", (
            f"Timed out discovering Gazebo contact topics after {timeout:g}s."
        )
    except Exception as exc:
        return [], type(exc).__name__, str(exc)

    if completed.returncode != 0:
        reason = (
            _first_output_line(completed.stderr)
            or _first_output_line(completed.stdout)
            or f"{' '.join(command)} exited with code {completed.returncode}."
        )
        return [], "contact_topic_discovery_failed", f"Gazebo contact topic discovery failed: {reason}"

    topics = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip() and "contact" in line.strip().lower()
    ]
    return _dedupe(topics), None, None


def _contact_echo_command(topic: str) -> list[str]:
    return ["gz", "topic", "-e", "-t", topic]


def _parse_contact_log(text: str) -> tuple[int, list[str]]:
    contact_count = len(re.findall(r"(?m)^\s*contact\s*\{", text))
    names = re.findall(r"(?m)^\s*name:\s*\"([^\"]+)\"", text)
    pairs = []
    for index in range(0, len(names) - 1, 2):
        pairs.append(f"{names[index]} <-> {names[index + 1]}")
    return contact_count, pairs


def _evaluate_collision_free_assertions(scenario: Scenario, metrics: dict) -> list:
    raw_assertions = scenario.document.get("assertions") or []
    if not isinstance(raw_assertions, list):
        return []

    results = []
    for index, raw_assertion in enumerate(raw_assertions):
        if not isinstance(raw_assertion, dict) or len(raw_assertion) != 1:
            continue
        kind, params = next(iter(raw_assertion.items()))
        if kind != "collision_free":
            continue
        temp = Scenario(
            path=scenario.path,
            document={"assertions": [{"collision_free": params or {}}]},
            scenario_id=scenario.scenario_id,
            name=scenario.name,
            tags=scenario.tags,
            step_count=scenario.step_count,
            assertion_count=1,
        )
        result = evaluate_assertions(temp, metrics=metrics, duration_seconds=0.0)[0]
        results.append(replace(result, index=index))
    return results


def _merge_assertions(existing: list, updates: list) -> list:
    if not updates:
        return existing
    by_index = {assertion.index: assertion for assertion in existing}
    for assertion in updates:
        by_index[assertion.index] = assertion
    return [by_index[index] for index in sorted(by_index)]


@dataclass(frozen=True)
class _SimulatorBranch:
    name: str
    scenario: Scenario


class _ScheduledSimulatorRunner:
    def __init__(
        self,
        scenario: Scenario,
        command_runner: CommandRunner,
        timeout: float,
        clock: Clock,
        sleeper: Sleeper,
        scenario_started_at: float,
    ) -> None:
        self._branches = _parallel_simulator_branch_scenarios(scenario)
        self._command_runner = command_runner
        self._timeout = timeout
        self._clock = clock
        self._sleeper = sleeper
        self._scenario_started_at = scenario_started_at
        self._threads: list[threading.Thread] = []
        self._results: list[GazeboSimulatorStepsResult] = []
        self._lock = threading.Lock()

    @property
    def has_work(self) -> bool:
        return bool(self._branches)

    def start(self) -> None:
        for branch in self._branches:
            thread = threading.Thread(
                target=self._run_branch,
                args=(branch,),
                name=f"gazebo-sim-scenario-branch-{branch.name}",
            )
            thread.start()
            self._threads.append(thread)

    def join(self) -> GazeboSimulatorStepsResult | None:
        for thread in self._threads:
            thread.join()
        return _combine_simulator_steps_results(*self._results)

    def _run_branch(self, branch: _SimulatorBranch) -> None:
        try:
            result = _execute_gazebo_simulator_steps(
                scenario=branch.scenario,
                command_runner=self._command_runner,
                timeout=self._timeout,
                clock=self._clock,
                sleeper=self._sleeper,
                scenario_started_at=self._scenario_started_at,
            )
        except Exception as exc:
            result = GazeboSimulatorStepsResult(
                steps=[
                    StepRunResult(
                        index=0,
                        kind=f"gazebo_sim.parallel.{branch.name}",
                        status="failed",
                        duration_seconds=0.0,
                        failure_reason=str(exc),
                        time_offset_seconds=max(0.0, self._clock() - self._scenario_started_at),
                    )
                ],
                commands=[],
                spawned_entities=[],
                moved_entities=[],
                deleted_entities=[],
                error_type=type(exc).__name__,
                failure_reason=str(exc),
            )
        result = _prefix_simulator_step_kinds(result, branch.name)
        with self._lock:
            self._results.append(result)


def _combine_simulator_steps_results(
    *results: GazeboSimulatorStepsResult | None,
) -> GazeboSimulatorStepsResult | None:
    available = [result for result in results if result is not None]
    if not available:
        return None

    combined = GazeboSimulatorStepsResult(
        steps=[],
        commands=[],
        spawned_entities=[],
        moved_entities=[],
        deleted_entities=[],
    )
    for result in available:
        combined.steps.extend(_offset_steps(result.steps, offset=len(combined.steps)))
        combined.commands.extend(result.commands)
        combined.spawned_entities.extend(result.spawned_entities)
        combined.moved_entities.extend(result.moved_entities)
        combined.deleted_entities.extend(result.deleted_entities)
        combined.executed_count += result.executed_count
        combined.skipped_count += result.skipped_count
        if result.failure_reason and combined.failure_reason is None:
            combined.error_type = result.error_type
            combined.failure_reason = result.failure_reason

    combined.spawned_entities = _dedupe(combined.spawned_entities)
    combined.moved_entities = _dedupe(combined.moved_entities)
    combined.deleted_entities = _dedupe(combined.deleted_entities)
    return combined


def _prefix_simulator_step_kinds(
    result: GazeboSimulatorStepsResult,
    branch_name: str,
) -> GazeboSimulatorStepsResult:
    prefix = f"gazebo_sim.parallel.{branch_name}."
    steps = []
    for step in result.steps:
        kind = step.kind
        if kind.startswith("gazebo_sim.parallel."):
            pass
        elif kind.startswith("gazebo_sim."):
            kind = prefix + kind.removeprefix("gazebo_sim.")
        steps.append(
            StepRunResult(
                index=step.index,
                kind=kind,
                status=step.status,
                duration_seconds=step.duration_seconds,
                failure_reason=step.failure_reason,
                time_offset_seconds=step.time_offset_seconds,
            )
        )
    return GazeboSimulatorStepsResult(
        steps=steps,
        commands=result.commands,
        spawned_entities=result.spawned_entities,
        moved_entities=result.moved_entities,
        deleted_entities=result.deleted_entities,
        executed_count=result.executed_count,
        skipped_count=result.skipped_count,
        error_type=result.error_type,
        failure_reason=result.failure_reason,
    )


def _nav2_execution_scenario(scenario: Scenario) -> Scenario:
    raw_steps = scenario.document.get("steps") or []
    if not isinstance(raw_steps, list):
        return scenario

    expanded_steps: list[dict] = []
    changed = False
    for raw_step in raw_steps:
        kind, params = _step_kind_and_params(raw_step)
        if kind == "parallel":
            changed = True
            for branch in _parallel_branches(params):
                branch_steps = _branch_steps(branch)
                if _branch_has_nav2_steps(branch_steps):
                    expanded_steps.extend(
                        step
                        for step in branch_steps
                        if _step_kind_and_params(step)[0] in NAV2_EXECUTABLE_STEP_KINDS
                    )
            continue
        if kind in NAV2_EXECUTABLE_STEP_KINDS:
            expanded_steps.append(raw_step)
        else:
            changed = True

    if not changed:
        return scenario

    document = dict(scenario.document)
    document["steps"] = expanded_steps
    return Scenario(
        path=scenario.path,
        document=document,
        scenario_id=scenario.scenario_id,
        name=scenario.name,
        tags=scenario.tags,
        step_count=len(expanded_steps),
        assertion_count=scenario.assertion_count,
    )


def _parallel_simulator_branch_scenarios(scenario: Scenario) -> list[_SimulatorBranch]:
    raw_steps = scenario.document.get("steps") or []
    if not isinstance(raw_steps, list):
        return []

    branches: list[_SimulatorBranch] = []
    for raw_step in raw_steps:
        kind, params = _step_kind_and_params(raw_step)
        if kind != "parallel":
            continue
        for index, branch in enumerate(_parallel_branches(params)):
            steps = _branch_steps(branch)
            if not _branch_has_simulator_steps(steps):
                continue
            branch_name = _branch_name(branch, index)
            document = dict(scenario.document)
            document["steps"] = steps
            branches.append(
                _SimulatorBranch(
                    name=branch_name,
                    scenario=Scenario(
                        path=scenario.path,
                        document=document,
                        scenario_id=f"{scenario.scenario_id}.{branch_name}",
                        name=f"{scenario.name}.{branch_name}",
                        tags=scenario.tags,
                        step_count=len(steps),
                        assertion_count=scenario.assertion_count,
                    ),
                )
            )
    return branches


def _parallel_branches(params: dict) -> list[dict]:
    branches = params.get("branches") or []
    if not isinstance(branches, list):
        raise GazeboSimError("parallel branches must be a list.")
    for index, branch in enumerate(branches):
        if not isinstance(branch, dict):
            raise GazeboSimError(f"parallel branch {index} must be a mapping.")
    return branches


def _branch_steps(branch: dict) -> list[dict]:
    steps = branch.get("steps") or []
    if not isinstance(steps, list):
        raise GazeboSimError("parallel branch steps must be a list.")
    return steps


def _branch_name(branch: dict, index: int) -> str:
    raw_name = branch.get("name") or f"branch_{index}"
    return _safe_name(str(raw_name))


def _branch_has_nav2_steps(steps: list[dict]) -> bool:
    return any(_step_kind_and_params(step)[0] in NAV2_EXECUTABLE_STEP_KINDS for step in steps)


def _branch_has_simulator_steps(steps: list[dict]) -> bool:
    simulator_kinds = {"spawn_obstacle", "move_entity", "delete_entity", "wait", "log"}
    return any(_step_kind_and_params(step)[0] in simulator_kinds for step in steps)


def _step_kind_and_params(raw_step: dict) -> tuple[str, dict]:
    if not isinstance(raw_step, dict) or len(raw_step) != 1:
        raise GazeboSimError("Scenario steps must contain exactly one action.")
    kind, params = next(iter(raw_step.items()))
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise GazeboSimError(f"Step parameters for {kind} must be a mapping.")
    return str(kind), params


def _execute_gazebo_simulator_steps(
    scenario: Scenario,
    command_runner: CommandRunner,
    timeout: float,
    clock: Clock,
    sleeper: Sleeper,
    skip_parallel: bool = False,
    scenario_started_at: float | None = None,
) -> GazeboSimulatorStepsResult:
    result = GazeboSimulatorStepsResult(
        steps=[],
        commands=[],
        spawned_entities=[],
        moved_entities=[],
        deleted_entities=[],
    )
    entity_default_z: dict[str, float] = {}

    for scenario_step in parse_steps(scenario):
        if scenario_step.kind in NAV2_EXECUTABLE_STEP_KINDS:
            result.skipped_count += 1
            continue

        if skip_parallel and scenario_step.kind == "parallel":
            result.skipped_count += 1
            continue

        started = clock()
        step_kind = f"gazebo_sim.{scenario_step.kind}"
        failure_reason: str | None = None
        error_type: str | None = None
        command: list[str] | None = None

        try:
            if scenario_step.kind == "spawn_obstacle":
                command = gazebo_spawn_obstacle_command(scenario, scenario_step.params, timeout=timeout)
                result.commands.append(command)
                _run_gazebo_service_command(
                    command_runner=command_runner,
                    command=command,
                    timeout=timeout,
                    timeout_error="spawn_obstacle_timeout",
                    timeout_reason=(
                        f"Timed out spawning Gazebo obstacle "
                        f"{_required_name(scenario_step.params, 'spawn_obstacle')} after {timeout:g}s."
                    ),
                    failure_error="spawn_obstacle_failed",
                    failure_prefix=(
                        f"Gazebo spawn_obstacle failed for "
                        f"{_required_name(scenario_step.params, 'spawn_obstacle')}"
                    ),
                )
                result.spawned_entities.append(_required_name(scenario_step.params, "spawn_obstacle"))
                entity_default_z[_required_name(scenario_step.params, "spawn_obstacle")] = (
                    _spawn_obstacle_default_z(scenario_step.params)
                )
            elif scenario_step.kind == "move_entity":
                name = _required_name(scenario_step.params, "move_entity")
                last_at = 0.0
                default_z = entity_default_z.get(name, 0.0)
                for waypoint in _move_entity_waypoints(scenario_step.params):
                    at = waypoint["at"]
                    pose = waypoint["pose"]
                    if at > last_at:
                        sleeper(at - last_at)
                    command = gazebo_set_entity_pose_command(
                        scenario,
                        name=name,
                        pose=pose,
                        timeout=timeout,
                        default_z=default_z,
                    )
                    result.commands.append(command)
                    _run_gazebo_service_command(
                        command_runner=command_runner,
                        command=command,
                        timeout=timeout,
                        timeout_error="move_entity_timeout",
                        timeout_reason=f"Timed out moving Gazebo entity {name} after {timeout:g}s.",
                        failure_error="move_entity_failed",
                        failure_prefix=f"Gazebo move_entity failed for {name}",
                    )
                    last_at = at
                result.moved_entities.append(name)
            elif scenario_step.kind == "delete_entity":
                command = gazebo_delete_entity_command(scenario, scenario_step.params, timeout=timeout)
                result.commands.append(command)
                _run_gazebo_service_command(
                    command_runner=command_runner,
                    command=command,
                    timeout=timeout,
                    timeout_error="delete_entity_timeout",
                    timeout_reason=(
                        f"Timed out deleting Gazebo entity "
                        f"{_required_name(scenario_step.params, 'delete_entity')} after {timeout:g}s."
                    ),
                    failure_error="delete_entity_failed",
                    failure_prefix=(
                        f"Gazebo delete_entity failed for "
                        f"{_required_name(scenario_step.params, 'delete_entity')}"
                    ),
                )
                result.deleted_entities.append(_required_name(scenario_step.params, "delete_entity"))
                entity_default_z.pop(_required_name(scenario_step.params, "delete_entity"), None)
            elif scenario_step.kind == "wait":
                sleeper(float(scenario_step.params.get("seconds", 0.0)))
            elif scenario_step.kind == "log":
                result.skipped_count += 1
                continue
            elif scenario_step.kind in UNSUPPORTED_GAZEBO_SIMULATOR_STEP_KINDS:
                raise GazeboSimError(
                    f"Gazebo Sim simulator step is not supported yet: {scenario_step.kind}."
                )
            else:
                result.skipped_count += 1
                continue
            result.executed_count += 1
            status = "passed"
        except _GazeboServiceCommandError as exc:
            status = "failed"
            error_type = exc.error_type
            failure_reason = str(exc)
        except Exception as exc:
            status = "failed"
            error_type = type(exc).__name__
            failure_reason = str(exc)

        result.steps.append(
            StepRunResult(
                index=len(result.steps),
                kind=step_kind,
                status=status,
                duration_seconds=clock() - started,
                failure_reason=failure_reason,
                time_offset_seconds=(
                    max(0.0, started - scenario_started_at)
                    if scenario_started_at is not None
                    else None
                ),
            )
        )
        if failure_reason:
            result.error_type = error_type
            result.failure_reason = failure_reason
            break

    return result


class _GazeboServiceCommandError(RuntimeError):
    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type


def _run_gazebo_service_command(
    command_runner: CommandRunner,
    command: list[str],
    timeout: float,
    timeout_error: str,
    timeout_reason: str,
    failure_error: str,
    failure_prefix: str,
) -> None:
    try:
        completed = command_runner(command, timeout)
    except subprocess.TimeoutExpired as exc:
        raise _GazeboServiceCommandError(timeout_error, timeout_reason) from exc
    except Exception:
        raise

    if completed.returncode == 0:
        return

    reason = (
        _first_output_line(completed.stderr)
        or _first_output_line(completed.stdout)
        or f"{' '.join(command)} exited with code {completed.returncode}."
    )
    raise _GazeboServiceCommandError(failure_error, f"{failure_prefix}: {reason}")


def _scenario_world_name(scenario: Scenario) -> str:
    return _world_name_from_world_arg(gazebo_sim_command(scenario)[-1])


def _world_name_from_world_arg(world_arg: str) -> str:
    path = Path(world_arg)
    if path.exists():
        parsed_name = _parse_sdf_world_name(path)
        if parsed_name:
            return parsed_name
        return path.stem

    cleaned = world_arg.rstrip("/")
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[1]
    name = Path(cleaned).stem or Path(cleaned).name
    if not name:
        name = "default"
    return _safe_name(name)


def _parse_sdf_world_name(path: Path) -> str | None:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None

    if _strip_xml_namespace(root.tag) == "world":
        return root.attrib.get("name")
    for child in root:
        if _strip_xml_namespace(child.tag) == "world":
            return child.attrib.get("name")
    return None


def _strip_xml_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _required_name(params: dict, action: str) -> str:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise GazeboSimError(f"{action} requires a non-empty name.")
    return name


def _move_entity_waypoints(params: dict) -> list[dict]:
    if "trajectory" in params:
        raw_trajectory = params["trajectory"]
        if not isinstance(raw_trajectory, list) or not raw_trajectory:
            raise GazeboSimError("move_entity trajectory must be a non-empty list.")
        waypoints = []
        previous_at = 0.0
        for index, raw_waypoint in enumerate(raw_trajectory):
            if not isinstance(raw_waypoint, dict):
                raise GazeboSimError(f"move_entity trajectory waypoint {index} must be a mapping.")
            if "at" not in raw_waypoint:
                raise GazeboSimError(f"move_entity trajectory waypoint {index} is missing at.")
            if "pose" not in raw_waypoint:
                raise GazeboSimError(f"move_entity trajectory waypoint {index} is missing pose.")
            at = _float_value(raw_waypoint["at"], f"move_entity.trajectory[{index}].at")
            if at < 0:
                raise GazeboSimError(f"move_entity trajectory waypoint {index} at must be non-negative.")
            if at < previous_at:
                raise GazeboSimError("move_entity trajectory at values must be non-decreasing.")
            pose = raw_waypoint["pose"]
            if not isinstance(pose, dict):
                raise GazeboSimError(f"move_entity trajectory waypoint {index} pose must be a mapping.")
            waypoints.append({"at": at, "pose": pose})
            previous_at = at
        return waypoints

    pose = params.get("pose")
    if isinstance(pose, dict):
        return [{"at": 0.0, "pose": pose}]

    raise GazeboSimError("move_entity requires pose or trajectory.")


def _box_obstacle_sdf(name: str, params: dict) -> str:
    pose = params.get("pose") or {}
    if not isinstance(pose, dict):
        raise GazeboSimError("spawn_obstacle pose must be a mapping when provided.")
    size = params.get("size") or {}
    if not isinstance(size, dict):
        raise GazeboSimError("spawn_obstacle size must be a mapping when provided.")

    size_x = _positive_float(size.get("x", 1.0), "spawn_obstacle.size.x")
    size_y = _positive_float(size.get("y", 1.0), "spawn_obstacle.size.y")
    size_z = _positive_float(size.get("z", 1.0), "spawn_obstacle.size.z")
    x = _float_value(pose.get("x", 0.0), "spawn_obstacle.pose.x")
    y = _float_value(pose.get("y", 0.0), "spawn_obstacle.pose.y")
    yaw = _float_value(pose.get("yaw", 0.0), "spawn_obstacle.pose.yaw")
    z = size_z / 2.0

    sdf = ET.Element("sdf", {"version": "1.9"})
    model = ET.SubElement(sdf, "model", {"name": name})
    ET.SubElement(model, "static").text = "true"
    ET.SubElement(model, "pose").text = f"{x:g} {y:g} {z:g} 0 0 {yaw:g}"
    link = ET.SubElement(model, "link", {"name": "link"})
    collision = ET.SubElement(link, "collision", {"name": "collision"})
    collision_geometry = ET.SubElement(collision, "geometry")
    collision_box = ET.SubElement(collision_geometry, "box")
    ET.SubElement(collision_box, "size").text = f"{size_x:g} {size_y:g} {size_z:g}"
    visual = ET.SubElement(link, "visual", {"name": "visual"})
    visual_geometry = ET.SubElement(visual, "geometry")
    visual_box = ET.SubElement(visual_geometry, "box")
    ET.SubElement(visual_box, "size").text = f"{size_x:g} {size_y:g} {size_z:g}"
    return ET.tostring(sdf, encoding="unicode", short_empty_elements=False)


def _spawn_obstacle_default_z(params: dict) -> float:
    size = params.get("size") or {}
    if not isinstance(size, dict):
        return 0.5
    return _positive_float(size.get("z", 1.0), "spawn_obstacle.size.z") / 2.0


def _float_value(value: object, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise GazeboSimError(f"{field} must be numeric.") from exc


def _positive_float(value: object, field: str) -> float:
    number = _float_value(value, field)
    if number <= 0:
        raise GazeboSimError(f"{field} must be greater than 0.")
    return number


def _protobuf_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")
    return f'"{escaped}"'


def _navigation_data_topics(scenario: Scenario) -> list[str]:
    robot = scenario.document.get("robot") or {}
    configured_topics = {}
    if isinstance(robot, dict) and isinstance(robot.get("topics"), dict):
        configured_topics = robot["topics"]

    namespace = _scenario_namespace(scenario)
    topics = [
        _configured_topic(configured_topics, "tf", "/tf", namespace, apply_namespace_to_default=False),
        _configured_topic(configured_topics, "map", "map", namespace),
        _configured_topic(configured_topics, "global_costmap", "global_costmap/costmap", namespace),
        _configured_topic(configured_topics, "local_costmap", "local_costmap/costmap", namespace),
    ]
    return _dedupe(topics)


def _configured_topic(
    configured_topics: dict,
    key: str,
    default: str,
    namespace: str,
    apply_namespace_to_default: bool = True,
) -> str:
    value = configured_topics.get(key, default)
    topic = str(value)
    if topic.startswith("/"):
        return topic
    if value == default and not apply_namespace_to_default:
        return "/" + topic.strip("/")
    return _namespace_topic(namespace, topic)


def _namespace_topic(namespace: str, topic: str) -> str:
    topic = topic.strip("/")
    if namespace:
        return f"{namespace}/{topic}"
    return f"/{topic}"


def _scenario_namespace(scenario: Scenario) -> str:
    runtime = scenario.document.get("runtime") or {}
    isolation = runtime.get("isolation") if isinstance(runtime, dict) else {}
    namespace = isolation.get("namespace", "") if isinstance(isolation, dict) else ""
    namespace = str(namespace).strip()
    if not namespace or namespace == "/":
        return ""
    return "/" + namespace.strip("/")


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _first_output_line(value: str | None) -> str:
    if not value:
        return ""
    for line in value.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _resolve_world_arg(scenario: Scenario, world: str) -> str:
    if _looks_like_resource_uri(world):
        return world
    path = Path(world)
    if path.is_absolute():
        if not path.exists():
            raise GazeboSimError(f"Gazebo Sim world file does not exist: {path}")
        return str(path)
    candidate = scenario.path.parent / path
    if candidate.exists():
        return str(candidate)
    if _looks_like_local_path(world):
        raise GazeboSimError(
            f"Gazebo Sim world file does not exist: {candidate} "
            f"(from simulator.world: {world})"
        )
    return world


def _artifact_dir(report_dir: Path, scenario: Scenario) -> Path:
    return report_dir / "artifacts" / _safe_name(scenario.scenario_id)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "scenario"


def _metric_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "process"


def _looks_like_local_path(value: str) -> bool:
    suffix = Path(value).suffix.lower()
    return "/" in value or "\\" in value or suffix in {".sdf", ".world"}


def _looks_like_resource_uri(value: str) -> bool:
    return "://" in value


def _write_log_header(log: TextIO, command: list[str]) -> None:
    log.write("nav2_scenario_runner Gazebo Sim lifecycle log\n")
    log.write(f"command: {' '.join(command)}\n")
    log.write("\n")
    log.flush()


def _copy_scenario_file(scenario: Scenario, path: Path) -> None:
    try:
        shutil.copyfile(scenario.path, path)
    except OSError:
        path.write_text(json.dumps(scenario.document, indent=2) + "\n", encoding="utf-8")


def _write_metadata(metadata: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def _stop_process(process: ProcessLike) -> int | None:
    if process.poll() is not None:
        return process.poll()
    process.terminate()
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait(timeout=5)
