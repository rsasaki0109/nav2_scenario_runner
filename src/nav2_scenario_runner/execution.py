from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol, Union

from .assertions import assertion_results_passed, evaluate_assertions, first_failed_assertion
from .runner import ScenarioRunResult, StepRunResult
from .scenario import Scenario


class BackendUnavailable(RuntimeError):
    """Raised when a requested execution backend cannot be constructed."""


class StepExecutionError(RuntimeError):
    """Raised when a scenario step cannot be executed successfully."""


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    yaw: float
    frame: str = "map"


@dataclass(frozen=True)
class ScenarioStep:
    index: int
    kind: str
    params: dict


class Nav2ExecutionBackend(Protocol):
    def wait_for_nav2_active(self, timeout: float) -> None:
        ...

    def set_initial_pose(self, pose: Pose2D) -> None:
        ...

    def send_goal(self, name: str, pose: Pose2D, behavior_tree: str | None = None) -> None:
        ...

    def reset_path_length_traveled(self) -> None:
        ...

    def reset_replanning_count(self) -> None:
        ...

    def reset_recovery_count(self) -> None:
        ...

    def reset_collision_count(self) -> None:
        ...

    def expect_goal_reached(self, goal_name: str, timeout: float) -> None:
        ...

    def get_path_length_traveled(self) -> float | None:
        ...

    def get_replanning_count(self) -> int | None:
        ...

    def get_recovery_count(self) -> int | None:
        ...

    def get_collision_count(self) -> int | None:
        ...

    def close(self) -> None:
        ...


class ExecutionEngine:
    def __init__(self, backend: Nav2ExecutionBackend, clock: Callable[[], float] = time.monotonic):
        self._backend = backend
        self._clock = clock
        self._run_started_at = 0.0
        self._goal_started_at: dict[str, float] = {}
        self._metrics: dict[str, Union[int, float, str, bool]] = {}

    def run(self, scenario: Scenario) -> ScenarioRunResult:
        started = self._clock()
        step_results: list[StepRunResult] = []
        assertion_results = []
        status = "passed"
        failure_reason: str | None = None
        self._goal_started_at = {}
        self._metrics = {}
        self._run_started_at = started

        try:
            steps = parse_steps(scenario)
            for step in steps:
                step_result = self._run_step(step)
                step_results.append(step_result)
                if step_result.status != "passed":
                    status = "failed"
                    failure_reason = step_result.failure_reason
                    break
        except Exception as exc:
            status = "failed"
            failure_reason = str(exc)
        finally:
            self._backend.close()

        duration = self._clock() - started
        if status == "passed":
            assertion_results = evaluate_assertions(
                scenario,
                metrics=self._metrics,
                duration_seconds=duration,
            )
            if not assertion_results_passed(assertion_results):
                status = "failed"
                failed_assertion = first_failed_assertion(assertion_results)
                failure_reason = failed_assertion.message if failed_assertion else "Assertion failed."

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
            steps=step_results,
            assertions=assertion_results,
            metrics=self._metrics.copy(),
        )

    def _run_step(self, step: ScenarioStep) -> StepRunResult:
        started = self._clock()
        time_offset = max(0.0, started - self._run_started_at)
        failure_reason: str | None = None
        status = "passed"

        try:
            self._dispatch(step)
        except Exception as exc:
            status = "failed"
            failure_reason = str(exc)

        return StepRunResult(
            index=step.index,
            kind=step.kind,
            status=status,
            duration_seconds=self._clock() - started,
            failure_reason=failure_reason,
            time_offset_seconds=time_offset,
        )

    def _dispatch(self, step: ScenarioStep) -> None:
        if step.kind == "wait_for_nav2_active":
            timeout = float(step.params.get("timeout", 30.0))
            self._backend.wait_for_nav2_active(timeout=timeout)
            return

        if step.kind == "set_initial_pose":
            self._backend.set_initial_pose(_pose_from_mapping(step.params))
            return

        if step.kind == "send_goal":
            pose_data = step.params.get("pose", step.params)
            pose = _pose_from_mapping(pose_data)
            name = str(step.params.get("name", "goal"))
            behavior_tree = step.params.get("behavior_tree")
            self._backend.send_goal(name=name, pose=pose, behavior_tree=behavior_tree)
            self._backend.reset_path_length_traveled()
            self._backend.reset_replanning_count()
            self._backend.reset_recovery_count()
            self._backend.reset_collision_count()
            self._goal_started_at[name] = self._clock()
            return

        if step.kind == "expect_goal_reached":
            goal_name = str(step.params.get("goal", "goal"))
            timeout = float(step.params.get("timeout", 60.0))
            self._backend.expect_goal_reached(goal_name=goal_name, timeout=timeout)
            self._record_goal_reached_metrics(goal_name)
            return

        raise StepExecutionError(f"Unsupported executable step: {step.kind}")

    def _record_goal_reached_metrics(self, goal_name: str) -> None:
        started = self._goal_started_at.get(goal_name)
        if started is None:
            raise StepExecutionError(f"Goal was not sent before expectation: {goal_name}")
        travel_time = self._clock() - started
        self._metrics["travel_time"] = travel_time
        self._metrics[f"travel_time.{goal_name}"] = travel_time
        self._metrics["goal_reached"] = True
        path_length_traveled = self._backend.get_path_length_traveled()
        if path_length_traveled is not None:
            self._metrics["path_length_traveled"] = path_length_traveled
            self._metrics[f"path_length_traveled.{goal_name}"] = path_length_traveled
        replanning_count = self._backend.get_replanning_count()
        if replanning_count is not None:
            self._metrics["replanning_count"] = replanning_count
            self._metrics[f"replanning_count.{goal_name}"] = replanning_count
        recovery_count = self._backend.get_recovery_count()
        if recovery_count is not None:
            self._metrics["recovery_count"] = recovery_count
            self._metrics[f"recovery_count.{goal_name}"] = recovery_count
        collision_count = self._backend.get_collision_count()
        if collision_count is not None:
            self._metrics["collision_count"] = collision_count
            self._metrics[f"collision_count.{goal_name}"] = collision_count
            self._metrics["collision_free"] = collision_count == 0


def parse_steps(scenario: Scenario) -> list[ScenarioStep]:
    steps = scenario.document.get("steps") or []
    if not isinstance(steps, list):
        raise StepExecutionError("Scenario steps must be a list.")

    parsed: list[ScenarioStep] = []
    for index, raw_step in enumerate(steps):
        if not isinstance(raw_step, dict) or len(raw_step) != 1:
            raise StepExecutionError(f"Step {index} must contain exactly one action.")
        kind, params = next(iter(raw_step.items()))
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise StepExecutionError(f"Step {index} parameters for {kind} must be a mapping.")
        parsed.append(ScenarioStep(index=index, kind=str(kind), params=params))

    return parsed


def _pose_from_mapping(data: dict) -> Pose2D:
    try:
        return Pose2D(
            x=float(data["x"]),
            y=float(data["y"]),
            yaw=float(data["yaw"]),
            frame=str(data.get("frame", "map")),
        )
    except KeyError as exc:
        raise StepExecutionError(f"Pose is missing required field: {exc.args[0]}") from exc
    except (TypeError, ValueError) as exc:
        raise StepExecutionError(f"Pose values must be numeric: {exc}") from exc
