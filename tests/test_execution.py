from __future__ import annotations

from pathlib import Path

from nav2_scenario_runner.backends.fake import FakeNav2Backend
from nav2_scenario_runner.execution import ExecutionEngine
from nav2_scenario_runner.runner import run_with_backend_factory
from nav2_scenario_runner.scenario import Scenario, load_scenario


def test_execution_engine_runs_supported_nav2_steps():
    loaded = load_scenario(Path("examples/turtlebot3_gazebo/smoke.yaml"))
    assert loaded.scenario is not None
    backend = FakeNav2Backend()

    result = ExecutionEngine(backend).run(loaded.scenario)

    assert result.status == "passed"
    assert [step.kind for step in result.steps or []] == [
        "wait_for_nav2_active",
        "set_initial_pose",
        "send_goal",
        "expect_goal_reached",
    ]
    assert backend.operations == [
        "wait_for_nav2_active:30",
        "set_initial_pose:0,0,0",
        "send_goal:main_goal:10,0,0",
        "reset_path_length_traveled",
        "reset_replanning_count",
        "reset_recovery_count",
        "reset_collision_count",
        "expect_goal_reached:main_goal:60",
        "get_path_length_traveled",
        "get_replanning_count",
        "get_recovery_count",
        "get_collision_count",
        "close",
    ]
    assert result.assertions is not None
    assert [assertion.kind for assertion in result.assertions] == [
        "collision_free",
        "path_length",
        "travel_time",
        "recovery_count",
    ]
    assert [assertion.status for assertion in result.assertions] == [
        "passed",
        "passed",
        "passed",
        "passed",
    ]


def test_execution_engine_records_travel_time_metric():
    loaded = load_scenario(Path("examples/turtlebot3_gazebo/smoke.yaml"))
    assert loaded.scenario is not None

    result = ExecutionEngine(FakeNav2Backend(), clock=IncrementingClock()).run(loaded.scenario)

    assert result.status == "passed"
    assert result.metrics is not None
    assert result.metrics["goal_reached"] is True
    assert result.metrics["travel_time"] == 3.0
    assert result.metrics["travel_time.main_goal"] == 3.0
    assert result.metrics["path_length_traveled"] == 10.0
    assert result.metrics["path_length_traveled.main_goal"] == 10.0
    assert result.metrics["replanning_count"] == 1
    assert result.metrics["replanning_count.main_goal"] == 1
    assert result.metrics["recovery_count"] == 0
    assert result.metrics["recovery_count.main_goal"] == 0
    assert result.metrics["collision_count"] == 0
    assert result.metrics["collision_count.main_goal"] == 0
    assert result.metrics["collision_free"] is True


def test_execution_engine_runs_wait_step():
    scenario = Scenario(
        path=Path("wait.yaml"),
        document={
            "apiVersion": "nav2.scenario/v1alpha1",
            "kind": "Scenario",
            "metadata": {"name": "wait"},
            "steps": [{"wait": {"seconds": 0.0}}],
        },
        scenario_id="wait",
        name="wait",
        tags=set(),
        step_count=1,
        assertion_count=0,
    )

    result = ExecutionEngine(FakeNav2Backend()).run(scenario)

    assert result.status == "passed"
    assert result.steps is not None
    assert result.steps[0].kind == "wait"
    assert result.steps[0].status == "passed"


def test_execution_engine_rejects_negative_wait_step():
    scenario = Scenario(
        path=Path("negative_wait.yaml"),
        document={
            "apiVersion": "nav2.scenario/v1alpha1",
            "kind": "Scenario",
            "metadata": {"name": "negative_wait"},
            "steps": [{"wait": {"seconds": -1.0}}],
        },
        scenario_id="negative_wait",
        name="negative_wait",
        tags=set(),
        step_count=1,
        assertion_count=0,
    )

    result = ExecutionEngine(FakeNav2Backend()).run(scenario)

    assert result.status == "failed"
    assert result.failure_reason == "wait.seconds must be non-negative."


def test_execution_engine_fails_when_supported_assertion_fails():
    scenario = Scenario(
        path=Path("slow.yaml"),
        document={
            "apiVersion": "nav2.scenario/v1alpha1",
            "kind": "Scenario",
            "metadata": {"name": "slow"},
            "steps": [
                {"send_goal": {"name": "main_goal", "pose": {"x": 1.0, "y": 0.0, "yaw": 0.0}}},
                {"expect_goal_reached": {"goal": "main_goal", "timeout": 60.0}},
            ],
            "assertions": [{"travel_time": {"max": 1.0}}],
        },
        scenario_id="slow",
        name="slow",
        tags=set(),
        step_count=2,
        assertion_count=1,
    )

    result = ExecutionEngine(FakeNav2Backend(), clock=IncrementingClock()).run(scenario)

    assert result.status == "failed"
    assert result.failure_reason == "travel_time=3 exceeds max 1."
    assert result.assertions is not None
    assert result.assertions[0].status == "failed"


