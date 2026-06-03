from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree

from .runner import RunReport


def write_json_report(report: RunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")


def write_trace_report(report: RunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_trace_report(report), indent=2) + "\n", encoding="utf-8")


def build_trace_report(report: RunReport) -> dict:
    return {
        "schema": "nav2_scenario_runner.trace/v1alpha1",
        "runner_version": report.runner_version,
        "generated_at": report.generated_at,
        "mode": report.mode,
        "scenarios": [_trace_scenario(scenario) for scenario in report.scenarios],
    }


def write_junit_report(report: RunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    testsuites = ElementTree.Element(
        "testsuites",
        {
            "name": "nav2_scenario_runner",
            "tests": str(report.total),
            "failures": str(report.failed),
            "errors": "0",
            "skipped": "0",
            "time": _format_seconds(sum(scenario.duration_seconds for scenario in report.scenarios)),
        },
    )
    testsuite = ElementTree.SubElement(
        testsuites,
        "testsuite",
        {
            "name": f"nav2_scenario_runner.{report.mode}",
            "tests": str(report.total),
            "failures": str(report.failed),
            "errors": "0",
            "skipped": "0",
            "time": _format_seconds(sum(scenario.duration_seconds for scenario in report.scenarios)),
        },
    )

    for scenario in report.scenarios:
        testcase = ElementTree.SubElement(
            testsuite,
            "testcase",
            {
                "classname": scenario.path,
                "name": scenario.name,
                "time": _format_seconds(scenario.duration_seconds),
            },
        )

        if scenario.status not in {"passed", "dry_run_passed"}:
            failure = ElementTree.SubElement(
                testcase,
                "failure",
                {
                    "message": scenario.failure_reason or scenario.status,
                    "type": scenario.status,
                },
            )
            failure.text = _failure_text(scenario)

        system_out_lines = []
        if scenario.steps:
            system_out_lines.extend(
                f"step {step.index}: {step.kind} {step.status} {_format_seconds(step.duration_seconds)}s"
                for step in scenario.steps
            )
        if scenario.assertions:
            system_out_lines.extend(
                f"assertion {assertion.index}: {assertion.kind} {assertion.status} {assertion.message}"
                for assertion in scenario.assertions
            )
        if system_out_lines:
            system_out = ElementTree.SubElement(testcase, "system-out")
            system_out.text = "\n".join(system_out_lines)

    ElementTree.indent(testsuites)
    ElementTree.ElementTree(testsuites).write(path, encoding="utf-8", xml_declaration=True)


def _failure_text(scenario) -> str:
    lines = [f"scenario: {scenario.name}", f"status: {scenario.status}"]
    if scenario.failure_reason:
        lines.append(f"reason: {scenario.failure_reason}")
    if scenario.steps:
        lines.append("steps:")
        lines.extend(
            f"  {step.index}: {step.kind} {step.status}"
            + (f" reason={step.failure_reason}" if step.failure_reason else "")
            for step in scenario.steps
        )
    if scenario.assertions:
        lines.append("assertions:")
        lines.extend(
            f"  {assertion.index}: {assertion.kind} {assertion.status} {assertion.message}"
            for assertion in scenario.assertions
        )
    return "\n".join(lines)


def _format_seconds(value: float) -> str:
    return f"{value:.6f}"


def _trace_scenario(scenario) -> dict:
    events = [
        _trace_event(
            offset=0.0,
            event_type="scenario.started",
            scenario=scenario,
            data={"status": scenario.status},
        )
    ]

    offset = 0.0
    for step in scenario.steps or []:
        step_start_offset = _step_start_offset(step, fallback=offset)
        events.append(
            _trace_event(
                offset=step_start_offset,
                event_type="step.started",
                scenario=scenario,
                data={"index": step.index, "kind": step.kind},
            )
        )
        step_finish_offset = step_start_offset + max(0.0, float(step.duration_seconds))
        offset = max(offset, step_finish_offset)
        step_data = {
            "index": step.index,
            "kind": step.kind,
            "status": step.status,
            "duration_seconds": _round_seconds(step.duration_seconds),
        }
        if step.failure_reason:
            step_data["failure_reason"] = step.failure_reason
        events.append(
            _trace_event(
                offset=step_finish_offset,
                event_type="step.finished",
                scenario=scenario,
                data=step_data,
            )
        )

    evaluation_offset = max(offset, float(scenario.duration_seconds))
    for assertion in scenario.assertions or []:
        assertion_data = {
            "index": assertion.index,
            "kind": assertion.kind,
            "status": assertion.status,
            "severity": assertion.severity,
            "message": assertion.message,
        }
        if assertion.metric:
            assertion_data["metric"] = assertion.metric
        if assertion.actual is not None:
            assertion_data["actual"] = assertion.actual
        if assertion.expected is not None:
            assertion_data["expected"] = assertion.expected
        events.append(
            _trace_event(
                offset=evaluation_offset,
                event_type="assertion.evaluated",
                scenario=scenario,
                data=assertion_data,
            )
        )

    for name, value in sorted((scenario.metrics or {}).items()):
        events.append(
            _trace_event(
                offset=evaluation_offset,
                event_type="metric.recorded",
                scenario=scenario,
                data={"name": name, "value": value},
            )
        )

    final_offset = max(evaluation_offset, float(scenario.duration_seconds))
    finish_data = {
        "status": scenario.status,
        "duration_seconds": _round_seconds(scenario.duration_seconds),
    }
    if scenario.failure_reason:
        finish_data["failure_reason"] = scenario.failure_reason
    events.append(
        _trace_event(
            offset=final_offset,
            event_type="scenario.finished",
            scenario=scenario,
            data=finish_data,
        )
    )

    return {
        "scenario_id": scenario.scenario_id,
        "name": scenario.name,
        "path": scenario.path,
        "status": scenario.status,
        "duration_seconds": _round_seconds(scenario.duration_seconds),
        "events": _sort_trace_events(events),
    }


def _trace_event(offset: float, event_type: str, scenario, data: dict) -> dict:
    return {
        "time_offset_seconds": _round_seconds(offset),
        "type": event_type,
        "scenario_id": scenario.scenario_id,
        "data": data,
    }


def _step_start_offset(step, fallback: float) -> float:
    explicit = getattr(step, "time_offset_seconds", None)
    if explicit is None:
        return fallback
    return max(0.0, float(explicit))


def _sort_trace_events(events: list[dict]) -> list[dict]:
    return [
        event
        for _, event in sorted(
            enumerate(events),
            key=lambda item: (item[1]["time_offset_seconds"], item[0]),
        )
    ]


def _round_seconds(value: float) -> float:
    return round(float(value), 6)
