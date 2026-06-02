from __future__ import annotations

import json
from html import escape as html_escape
from pathlib import Path
from typing import Any


PASS_STATUSES = {"passed", "dry_run_passed"}
METRIC_ORDER = [
    "travel_time",
    "path_length_traveled",
    "path_length",
    "recovery_count",
    "replanning_count",
    "collision_count",
    "collision_free",
    "goal_reached",
]


def load_run_report(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read report {path}: {exc}") from exc

    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON report {path}: {exc}") from exc

    if not isinstance(report, dict):
        raise ValueError("Run report must be a JSON object.")
    scenarios = report.get("scenarios", [])
    if not isinstance(scenarios, list):
        raise ValueError("Run report field 'scenarios' must be a list.")
    return report


def write_text_report(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_text_report(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(text)


def report_has_failures(report: dict[str, Any]) -> bool:
    failed = report.get("failed")
    if isinstance(failed, int):
        return failed > 0
    return any(not _is_passing_scenario(scenario) for scenario in _scenarios(report))


def format_run_report(report: dict[str, Any], output_format: str = "console") -> str:
    if output_format == "console":
        return format_console_report(report)
    if output_format == "markdown":
        return format_markdown_report(report)
    if output_format == "html":
        return format_html_report(report)
    raise ValueError(f"Unsupported report format: {output_format}")


def format_console_report(report: dict[str, Any]) -> str:
    scenarios = _scenarios(report)
    total = _count(report, "total", len(scenarios))
    failed = _count(report, "failed", sum(1 for scenario in scenarios if not _is_passing_scenario(scenario)))
    passed = _count(report, "passed", total - failed)
    label = "FAIL" if failed else "PASS"

    heading = (
        f"Report {label}: mode={_text(report.get('mode'), 'unknown')} "
        f"total={total} passed={passed} failed={failed}"
    )
    if report.get("generated_at"):
        heading += f" generated_at={report['generated_at']}"

    lines = [heading]
    if not scenarios:
        lines.append("No scenarios.")
        return "\n".join(lines) + "\n"

    for scenario in scenarios:
        status = _text(scenario.get("status"), "unknown")
        marker = "PASS" if _is_passing_scenario(scenario) else "FAIL"
        lines.append(
            f"- {marker} {_scenario_name(scenario)} status={status} "
            f"duration={_duration(scenario.get('duration_seconds'))} "
            f"steps={_count(scenario, 'step_count', len(_list(scenario.get('steps'))))} "
            f"assertions={_count(scenario, 'assertion_count', len(_list(scenario.get('assertions'))))}"
        )

        metrics = _format_metric_summary(scenario.get("metrics"))
        if metrics:
            lines.append(f"  metrics: {metrics}")
        artifact_summary = _format_artifact_summary(scenario)
        if artifact_summary and not _is_passing_scenario(scenario):
            lines.append(f"  artifacts: {artifact_summary}")

        if scenario.get("failure_reason"):
            lines.append(f"  reason: {scenario['failure_reason']}")

        for step in _interesting_steps(scenario):
            lines.append(
                f"  step {_text(step.get('index'), '?')}: {_text(step.get('kind'), 'unknown')} "
                f"{_text(step.get('status'), 'unknown')}"
                + (f" - {step['failure_reason']}" if step.get("failure_reason") else "")
            )

        for assertion in _interesting_assertions(scenario):
            message = _text(assertion.get("message"), "")
            suffix = f" - {message}" if message else ""
            lines.append(
                f"  assertion {_text(assertion.get('index'), '?')}: "
                f"{_text(assertion.get('kind'), 'unknown')} "
                f"{_text(assertion.get('status'), 'unknown')}{suffix}"
            )

    return "\n".join(lines) + "\n"


def format_markdown_report(report: dict[str, Any]) -> str:
    scenarios = _scenarios(report)
    total = _count(report, "total", len(scenarios))
    failed = _count(report, "failed", sum(1 for scenario in scenarios if not _is_passing_scenario(scenario)))
    passed = _count(report, "passed", total - failed)
    label = "FAIL" if failed else "PASS"

    lines = [
        "# Nav2 Scenario Report",
        "",
        f"- Result: `{label}`",
        f"- Mode: `{_escape_markdown(_text(report.get('mode'), 'unknown'))}`",
        f"- Total: `{total}`",
        f"- Passed: `{passed}`",
        f"- Failed: `{failed}`",
    ]
    if report.get("generated_at"):
        lines.append(f"- Generated: `{_escape_markdown(str(report['generated_at']))}`")

    lines.extend(
        [
            "",
            "| Scenario | Status | Duration | Travel Time | Path Length | Recovery | Replan | Collision Free |",
            "|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )

    for scenario in scenarios:
        metrics = _dict(scenario.get("metrics"))
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_markdown(_scenario_name(scenario)),
                    _escape_markdown(_text(scenario.get("status"), "unknown")),
                    _duration(scenario.get("duration_seconds")),
                    _metric_cell(metrics, "travel_time"),
                    _metric_cell(metrics, "path_length_traveled", fallback="path_length"),
                    _metric_cell(metrics, "recovery_count"),
                    _metric_cell(metrics, "replanning_count"),
                    _metric_cell(metrics, "collision_free"),
                ]
            )
            + " |"
        )

    detail_scenarios = [scenario for scenario in scenarios if _has_detail_section(scenario)]
    if detail_scenarios:
        lines.extend(["", "## Scenario Details"])
        for scenario in detail_scenarios:
            lines.extend(["", f"### {_escape_markdown(_scenario_name(scenario))}"])
            if scenario.get("failure_reason"):
                lines.append(f"- Reason: {_escape_markdown(str(scenario['failure_reason']))}")
            artifact_lines = _artifact_markdown_lines(scenario)
            if artifact_lines:
                lines.append("- Artifacts:")
                lines.extend(f"  - {line}" for line in artifact_lines)
            for step in _interesting_steps(scenario):
                line = (
                    f"- Step `{_escape_markdown(_text(step.get('index'), '?'))}` "
                    f"`{_escape_markdown(_text(step.get('kind'), 'unknown'))}` "
                    f"`{_escape_markdown(_text(step.get('status'), 'unknown'))}`"
                )
                if step.get("failure_reason"):
                    line += f": {_escape_markdown(str(step['failure_reason']))}"
                lines.append(line)
            for assertion in _interesting_assertions(scenario):
                line = (
                    f"- Assertion `{_escape_markdown(_text(assertion.get('index'), '?'))}` "
                    f"`{_escape_markdown(_text(assertion.get('kind'), 'unknown'))}` "
                    f"`{_escape_markdown(_text(assertion.get('status'), 'unknown'))}`"
                )
                if assertion.get("message"):
                    line += f": {_escape_markdown(str(assertion['message']))}"
                lines.append(line)

    return "\n".join(lines) + "\n"


def format_html_report(report: dict[str, Any]) -> str:
    scenarios = _scenarios(report)
    total = _count(report, "total", len(scenarios))
    failed = _count(report, "failed", sum(1 for scenario in scenarios if not _is_passing_scenario(scenario)))
    passed = _count(report, "passed", total - failed)
    label = "FAIL" if failed else "PASS"
    generated_at = _text(report.get("generated_at"), "-")
    mode = _text(report.get("mode"), "unknown")

    scenario_rows = "\n".join(_html_scenario_row(scenario) for scenario in scenarios)
    if not scenario_rows:
        scenario_rows = '<tr><td colspan="8" class="muted">No scenarios.</td></tr>'

    detail_sections = "\n".join(
        _html_detail_section(scenario)
        for scenario in scenarios
        if _has_detail_section(scenario)
    )
    if not detail_sections:
        detail_sections = '<p class="muted">No details.</p>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nav2 Scenario Report</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --panel: #ffffff;
      --text: #172033;
      --muted: #5b6475;
      --border: #d8dee8;
      --pass: #147d52;
      --fail: #bf2e2e;
      --warn: #9a6700;
      --info: #235fb2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    main {{
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 32px 0 48px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-start;
      margin-bottom: 24px;
    }}
    h1, h2, h3 {{ margin: 0; }}
    h1 {{ font-size: 28px; font-weight: 700; }}
    h2 {{ font-size: 18px; margin: 28px 0 12px; }}
    h3 {{ font-size: 15px; margin-bottom: 8px; }}
    .subtitle {{ margin: 6px 0 0; color: var(--muted); }}
    .badge {{
      display: inline-block;
      min-width: 64px;
      padding: 6px 10px;
      border-radius: 8px;
      color: #ffffff;
      text-align: center;
      font-weight: 700;
      background: var(--info);
    }}
    .badge.pass {{ background: var(--pass); }}
    .badge.fail {{ background: var(--fail); }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }}
    .summary-item {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
    }}
    .summary-item span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
    }}
    .summary-item strong {{
      display: block;
      margin-top: 4px;
      font-size: 18px;
    }}
    .table-wrap {{
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      min-width: 860px;
      border-collapse: collapse;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }}
    th {{
      background: #eef2f7;
      color: #2f3b52;
      font-size: 12px;
      text-transform: uppercase;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .status {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 8px;
      font-weight: 700;
      background: #e7edf7;
      color: var(--info);
    }}
    .status.pass {{ background: #e7f5ee; color: var(--pass); }}
    .status.fail {{ background: #fae8e8; color: var(--fail); }}
    .detail {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 12px;
    }}
    .reason {{ color: var(--fail); margin: 0 0 8px; }}
    ul {{ margin: 8px 0 0; padding-left: 20px; }}
    code {{
      background: #eef2f7;
      border-radius: 6px;
      padding: 1px 5px;
    }}
    .muted {{ color: var(--muted); }}
    .warning {{ color: var(--warn); }}
    @media (max-width: 720px) {{
      main {{ width: min(100% - 20px, 1180px); padding-top: 20px; }}
      header {{ display: block; }}
      .badge {{ margin-top: 12px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Nav2 Scenario Report</h1>
        <p class="subtitle">Generated {_html(generated_at)}</p>
      </div>
      <span class="badge {'fail' if failed else 'pass'}">{_html(label)}</span>
    </header>

    <section class="summary" aria-label="Run summary">
      {_html_summary_item("Mode", mode)}
      {_html_summary_item("Total", total)}
      {_html_summary_item("Passed", passed)}
      {_html_summary_item("Failed", failed)}
    </section>

    <section>
      <h2>Scenarios</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Scenario</th>
              <th>Status</th>
              <th class="num">Duration</th>
              <th class="num">Travel Time</th>
              <th class="num">Path Length</th>
              <th class="num">Recovery</th>
              <th class="num">Replan</th>
              <th>Collision Free</th>
            </tr>
          </thead>
          <tbody>
            {scenario_rows}
          </tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>Scenario Details</h2>
      {detail_sections}
    </section>
  </main>
</body>
</html>
"""


def _scenarios(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [scenario for scenario in _list(report.get("scenarios")) if isinstance(scenario, dict)]


def _html_scenario_row(scenario: dict[str, Any]) -> str:
    metrics = _dict(scenario.get("metrics"))
    status = _text(scenario.get("status"), "unknown")
    status_class = "pass" if _is_passing_scenario(scenario) else "fail"
    return (
        "<tr>"
        f"<td>{_html(_scenario_name(scenario))}</td>"
        f'<td><span class="status {status_class}">{_html(status)}</span></td>'
        f'<td class="num">{_html(_duration(scenario.get("duration_seconds")))}</td>'
        f'<td class="num">{_html(_metric_cell(metrics, "travel_time"))}</td>'
        f'<td class="num">{_html(_metric_cell(metrics, "path_length_traveled", fallback="path_length"))}</td>'
        f'<td class="num">{_html(_metric_cell(metrics, "recovery_count"))}</td>'
        f'<td class="num">{_html(_metric_cell(metrics, "replanning_count"))}</td>'
        f'<td>{_html(_metric_cell(metrics, "collision_free"))}</td>'
        "</tr>"
    )


def _html_detail_section(scenario: dict[str, Any]) -> str:
    lines = [f'<article class="detail"><h3>{_html(_scenario_name(scenario))}</h3>']
    if scenario.get("failure_reason"):
        lines.append(f'<p class="reason">{_html(str(scenario["failure_reason"]))}</p>')

    artifact_items = _artifact_html_items(scenario)
    if artifact_items:
        lines.append("<h4>Artifacts</h4>")
        lines.append("<ul>" + "".join(artifact_items) + "</ul>")

    step_lines = []
    for step in _interesting_steps(scenario):
        text = (
            f"Step {_text(step.get('index'), '?')}: "
            f"{_text(step.get('kind'), 'unknown')} "
            f"{_text(step.get('status'), 'unknown')}"
        )
        if step.get("failure_reason"):
            text += f" - {step['failure_reason']}"
        step_lines.append(f"<li>{_html(text)}</li>")
    if step_lines:
        lines.append("<ul>" + "".join(step_lines) + "</ul>")

    assertion_lines = []
    for assertion in _interesting_assertions(scenario):
        status = _text(assertion.get("status"), "unknown")
        css_class = "warning" if status == "warning" else ""
        text = (
            f"Assertion {_text(assertion.get('index'), '?')}: "
            f"{_text(assertion.get('kind'), 'unknown')} {status}"
        )
        if assertion.get("message"):
            text += f" - {assertion['message']}"
        class_attr = f' class="{css_class}"' if css_class else ""
        assertion_lines.append(f"<li{class_attr}>{_html(text)}</li>")
    if assertion_lines:
        lines.append("<ul>" + "".join(assertion_lines) + "</ul>")

    lines.append("</article>")
    return "\n".join(lines)


def _html_summary_item(label: str, value: Any) -> str:
    return (
        '<div class="summary-item">'
        f"<span>{_html(label)}</span>"
        f"<strong>{_html(_text(value, '-'))}</strong>"
        "</div>"
    )


def _interesting_steps(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        step
        for step in _list(scenario.get("steps"))
        if isinstance(step, dict) and _text(step.get("status"), "unknown") not in {"passed", "dry_run_passed"}
    ]


def _has_detail_section(scenario: dict[str, Any]) -> bool:
    return (
        not _is_passing_scenario(scenario)
        or bool(_interesting_assertions(scenario))
        or bool(_artifact_metrics(scenario))
    )


def _interesting_assertions(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        assertion
        for assertion in _list(scenario.get("assertions"))
        if isinstance(assertion, dict) and _text(assertion.get("status"), "unknown") != "passed"
    ]


def _artifact_metrics(scenario: dict[str, Any]) -> dict[str, str]:
    metrics = _dict(scenario.get("metrics"))
    artifacts: dict[str, str] = {}
    for key in ("artifact_dir", "scenario_copy", "gazebo_log", "metadata", "simulator_log"):
        value = metrics.get(key)
        if value:
            artifacts[key] = str(value)
    return artifacts


def _format_artifact_summary(scenario: dict[str, Any]) -> str:
    artifacts = _artifact_metrics(scenario)
    if not artifacts:
        return ""
    if artifacts.get("artifact_dir"):
        return artifacts["artifact_dir"]
    return ", ".join(f"{key}={value}" for key, value in artifacts.items())


def _artifact_markdown_lines(scenario: dict[str, Any]) -> list[str]:
    artifacts = _artifact_metrics(scenario)
    labels = {
        "artifact_dir": "Bundle",
        "scenario_copy": "Scenario",
        "gazebo_log": "Gazebo log",
        "metadata": "Metadata",
        "simulator_log": "Simulator log",
    }
    return [
        f"{labels[key]}: `{_escape_markdown(value)}`"
        for key, value in artifacts.items()
    ]


def _artifact_html_items(scenario: dict[str, Any]) -> list[str]:
    artifacts = _artifact_metrics(scenario)
    labels = {
        "artifact_dir": "Bundle",
        "scenario_copy": "Scenario",
        "gazebo_log": "Gazebo log",
        "metadata": "Metadata",
        "simulator_log": "Simulator log",
    }
    return [
        f"<li>{_html(labels[key])}: {_html_path_value(value)}</li>"
        for key, value in artifacts.items()
    ]


def _html_path_value(value: str) -> str:
    escaped = _html(value)
    if _is_linkable_path(value):
        return f'<a href="{escaped}"><code>{escaped}</code></a>'
    return f"<code>{escaped}</code>"


def _is_linkable_path(value: str) -> bool:
    return bool(value) and "://" not in value and not value.startswith("#")


def _is_passing_scenario(scenario: dict[str, Any]) -> bool:
    return _text(scenario.get("status"), "unknown") in PASS_STATUSES


def _scenario_name(scenario: dict[str, Any]) -> str:
    for key in ("scenario_id", "name", "path"):
        value = scenario.get(key)
        if value:
            return str(value)
    return "<unknown>"


def _format_metric_summary(metrics_value: Any) -> str:
    metrics = _dict(metrics_value)
    if not metrics:
        return ""

    keys = []
    for key in METRIC_ORDER:
        if key in metrics:
            keys.append(key)
    keys.extend(
        key
        for key in sorted(metrics)
        if key not in keys and not ("." in key and key.split(".", 1)[0] in metrics)
    )
    return ", ".join(f"{key}={_metric_value(metrics[key])}" for key in keys)


def _metric_cell(metrics: dict[str, Any], key: str, fallback: str | None = None) -> str:
    if key in metrics:
        return _metric_value(metrics[key])
    if fallback and fallback in metrics:
        return _metric_value(metrics[fallback])
    return "-"


def _metric_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    if value is None:
        return "-"
    return str(value)


def _duration(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.3f}s"
    return "-"


def _count(data: dict[str, Any], key: str, default: int) -> int:
    value = data.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any, default: str) -> str:
    if value is None:
        return default
    return str(value)


def _escape_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _html(value: Any) -> str:
    return html_escape(str(value), quote=True)
