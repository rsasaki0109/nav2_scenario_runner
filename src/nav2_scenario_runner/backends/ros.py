from __future__ import annotations

import math
import time
from typing import Any

from nav2_scenario_runner.execution import BackendUnavailable, Pose2D, StepExecutionError
from nav2_scenario_runner.scenario import Scenario


class RosAttachBackend:
    def __init__(self, namespace: str = ""):
        try:
            import rclpy
            from action_msgs.msg import GoalStatus
            from geometry_msgs.msg import PoseWithCovarianceStamped
            from nav2_msgs.action import NavigateToPose
            from nav_msgs.msg import Odometry, Path as PathMsg
            from rclpy.action import ActionClient
        except ImportError as exc:
            raise BackendUnavailable(
                "ROS attach backend requires rclpy, action_msgs, geometry_msgs, "
                "nav2_msgs, nav_msgs, and a sourced ROS 2/Nav2 environment."
            ) from exc

        self._rclpy = rclpy
        self._GoalStatus = GoalStatus
        self._Odometry = Odometry
        self._PathMsg = PathMsg
        self._PoseWithCovarianceStamped = PoseWithCovarianceStamped
        self._NavigateToPose = NavigateToPose
        self._ActionClient = ActionClient
        self._namespace = _normalize_namespace(namespace)
        self._last_odom_xy: tuple[float, float] | None = None
        self._path_length_traveled: float = 0.0
        self._trajectory_points: list[dict[str, float]] = []
        self._replanning_count: int = 0
        self._received_odom = False
        self._owns_context = not rclpy.ok()
        if self._owns_context:
            rclpy.init()
        self._node = rclpy.create_node("nav2_scenario_runner")
        self._initial_pose_pub = self._node.create_publisher(
            PoseWithCovarianceStamped,
            self._topic("initialpose"),
            10,
        )
        self._navigate_client = ActionClient(
            self._node,
            NavigateToPose,
            self._topic("navigate_to_pose"),
        )
        self._odom_sub = self._node.create_subscription(
            Odometry,
            self._topic("odom"),
            self._odom_callback,
            50,
        )
        self._plan_sub = self._node.create_subscription(
            PathMsg,
            self._topic("plan"),
            self._plan_callback,
            50,
        )
        self._goal_results: dict[str, Any] = {}

    @classmethod
    def from_scenario(cls, scenario: Scenario) -> "RosAttachBackend":
        runtime = scenario.document.get("runtime") or {}
        isolation = runtime.get("isolation") or {}
        namespace = isolation.get("namespace", "")
        return cls(namespace=namespace)

    def wait_for_nav2_active(self, timeout: float) -> None:
        if not self._navigate_client.wait_for_server(timeout_sec=timeout):
            raise StepExecutionError(
                f"Nav2 NavigateToPose action server not available after {timeout:g}s"
            )

    def set_initial_pose(self, pose: Pose2D) -> None:
        msg = self._PoseWithCovarianceStamped()
        msg.header.frame_id = pose.frame
        msg.pose.pose.position.x = pose.x
        msg.pose.pose.position.y = pose.y
        msg.pose.pose.orientation.z = math.sin(pose.yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(pose.yaw / 2.0)
        msg.pose.covariance[0] = 0.25
        msg.pose.covariance[7] = 0.25
        msg.pose.covariance[35] = 0.06853891945200942
        for _ in range(8):
            msg.header.stamp = self._node.get_clock().now().to_msg()
            self._initial_pose_pub.publish(msg)
            self._spin_for(0.2)

    def send_goal(self, name: str, pose: Pose2D, behavior_tree: str | None = None) -> None:
        goal_msg = self._NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = pose.frame
        goal_msg.pose.header.stamp = self._node.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = pose.x
        goal_msg.pose.pose.position.y = pose.y
        goal_msg.pose.pose.orientation.z = math.sin(pose.yaw / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(pose.yaw / 2.0)
        if behavior_tree:
            goal_msg.behavior_tree = behavior_tree

        send_future = self._navigate_client.send_goal_async(goal_msg)
        self._rclpy.spin_until_future_complete(self._node, send_future)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            raise StepExecutionError(f"Nav2 goal was rejected: {name}")
        self._goal_results[name] = goal_handle.get_result_async()

    def reset_path_length_traveled(self) -> None:
        self._path_length_traveled = 0.0
        self._last_odom_xy = None
        self._trajectory_points = []
        self._spin_for(0.05)

    def reset_replanning_count(self) -> None:
        self._replanning_count = 0
        self._spin_for(0.01)

    def reset_recovery_count(self) -> None:
        # No reliable default collector is implemented yet for Nav2 recovery behavior events.
        return

    def reset_collision_count(self) -> None:
        # Collision events require a simulator/contact source; attach mode has no default collector yet.
        return

    def expect_goal_reached(self, goal_name: str, timeout: float) -> None:
        result_future = self._goal_results.get(goal_name)
        if result_future is None:
            raise StepExecutionError(f"Goal was not sent before expectation: {goal_name}")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._rclpy.spin_once(self._node, timeout_sec=0.1)
            if result_future.done():
                result = result_future.result()
                if result.status != self._GoalStatus.STATUS_SUCCEEDED:
                    raise StepExecutionError(
                        f"Nav2 goal did not succeed: {goal_name} status={result.status}"
                    )
                return

        raise StepExecutionError(f"Timed out waiting for Nav2 goal: {goal_name}")

    def get_path_length_traveled(self) -> float | None:
        if not self._received_odom:
            return None
        return self._path_length_traveled

    def get_replanning_count(self) -> int | None:
        return self._replanning_count

    def get_recovery_count(self) -> int | None:
        return None

    def get_collision_count(self) -> int | None:
        return None

    def get_trajectory_points(self) -> list[dict[str, float]] | None:
        if len(self._trajectory_points) < 2:
            return None
        return list(self._trajectory_points)

    def close(self) -> None:
        self._navigate_client.destroy()
        self._node.destroy_subscription(self._odom_sub)
        self._node.destroy_subscription(self._plan_sub)
        self._node.destroy_node()
        if self._owns_context:
            self._rclpy.shutdown()

    def _topic(self, topic: str) -> str:
        if not self._namespace:
            return f"/{topic}"
        return f"{self._namespace}/{topic}"

    def _spin_for(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._rclpy.spin_once(self._node, timeout_sec=0.01)

    def _odom_callback(self, msg: Any) -> None:
        self._received_odom = True
        x = float(msg.pose.pose.position.x)
        y = float(msg.pose.pose.position.y)
        if self._last_odom_xy is not None:
            previous_x, previous_y = self._last_odom_xy
            delta = math.hypot(x - previous_x, y - previous_y)
            self._path_length_traveled += delta
            last_sample = self._trajectory_points[-1] if self._trajectory_points else None
            if last_sample is None or math.hypot(x - last_sample["x"], y - last_sample["y"]) >= 0.02:
                self._trajectory_points.append({"x": x, "y": y})
        else:
            self._trajectory_points.append({"x": x, "y": y})
        self._last_odom_xy = (x, y)

    def _plan_callback(self, _msg: Any) -> None:
        self._replanning_count += 1


def _normalize_namespace(namespace: str) -> str:
    namespace = namespace.strip()
    if not namespace or namespace == "/":
        return ""
    return "/" + namespace.strip("/")
