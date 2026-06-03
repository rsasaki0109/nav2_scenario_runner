from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PASS_STATUSES = {"passed", "dry_run_passed"}


@dataclass(frozen=True)
class MetricRule:
    kind: str
    metric: str
    limit: float


@dataclass(frozen=True)
class CompareIssue:
    kind: str
    scenario_id: str
    message: str
    baseline: Any = None
    current: Any = None
    rule: str | None = None


@dataclass(frozen=True)
class CompareReport:
    baseline_path: str
    current_path: str
    passed: bool
    checked_scenarios: int
    new_scenarios: list[str]
    missing_scenarios: list[str]
    issues: list[CompareIssue]


def compare_report_files(
    current_path: Path,
    baseline_path: Path,
    rules: list[MetricRule],
    allow_missing: bool = False,
) -> CompareReport:
    current = _load_report(current_path)
    baseline = _load_report(baseline_path)
    return compare_reports(
        current=current,
        baseline=baseline,
        current_path=current_path,
        baseline_path=baseline_path,
        rules=rules,
        allow_missing=allow_missing,
    )


def compare_reports(
    current: dict[str, Any],
    baseline: dict[str, Any],
    current_path: Path,
    baseline_path: Path,
    rules: list[MetricRule],
    allow_missing: bool = False,
) -> CompareReport:
    current_scenarios = _scenario_map(current)
    baseline_scenarios = _scenario_map(baseline)
    issues: list[CompareIssue] = []

    missing_scenarios = sorted(set(baseline_scenarios) - set(current_scenarios))
    new_scenarios = sorted(set(current_scenarios) - set(baseline_scenarios))

    if missing_scenarios and not allow_missing:
        for scenario_id in missing_scenarios:
            issues.append(
                CompareIssue(
                    kind="missing_scenario",
                    scenario_id=scenario_id,
                    message="Scenario existed in baseline but is missing from current report.",
                )
            )

    for scenario_id in sorted(set(current_scenarios) & set(baseline_scenarios)):
        current_scenario = current_scenarios[scenario_id]
        baseline_scenario = baseline_scenarios[scenario_id]
        issues.extend(_compare_status(scenario_id, current_scenario, baseline_scenario))
        issues.extend(_compare_metrics(scenario_id, current_scenario, baseline_scenario, rules))

    return CompareReport(
        baseline_path=str(baseline_path),
        current_path=str(current_path),
        passed=not issues,
        checked_scenarios=len(set(current_scenarios) & set(baseline_scenarios)),
        new_scenarios=new_scenarios,
        missing_scenarios=missing_scenarios,
        issues=issues,
    )


def parse_metric_rule(raw: str, kind: str) -> MetricRule:
    if "=" not in raw:
        raise ValueError(f"Expected METRIC=VALUE, got: {raw}")
    metric, value = raw.split("=", 1)
    metric = metric.strip()
    if not metric:
        raise ValueError(f"Metric name is empty in rule: {raw}")
    try:
        limit = float(value)
    except ValueError as exc:
        raise ValueError(f"Rule value must be numeric in {raw}") from exc
    if limit < 0:
        raise ValueError(f"Rule value must be non-negative in {raw}")
    return MetricRule(kind=kind, metric=metric, limit=limit)


def write_compare_report(report: CompareReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")


def write_compare_markdown(report: CompareReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_compare_markdown(report), encoding="utf-8")


def format_compare_markdown(report: CompareReport) -> str:
    label = "PASS" if report.passed else "FAIL"
    lines = [
        "# Nav2 Scenario Regression",
        "",
        f"- Result: `{label}`",
        f"- Checked scenarios: `{report.checked_scenarios}`",
        f"- Issues: `{len(report.issues)}`",
        f"- New scenarios: `{len(report.new_scenarios)}`",
        f"- Missing scenarios: `{len(report.missing_scenarios)}`",
        f"- Current: `{_escape_markdown(report.current_path)}`",
        f"- Baseline: `{_escape_markdown(report.baseline_path)}`",
    ]

    if report.issues:
        lines.extend(
            [
                "",
                "## Issues",
                "",
                "| Scenario | Kind | Message | Baseline | Current | Rule |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        for issue in report.issues:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_markdown(issue.scenario_id),
                        _escape_markdown(issue.kind),
                        _escape_markdown(issue.message),
                        _format_markdown_value(issue.baseline),
                        _format_markdown_value(issue.current),
                        _escape_markdown(issue.rule or "-"),
                    ]
                )
                + " |"
            )
    else:
        lines.extend(["", "No regressions detected."])

    if report.new_scenarios:
        lines.extend(["", "## New Scenarios", ""])
        lines.extend(f"- `{_escape_markdown(scenario_id)}`" for scenario_id in report.new_scenarios)

    if report.missing_scenarios:
        lines.extend(["", "## Missing Scenarios", ""])
        lines.extend(f"- `{_escape_markdown(scenario_id)}`" for scenario_id in report.missing_scenarios)

    return "\n".join(lines) + "\n"