def test_execution_engine_fails_when_path_length_assertion_fails():
    scenario = Scenario(
        path=Path("long_path.yaml"),
        document={
            "apiVersion": "nav2.scenario/v1alpha1",
            "kind": "Scenario",
            "metadata": {"name": "long_path"},
            "steps": [
                {"set_initial_pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}},
                {"send_goal": {"name": "main_goal", "pose": {"x": 10.0, "y": 0.0, "yaw": 0.0}}},
                {"expect_goal_reached": {"goal": "main_goal", "timeout": 60.0}},
            ],
            "assertions": [{"path_length": {"max": 5.0}}],
        },
        scenario_id="long_path",
        name="long_path",
        tags=set(),
        step_count=3,
        assertion_count=1,
    )

    result = ExecutionEngine(FakeNav2Backend()).run(scenario)

    assert result.status == "failed"
    assert result.failure_reason == "path_length_traveled=10 exceeds max 5."
    assert result.metrics is not None
    assert result.metrics["path_length_traveled"] == 10.0


def test_execution_engine_fails_when_replanning_count_assertion_fails():
    scenario = Scenario(
        path=Path("replan.yaml"),
        document={
            "apiVersion": "nav2.scenario/v1alpha1",
            "kind": "Scenario",
            "metadata": {"name": "replan"},
            "steps": [
                {"set_initial_pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}},
                {"send_goal": {"name": "main_goal", "pose": {"x": 1.0, "y": 0.0, "yaw": 0.0}}},
                {"expect_goal_reached": {"goal": "main_goal", "timeout": 60.0}},
            ],
            "assertions": [{"replanning_count": {"max": 0}}],
        },
        scenario_id="replan",
        name="replan",
        tags=set(),
        step_count=3,
        assertion_count=1,
    )

    result = ExecutionEngine(FakeNav2Backend()).run(scenario)

    assert result.status == "failed"
    assert result.failure_reason == "replanning_count=1 exceeds max 0."
    assert result.metrics is not None
    assert result.metrics["replanning_count"] == 1


def test_execution_engine_fails_when_recovery_count_assertion_fails():
    scenario = Scenario(
        path=Path("recovery.yaml"),
        document={
            "apiVersion": "nav2.scenario/v1alpha1",
            "kind": "Scenario",
            "metadata": {"name": "recovery"},
            "steps": [
                {"set_initial_pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}},
                {"send_goal": {"name": "main_goal", "pose": {"x": 1.0, "y": 0.0, "yaw": 0.0}}},
                {"expect_goal_reached": {"goal": "main_goal", "timeout": 60.0}},
            ],
            "assertions": [{"recovery_count": {"max": 1}}],
        },
        scenario_id="recovery",
        name="recovery",
        tags=set(),
        step_count=3,
        assertion_count=1,
    )

    result = ExecutionEngine(FakeNav2Backend(simulated_recovery_count=2)).run(scenario)

    assert result.status == "failed"
    assert result.failure_reason == "recovery_count=2 exceeds max 1."
    assert result.metrics is not None
    assert result.metrics["recovery_count"] == 2


def test_execution_engine_fails_when_collision_free_assertion_fails():
    scenario = Scenario(
        path=Path("collision.yaml"),
        document={
            "apiVersion": "nav2.scenario/v1alpha1",
            "kind": "Scenario",
            "metadata": {"name": "collision"},
            "steps": [
                {"set_initial_pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}},
                {"send_goal": {"name": "main_goal", "pose": {"x": 1.0, "y": 0.0, "yaw": 0.0}}},
                {"expect_goal_reached": {"goal": "main_goal", "timeout": 60.0}},
            ],
            "assertions": [{"collision_free": {}}],
        },
        scenario_id="collision",
        name="collision",
        tags=set(),
        step_count=3,
        assertion_count=1,
    )

    result = ExecutionEngine(FakeNav2Backend(simulated_collision_count=1)).run(scenario)

    assert result.status == "failed"
    assert result.failure_reason == "Collision detected; collision_count=1."
    assert result.metrics is not None
    assert result.metrics["collision_free"] is False
    assert result.metrics["collision_count"] == 1


def test_execution_engine_fails_unknown_step():
    scenario = Scenario(
        path=Path("unknown.yaml"),
        document={
            "apiVersion": "nav2.scenario/v1alpha1",
            "kind": "Scenario",
            "metadata": {"name": "unknown_step"},
            "steps": [{"custom_plugin_step": {}}],
        },
        scenario_id="unknown_step",
        name="unknown_step",
        tags=set(),
        step_count=1,
        assertion_count=0,
    )

    result = ExecutionEngine(FakeNav2Backend()).run(scenario)

    assert result.status == "failed"
    assert result.failure_reason == "Unsupported executable step: custom_plugin_step"
    assert result.steps is not None
    assert result.steps[0].status == "failed"


def test_run_with_backend_factory_summarizes_failures():
    loaded = load_scenario(Path("examples/turtlebot3_gazebo/smoke.yaml"))
    assert loaded.scenario is not None

    report = run_with_backend_factory(
        [loaded.scenario],
        mode="fake",
        backend_factory=lambda _scenario: FakeNav2Backend(),
    )

    assert report.mode == "fake"
    assert report.total == 1
    assert report.passed == 1
    assert report.failed == 0


def test_execution_engine_reports_step_parse_failure():
    scenario = Scenario(
        path=Path("bad_step.yaml"),
        document={
            "apiVersion": "nav2.scenario/v1alpha1",
            "kind": "Scenario",
            "metadata": {"name": "bad_step"},
            "steps": ["not-a-step-mapping"],
        },
        scenario_id="bad_step",
        name="bad_step",
        tags=set(),
        step_count=1,
        assertion_count=0,
    )

    result = ExecutionEngine(FakeNav2Backend()).run(scenario)

    assert result.status == "failed"
    assert result.failure_reason == "Step 0 must contain exactly one action."
    assert result.steps == []
    assert result.assertions == []


class IncrementingClock:
    def __init__(self):
        self.value = -1.0

    def __call__(self) -> float:
        self.value += 1.0
        return self.value
