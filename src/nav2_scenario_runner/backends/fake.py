from __future__ import annotations

import math
from dataclasses import dataclass, field

from nav2_scenario_runner.execution import Pose2D, StepExecutionError


@dataclass
class FakeNav2Backend:
    operations: list[str] = field(default_factory=list)
    accepted_goals: set[str] = field(default_factory=set)
    current_pose: Pose2D | None = None
    goal_poses: dict[str, Pose2D] = field(default_factory=dict)
    path_length_traveled: float = 0.0
    replanning_count: int = 0
    recovery_count: int = 0
    collision_count: int = 0
    trajectory_points: list[dict[str, float]] = field(default_factory=list)
    simulated_recovery_count: int = 0
    simulated_collision_count: int = 0

    def wait_for_nav2_active(self, timeout: float) -> None:
        self.operations.append(f"wait_for_nav2_active:{timeout:g}")

    def set_initial_pose(self, pose: Pose2D) -> None:
        self.current_pose = pose
        self.operations.append(f"set_initial_pose:{pose.x:g},{pose.y:g},{pose.yaw:g}")

    def send_goal(self, name: str, pose: Pose2D, behavior_tree: str | None = None) -> None:
        self.accepted_goals.add(name)
        self.goal_poses[name] = pose
        suffix = f":{behavior_tree}" if behavior_tree else ""
        self.operations.append(f"send_goal:{name}:{pose.x:g},{pose.y:g},{pose.yaw:g}{suffix}")

    def reset_path_length_traveled(self) -> None:
        self.path_length_traveled = 0.0
        self.operations.append("reset_path_length_traveled")

    def reset_replanning_count(self) -> None:
        self.replanning_count = 0
        self.operations.append("reset_replanning_count")

    def reset_recovery_count(self) -> None:
        self.recovery_count = 0
        self.operations.append("reset_recovery_count")

    def reset_collision_count(self) -> None:
        self.collision_count = 0
        self.operations.append("reset_collision_count")

    def expect_goal_reached(self, goal_name: str, timeout: float) -> None:
        self.operations.append(f"expect_goal_reached:{goal_name}:{timeout:g}")
        if goal_name not in self.accepted_goals:
            raise StepExecutionError(f"Goal was not sent before expectation: {goal_name}")
        self.replanning_count = max(self.replanning_count, 1)
        self.recovery_count = self.simulated_recovery_count
        self.collision_count = self.simulated_collision_count
        goal_pose = self.goal_poses.get(goal_name)
        if self.current_pose and goal_pose:
            start_pose = self.current_pose
            self.path_length_traveled = math.hypot(
                goal_pose.x - start_pose.x,
                goal_pose.y - start_pose.y,
            )
            self.trajectory_points = [
                {"x": start_pose.x, "y": start_pose.y},
                {"x": goal_pose.x, "y": goal_pose.y},
            ]
            self.current_pose = goal_pose

    def get_path_length_traveled(self) -> float | None:
        self.operations.append("get_path_length_traveled")
        return self.path_length_traveled

    def get_replanning_count(self) -> int | None:
        self.operations.append("get_replanning_count")
        return self.replanning_count

    def get_recovery_count(self) -> int | None:
        self.operations.append("get_recovery_count")
        return self.recovery_count

    def get_collision_count(self) -> int | None:
        self.operations.append("get_collision_count")
        return self.collision_count

    def get_trajectory_points(self) -> list[dict[str, float]] | None:
        self.operations.append("get_trajectory_points")
        return self.trajectory_points

    def close(self) -> None:
        self.operations.append("close")