def _load_report(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Cannot read report {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON report {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("scenarios"), list):
        raise ValueError(f"Report must contain a scenarios array: {path}")
    return data


def _scenario_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scenarios: dict[str, dict[str, Any]] = {}
    for scenario in report.get("scenarios", []):
        if not isinstance(scenario, dict):
            continue
        scenario_id = str(scenario.get("scenario_id") or scenario.get("name") or "")
        if scenario_id:
            scenarios[scenario_id] = scenario
    return scenarios


def _compare_status(
    scenario_id: str,
    current_scenario: dict[str, Any],
    baseline_scenario: dict[str, Any],
) -> list[CompareIssue]:
    baseline_status = str(baseline_scenario.get("status", ""))
    current_status = str(current_scenario.get("status", ""))
    if baseline_status in PASS_STATUSES and current_status not in PASS_STATUSES:
        return [
            CompareIssue(
                kind="status_regression",
                scenario_id=scenario_id,
                message=f"Scenario regressed from {baseline_status} to {current_status}.",
                baseline=baseline_status,
                current=current_status,
            )
        ]
    return []


def _compare_metrics(
    scenario_id: str,
    current_scenario: dict[str, Any],
    baseline_scenario: dict[str, Any],
    rules: list[MetricRule],
) -> list[CompareIssue]:
    issues: list[CompareIssue] = []
    for rule in rules:
        baseline_value = _numeric_metric(baseline_scenario, rule.metric)
        current_value = _numeric_metric(current_scenario, rule.metric)
        if baseline_value is None or current_value is None:
            continue

        if rule.kind == "max_increase_percent":
            allowed = _allowed_percent_value(baseline_value, rule.limit)
            if current_value > allowed:
                issues.append(
                    CompareIssue(
                        kind="metric_regression",
                        scenario_id=scenario_id,
                        message=(
                            f"{rule.metric} increased from {baseline_value:g} to "
                            f"{current_value:g}, exceeding {rule.limit:g}%."
                        ),
                        baseline=baseline_value,
                        current=current_value,
                        rule=f"{rule.metric}:max_increase_percent={rule.limit:g}",
                    )
                )
        elif rule.kind == "max_delta":
            delta = current_value - baseline_value
            if delta > rule.limit:
                issues.append(
                    CompareIssue(
                        kind="metric_regression",
                        scenario_id=scenario_id,
                        message=(
                            f"{rule.metric} increased by {delta:g}, exceeding "
                            f"max delta {rule.limit:g}."
                        ),
                        baseline=baseline_value,
                        current=current_value,
                        rule=f"{rule.metric}:max_delta={rule.limit:g}",
                    )
                )
        else:
            raise ValueError(f"Unsupported metric rule kind: {rule.kind}")
    return issues


def _numeric_metric(scenario: dict[str, Any], metric: str) -> float | None:
    metrics = scenario.get("metrics")
    if isinstance(metrics, dict) and metric in metrics:
        return _as_number(metrics[metric])
    if metric in scenario:
        return _as_number(scenario[metric])
    return None


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _allowed_percent_value(baseline_value: float, limit_percent: float) -> float:
    if baseline_value == 0:
        return 0.0
    return baseline_value * (1.0 + limit_percent / 100.0)


def _format_markdown_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    if value is None:
        return "-"
    return _escape_markdown(str(value))


def _escape_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
