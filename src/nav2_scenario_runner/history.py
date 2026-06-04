"""Run history and trend tracking.

The ``record`` command appends a run report to an append-only JSONL history
store, one line per run, keyed by a label (typically a commit SHA). The
``trend`` command reads that store and renders how metrics move over time, so a
team can watch for navigation quality drifting across commits in CI.

Like :mod:`nav2_scenario_runner.evaluate`, this module is dependency-free and
renders inline SVG.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import escape as html_escape
from pathlib import Path
from typing import Any

from .evaluate import (
    DEFAULT_HIGHER_IS_BETTER,
    DEFAULT_LOWER_IS_BETTER,
    MetricDirections,
)

PASS_STATUSES = {"passed", "dry_run_passed"}

# Per-run metric values that are not scalar trend material.
EXCLUDED_METRICS = {
    "trajectory",
    "artifact_dir",
    "scenario_copy",
    "gazebo_log",
    "metadata",
    "simulator_log",
}

SERIES_PALETTE = (
    "#235fb2",
    "#bf2e2e",
    "#147d52",
    "#9a6700",
    "#7048b6",
    "#0f7d8c",
    "#c0497b",
    "#5b6475",
)


@dataclass(frozen=True)
class HistoryEntry:
    label: str
    timestamp: str
    mode: str
    total: int
    passed: int
    failed: int
    scenarios: dict[str, dict[str, Any]]  # scenario_id -> {status, metrics{}}


@dataclass(frozen=True)
class Trend:
    labels: list[str]
    timestamps: list[str]
    pass_rates: list[float]
    metrics: list[str]
    scenario_ids: list[str]
    # metric -> scenario_id -> list aligned with labels (None where absent)
    series: dict[str, dict[str, list[float | None]]]
    directions: MetricDirections


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #


def summarize_report(report: dict[str, Any], label: str, timestamp: str | None) -> HistoryEntry:
    """Reduce a run report to a compact, scalar-only history entry."""

    if not isinstance(report, dict) or not isinstance(report.get("scenarios"), list):
        raise ValueError("Report must contain a scenarios array.")

    scenarios: dict[str, dict[str, Any]] = {}
    for scenario in report["scenarios"]:
        if not isinstance(scenario, dict):
            continue
        scenario_id = str(scenario.get("scenario_id") or scenario.get("name") or "")
        if not scenario_id:
            continue
        scenarios[scenario_id] = {
            "status": str(scenario.get("status", "unknown")),
            "metrics": _scalar_metrics(scenario.get("metrics")),
        }

    total = _int(report.get("total"), len(scenarios))
    passed = _int(
        report.get("passed"),
        sum(1 for scenario in scenarios.values() if scenario["status"] in PASS_STATUSES),
    )
    failed = _int(report.get("failed"), total - passed)

    resolved_timestamp = timestamp or str(report.get("generated_at") or "")
    return HistoryEntry(
        label=label,
        timestamp=resolved_timestamp,
        mode=str(report.get("mode", "unknown")),
        total=total,
        passed=passed,
        failed=failed,
        scenarios=scenarios,
    )


def entry_to_dict(entry: HistoryEntry) -> dict[str, Any]:
    return {
        "label": entry.label,
        "timestamp": entry.timestamp,
        "mode": entry.mode,
        "total": entry.total,
        "passed": entry.passed,
        "failed": entry.failed,
        "scenarios": entry.scenarios,
    }


def append_history(history_path: Path, entry: HistoryEntry) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry_to_dict(entry), sort_keys=True)
    with history_path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def load_history(history_path: Path) -> list[HistoryEntry]:
    try:
        raw = history_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read history {history_path}: {exc}") from exc

    entries: list[HistoryEntry] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid history line {line_number} in {history_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"History line {line_number} is not an object in {history_path}.")
        entries.append(
            HistoryEntry(
                label=str(data.get("label", "")),
                timestamp=str(data.get("timestamp", "")),
                mode=str(data.get("mode", "unknown")),
                total=_int(data.get("total"), 0),
                passed=_int(data.get("passed"), 0),
                failed=_int(data.get("failed"), 0),
                scenarios=data.get("scenarios") if isinstance(data.get("scenarios"), dict) else {},
            )
        )
    return entries


# --------------------------------------------------------------------------- #
# Trend assembly
# --------------------------------------------------------------------------- #


def build_trend(entries: list[HistoryEntry], directions: MetricDirections | None = None) -> Trend:
    if not entries:
        raise ValueError("Trend needs at least one recorded run.")
    directions = directions or MetricDirections()

    labels = [entry.label or entry.timestamp or f"run{index + 1}" for index, entry in enumerate(entries)]
    timestamps = [entry.timestamp for entry in entries]
    pass_rates = [(entry.passed / entry.total) if entry.total else 0.0 for entry in entries]

    scenario_ids: list[str] = []
    metrics: list[str] = []
    for entry in entries:
        for scenario_id, scenario in entry.scenarios.items():
            if scenario_id not in scenario_ids:
                scenario_ids.append(scenario_id)
            for metric in _dict(scenario.get("metrics")):
                if metric not in metrics:
                    metrics.append(metric)

    metrics = _order_metrics(metrics)

    series: dict[str, dict[str, list[float | None]]] = {}
    for metric in metrics:
        per_scenario: dict[str, list[float | None]] = {}
        for scenario_id in scenario_ids:
            values: list[float | None] = []
            for entry in entries:
                scenario = entry.scenarios.get(scenario_id)
                metric_value = _dict(scenario.get("metrics") if scenario else None).get(metric)
                values.append(_as_number(metric_value))
            if any(value is not None for value in values):
                per_scenario[scenario_id] = values
        if per_scenario:
            series[metric] = per_scenario

    return Trend(
        labels=labels,
        timestamps=timestamps,
        pass_rates=pass_rates,
        metrics=[metric for metric in metrics if metric in series],
        scenario_ids=scenario_ids,
        series=series,
        directions=directions,
    )


def trend_to_dict(trend: Trend) -> dict[str, Any]:
    latest_index = len(trend.labels) - 1
    deltas: dict[str, dict[str, Any]] = {}
    for metric, per_scenario in trend.series.items():
        metric_deltas: dict[str, Any] = {}
        for scenario_id, values in per_scenario.items():
            delta = _latest_delta(values)
            if delta is not None:
                metric_deltas[scenario_id] = {
                    "latest": values[latest_index],
                    "delta": round(delta, 6),
                    "improved": _is_improvement(metric, delta, trend.directions),
                }
        if metric_deltas:
            deltas[metric] = metric_deltas
    return {
        "schema": "nav2_scenario_runner.trend/v1alpha1",
        "runs": len(trend.labels),
        "labels": list(trend.labels),
        "pass_rates": [round(rate, 4) for rate in trend.pass_rates],
        "metrics": list(trend.metrics),
        "latest_deltas": deltas,
    }


# --------------------------------------------------------------------------- #
# Rendering: Markdown
# --------------------------------------------------------------------------- #


def format_trend_markdown(trend: Trend) -> str:
    lines = ["# Nav2 Trend", ""]
    lines.append(f"- Runs: `{len(trend.labels)}`")
    lines.append(f"- Latest: `{_escape_markdown(trend.labels[-1])}`")
    lines.append(f"- Pass rate: `{trend.pass_rates[-1] * 100:.0f}%`")

    lines.extend(["", "## Pass Rate", "", "| Run | Pass Rate |", "|---|---:|"])
    for label, rate in zip(trend.labels, trend.pass_rates):
        lines.append(f"| {_escape_markdown(label)} | {rate * 100:.0f}% |")

    for metric in trend.metrics:
        lines.extend(["", f"## {_escape_markdown(metric)} (latest vs previous)", ""])
        lines.append("| Scenario | Latest | Δ vs previous | Trend |")
        lines.append("|---|---:|---:|---|")
        for scenario_id, values in trend.series[metric].items():
            latest = values[-1]
            delta = _latest_delta(values)
            if latest is None:
                continue
            delta_text = "-" if delta is None else f"{delta:+g}"
            marker = _trend_marker(metric, delta, trend.directions)
            lines.append(
                f"| {_escape_markdown(scenario_id)} | {_format_number(latest)} | {delta_text} | {marker} |"
            )

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Rendering: HTML dashboard
# --------------------------------------------------------------------------- #


def format_trend_html(trend: Trend) -> str:
    pass_chart = _pass_rate_chart(trend)
    metric_panels = "\n".join(_metric_trend_panel(trend, metric) for metric in trend.metrics)
    if not metric_panels:
        metric_panels = '<p class="muted">No scalar metrics recorded.</p>'

    latest_pass = trend.pass_rates[-1] * 100 if trend.pass_rates else 0.0

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nav2 Trend</title>
  <style>
    :root {{
      --bg: #0f1726;
      --panel-solid: #182338;
      --text: #e8eef7;
      --muted: #9aa7bd;
      --border: #2a3850;
      --pass: #3ad29f;
      --fail: #ff6b6b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(1200px 600px at 70% -10%, #1d2c4a 0%, var(--bg) 55%);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 40px 0 64px; }}
    h1 {{ font-size: 30px; margin: 0; letter-spacing: -0.02em; }}
    h2 {{ font-size: 20px; margin: 36px 0 14px; }}
    h3 {{ font-size: 15px; margin: 0 0 10px; color: var(--muted); font-weight: 600; }}
    .subtitle {{ color: var(--muted); margin: 8px 0 0; }}
    .panel {{ background: var(--panel-solid); border: 1px solid var(--border); border-radius: 14px; padding: 18px 20px; margin-bottom: 16px; }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 4px 0 14px; }}
    .legend span {{ display: inline-flex; align-items: center; gap: 7px; color: var(--muted); font-size: 13px; }}
    .swatch {{ width: 12px; height: 12px; border-radius: 3px; flex: none; }}
    .muted {{ color: var(--muted); }}
    .pill {{ font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #24314a; color: var(--muted); }}
    .up {{ color: var(--fail); }}
    .down {{ color: var(--pass); }}
    svg {{ display: block; width: 100%; height: auto; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Nav2 Trend</h1>
      <p class="subtitle">{len(trend.labels)} runs &middot; latest pass rate {latest_pass:.0f}% &middot; latest <code>{_html(trend.labels[-1])}</code></p>
    </header>

    <section>
      <h2>Pass Rate</h2>
      <div class="panel">{pass_chart}</div>
    </section>

    <section>
      <h2>Metric Trends</h2>
      {metric_panels}
    </section>
  </main>
</body>
</html>
"""


def _pass_rate_chart(trend: Trend) -> str:
    values = [rate * 100 for rate in trend.pass_rates]
    series = {"pass_rate": values}
    return _line_chart(
        labels=trend.labels,
        series_values=series,
        colors={"pass_rate": "#3ad29f"},
        y_min=0.0,
        y_max=100.0,
        value_suffix="%",
    )


def _metric_trend_panel(trend: Trend, metric: str) -> str:
    per_scenario = trend.series[metric]
    colors = {
        scenario_id: SERIES_PALETTE[index % len(SERIES_PALETTE)]
        for index, scenario_id in enumerate(per_scenario)
    }
    legend = "".join(
        f'<span><i class="swatch" style="background:{color}"></i>{_html(scenario_id)}</span>'
        for scenario_id, color in colors.items()
    )
    arrow = "lower is better" if trend.directions.is_lower_better(metric) else (
        "higher is better" if metric in trend.directions.higher_is_better else "tracked"
    )
    chart = _line_chart(labels=trend.labels, series_values=per_scenario, colors=colors)
    return f"""<div class="panel">
  <h3>{_html(metric)} <span class="pill">{arrow}</span></h3>
  <div class="legend">{legend}</div>
  {chart}
</div>"""


def _line_chart(
    labels: list[str],
    series_values: dict[str, list[float | None]],
    colors: dict[str, str],
    y_min: float | None = None,
    y_max: float | None = None,
    value_suffix: str = "",
) -> str:
    width = max(560.0, 90.0 * max(len(labels), 1))
    width = min(width, 1100.0)
    height = 240.0
    pad_l, pad_r, pad_t, pad_b = 48.0, 18.0, 18.0, 40.0

    flat = [value for values in series_values.values() for value in values if value is not None]
    if not flat:
        return '<p class="muted">No data.</p>'
    lo = y_min if y_min is not None else min(flat)
    hi = y_max if y_max is not None else max(flat)
    if hi == lo:
        hi = lo + 1.0
    span = hi - lo

    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(labels)

    def x_of(index: int) -> float:
        if n == 1:
            return pad_l + plot_w / 2
        return pad_l + (index / (n - 1)) * plot_w

    def y_of(value: float) -> float:
        return pad_t + (1.0 - (value - lo) / span) * plot_h

    # Gridlines + y labels (3 horizontal lines).
    grid = []
    for fraction in (0.0, 0.5, 1.0):
        value = lo + fraction * span
        y = pad_t + (1.0 - fraction) * plot_h
        grid.append(
            f'<line x1="{pad_l:.1f}" y1="{y:.1f}" x2="{width - pad_r:.1f}" y2="{y:.1f}" stroke="#1c2740" stroke-width="1"/>'
            f'<text x="{pad_l - 8:.1f}" y="{y + 4:.1f}" fill="#9aa7bd" font-size="11" text-anchor="end">{_format_number(value)}{value_suffix}</text>'
        )

    # X axis labels (thin them when crowded).
    step = max(1, n // 8)
    x_labels = []
    for index, label in enumerate(labels):
        if index % step != 0 and index != n - 1:
            continue
        x = x_of(index)
        short = label if len(label) <= 10 else label[:9] + "…"
        x_labels.append(
            f'<text x="{x:.1f}" y="{height - 14:.1f}" fill="#9aa7bd" font-size="11" text-anchor="middle">{_html(short)}</text>'
        )

    polylines = []
    for series_id, values in series_values.items():
        color = colors.get(series_id, "#235fb2")
        segment: list[str] = []
        dots: list[str] = []
        for index, value in enumerate(values):
            if value is None:
                continue
            x, y = x_of(index), y_of(value)
            segment.append(f"{x:.1f},{y:.1f}")
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>')
        if segment:
            polylines.append(
                f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" '
                f'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>' + "".join(dots)
            )

    return (
        f'<svg viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="Trend chart" '
        f'style="background:#0d1524;border:1px solid var(--border);border-radius:10px">'
        + "".join(grid)
        + "".join(x_labels)
        + "".join(polylines)
        + "</svg>"
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _scalar_metrics(metrics: Any) -> dict[str, float]:
    result: dict[str, float] = {}
    if not isinstance(metrics, dict):
        return result
    for key, value in metrics.items():
        if key in EXCLUDED_METRICS or "." in key:
            continue
        number = _as_number(value)
        if number is not None:
            result[key] = number
    return result


def _order_metrics(metrics: list[str]) -> list[str]:
    canonical = list(DEFAULT_LOWER_IS_BETTER) + list(DEFAULT_HIGHER_IS_BETTER)
    return sorted(
        metrics,
        key=lambda metric: (canonical.index(metric) if metric in canonical else len(canonical), metric),
    )


def _latest_delta(values: list[float | None]) -> float | None:
    present = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(present) < 2:
        return None
    return present[-1][1] - present[-2][1]


def _is_improvement(metric: str, delta: float, directions: MetricDirections) -> bool | None:
    if delta == 0:
        return None
    if directions.is_lower_better(metric):
        return delta < 0
    if metric in directions.higher_is_better:
        return delta > 0
    return None


def _trend_marker(metric: str, delta: float | None, directions: MetricDirections) -> str:
    if delta is None or delta == 0:
        return "&rarr; stable"
    improved = _is_improvement(metric, delta, directions)
    if improved is True:
        return "&#9660; better"
    if improved is False:
        return "&#9650; worse"
    return ("&#9650; up" if delta > 0 else "&#9660; down")


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _escape_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _html(value: Any) -> str:
    return html_escape(str(value), quote=True)
