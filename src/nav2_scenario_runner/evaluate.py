"""Multi-configuration evaluation: rank Nav2 configs across a scenario suite.

The ``evaluate`` command takes several run reports -- one per Nav2
configuration (planner, controller, parameter set) -- and produces a single
leaderboard dashboard. Each scenario is run by every configuration, metrics are
normalized per scenario, and configurations are scored 0-100 so the best setup
is obvious at a glance. Trajectories from every configuration are overlaid on
shared axes for each scenario.

The module is intentionally dependency-free: charts are inline SVG, consistent
with :mod:`nav2_scenario_runner.report_view`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import escape as html_escape
from pathlib import Path
from typing import Any

PASS_STATUSES = {"passed", "dry_run_passed"}

# Metrics where a smaller value is a better navigation outcome.
DEFAULT_LOWER_IS_BETTER = (
    "travel_time",
    "path_length_traveled",
    "path_length",
    "recovery_count",
    "replanning_count",
    "collision_count",
    "duration_seconds",
)
# Boolean-style metrics where ``true`` (1.0) is the better outcome.
DEFAULT_HIGHER_IS_BETTER = (
    "collision_free",
    "goal_reached",
)

# Metric values that should never participate in scoring or charts.
EXCLUDED_METRICS = {"trajectory"}

# Distinct, colorblind-friendly palette for up to 8 configurations.
CONFIG_PALETTE = (
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
class ConfigEntry:
    """A single named configuration and its loaded run report."""

    label: str
    path: str
    report: dict[str, Any]


@dataclass
class MetricDirections:
    """Which way is "better" for each metric."""

    lower_is_better: set[str] = field(default_factory=lambda: set(DEFAULT_LOWER_IS_BETTER))
    higher_is_better: set[str] = field(default_factory=lambda: set(DEFAULT_HIGHER_IS_BETTER))

    def known(self, metric: str) -> bool:
        return metric in self.lower_is_better or metric in self.higher_is_better

    def is_lower_better(self, metric: str) -> bool:
        return metric in self.lower_is_better


@dataclass(frozen=True)
class ConfigScore:
    label: str
    color: str
    total: int
    passed: int
    pass_rate: float
    composite: float  # 0.0 - 1.0, higher is better
    wins: int
    rank: int


@dataclass(frozen=True)
class MetricCell:
    value: float | None
    normalized: float | None  # 0.0 worst .. 1.0 best within the scenario
    is_best: bool


@dataclass(frozen=True)
class ScenarioRow:
    scenario_id: str
    # per metric -> per config label -> cell
    cells: dict[str, dict[str, MetricCell]]
    statuses: dict[str, str]
    trajectories: dict[str, list[dict[str, float]]]


@dataclass(frozen=True)
class Evaluation:
    configs: list[ConfigScore]
    scenario_ids: list[str]
    metrics: list[str]
    rows: list[ScenarioRow]
    directions: MetricDirections


def parse_entry(raw: str) -> tuple[str, Path]:
    """Parse a ``LABEL=path/to/report.json`` evaluation entry."""

    if "=" not in raw:
        raise ValueError(f"Expected LABEL=PATH, got: {raw}")
    label, path = raw.split("=", 1)
    label = label.strip()
    path = path.strip()
    if not label:
        raise ValueError(f"Configuration label is empty in entry: {raw}")
    if not path:
        raise ValueError(f"Report path is empty in entry: {raw}")
    return label, Path(path)


def load_entries(entries: list[tuple[str, Path]], minimum: int = 2) -> list[ConfigEntry]:
    if len(entries) < minimum:
        count = "two" if minimum == 2 else str(minimum)
        raise ValueError(f"evaluate needs at least {count} --entry configurations to compare.")
    seen: set[str] = set()
    loaded: list[ConfigEntry] = []
    for label, path in entries:
        if label in seen:
            raise ValueError(f"Duplicate configuration label: {label}")
        seen.add(label)
        loaded.append(ConfigEntry(label=label, path=str(path), report=_load_report(path)))
    return loaded


def build_evaluation(
    entries: list[ConfigEntry],
    directions: MetricDirections | None = None,
) -> Evaluation:
    directions = directions or MetricDirections()
    labels = [entry.label for entry in entries]
    colors = {label: CONFIG_PALETTE[index % len(CONFIG_PALETTE)] for index, label in enumerate(labels)}

    scenario_maps = {entry.label: _scenario_map(entry.report) for entry in entries}

    # Scenario union, ordered by first appearance across configs.
    scenario_ids: list[str] = []
    for label in labels:
        for scenario_id in scenario_maps[label]:
            if scenario_id not in scenario_ids:
                scenario_ids.append(scenario_id)

    # Metric union restricted to known/scorable metrics, ordered consistently.
    metrics = _collect_metrics(scenario_ids, scenario_maps, labels, directions)

    rows: list[ScenarioRow] = []
    win_counts = {label: 0 for label in labels}
    composite_sums = {label: 0.0 for label in labels}
    composite_counts = {label: 0 for label in labels}

    for scenario_id in scenario_ids:
        cells: dict[str, dict[str, MetricCell]] = {}
        statuses: dict[str, str] = {}
        trajectories: dict[str, list[dict[str, float]]] = {}

        for label in labels:
            scenario = scenario_maps[label].get(scenario_id)
            statuses[label] = _status(scenario)
            points = _trajectory_points(scenario)
            if points:
                trajectories[label] = points

        for metric in metrics:
            raw_values = {
                label: _numeric_metric(scenario_maps[label].get(scenario_id), metric)
                for label in labels
            }
            present = {label: value for label, value in raw_values.items() if value is not None}
            normalized = _normalize(present, directions.is_lower_better(metric))
            best_norm = max(normalized.values(), default=None)

            metric_cells: dict[str, MetricCell] = {}
            for label in labels:
                value = raw_values[label]
                norm = normalized.get(label)
                is_best = (
                    norm is not None
                    and best_norm is not None
                    and abs(norm - best_norm) < 1e-9
                    and len(present) >= 2
                )
                metric_cells[label] = MetricCell(value=value, normalized=norm, is_best=is_best)
                if norm is not None and len(present) >= 2:
                    composite_sums[label] += norm
                    composite_counts[label] += 1
                if is_best:
                    win_counts[label] += 1
            cells[metric] = metric_cells

        rows.append(
            ScenarioRow(
                scenario_id=scenario_id,
                cells=cells,
                statuses=statuses,
                trajectories=trajectories,
            )
        )

    configs = _rank_configs(
        labels=labels,
        colors=colors,
        scenario_maps=scenario_maps,
        scenario_ids=scenario_ids,
        win_counts=win_counts,
        composite_sums=composite_sums,
        composite_counts=composite_counts,
    )

    return Evaluation(
        configs=configs,
        scenario_ids=scenario_ids,
        metrics=metrics,
        rows=rows,
        directions=directions,
    )


def _rank_configs(
    labels: list[str],
    colors: dict[str, str],
    scenario_maps: dict[str, dict[str, dict[str, Any]]],
    scenario_ids: list[str],
    win_counts: dict[str, int],
    composite_sums: dict[str, float],
    composite_counts: dict[str, int],
) -> list[ConfigScore]:
    scored: list[ConfigScore] = []
    for label in labels:
        present = [scenario_maps[label][sid] for sid in scenario_ids if sid in scenario_maps[label]]
        total = len(present)
        passed = sum(1 for scenario in present if _is_passing(scenario))
        pass_rate = passed / total if total else 0.0
        count = composite_counts[label]
        composite = composite_sums[label] / count if count else 0.0
        scored.append(
            ConfigScore(
                label=label,
                color=colors[label],
                total=total,
                passed=passed,
                pass_rate=pass_rate,
                composite=composite,
                wins=win_counts[label],
                rank=0,
            )
        )

    order = sorted(
        scored,
        key=lambda config: (config.pass_rate, config.composite, config.wins),
        reverse=True,
    )
    return [
        ConfigScore(
            label=config.label,
            color=config.color,
            total=config.total,
            passed=config.passed,
            pass_rate=config.pass_rate,
            composite=config.composite,
            wins=config.wins,
            rank=index + 1,
        )
        for index, config in enumerate(order)
    ]


def _collect_metrics(
    scenario_ids: list[str],
    scenario_maps: dict[str, dict[str, dict[str, Any]]],
    labels: list[str],
    directions: MetricDirections,
) -> list[str]:
    found: list[str] = []
    for scenario_id in scenario_ids:
        for label in labels:
            scenario = scenario_maps[label].get(scenario_id)
            metrics = _dict(scenario.get("metrics") if scenario else None)
            for key, value in metrics.items():
                if key in EXCLUDED_METRICS or key in found:
                    continue
                if "." in key:
                    continue  # skip per-goal sub-metrics for the headline view
                if not directions.known(key):
                    continue
                if _as_number(value) is None:
                    continue
                found.append(key)
    # Order by the canonical default ordering first, then discovery order.
    canonical = list(DEFAULT_LOWER_IS_BETTER) + list(DEFAULT_HIGHER_IS_BETTER)
    return sorted(found, key=lambda metric: (canonical.index(metric) if metric in canonical else len(canonical), metric))


def _normalize(values: dict[str, float], lower_is_better: bool) -> dict[str, float]:
    if not values:
        return {}
    low = min(values.values())
    high = max(values.values())
    if high == low:
        return {label: 1.0 for label in values}
    span = high - low
    result: dict[str, float] = {}
    for label, value in values.items():
        fraction = (value - low) / span
        result[label] = (1.0 - fraction) if lower_is_better else fraction
    return result


# --------------------------------------------------------------------------- #
# Rendering: Markdown
# --------------------------------------------------------------------------- #


def evaluation_to_dict(evaluation: Evaluation) -> dict[str, Any]:
    """A compact, machine-readable leaderboard for CI consumption."""

    return {
        "schema": "nav2_scenario_runner.evaluation/v1alpha1",
        "scenario_count": len(evaluation.scenario_ids),
        "metrics": list(evaluation.metrics),
        "leaderboard": [
            {
                "rank": config.rank,
                "label": config.label,
                "score": round(config.composite * 100, 2),
                "pass_rate": round(config.pass_rate, 4),
                "passed": config.passed,
                "total": config.total,
                "wins": config.wins,
            }
            for config in evaluation.configs
        ],
    }


def format_evaluation_markdown(evaluation: Evaluation) -> str:
    lines = ["# Nav2 Evaluation", ""]
    lines.append("## Leaderboard")
    lines.append("")
    lines.append("| Rank | Configuration | Score | Pass Rate | Wins |")
    lines.append("|---:|---|---:|---:|---:|")
    for config in evaluation.configs:
        medal = _medal(config.rank)
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{medal}{config.rank}",
                    _escape_markdown(config.label),
                    f"{config.composite * 100:.1f}",
                    f"{config.pass_rate * 100:.0f}% ({config.passed}/{config.total})",
                    str(config.wins),
                ]
            )
            + " |"
        )

    for metric in evaluation.metrics:
        lines.extend(["", f"## {_escape_markdown(metric)}", ""])
        header = "| Scenario | " + " | ".join(_escape_markdown(c.label) for c in evaluation.configs) + " |"
        sep = "|---|" + "|".join("---:" for _ in evaluation.configs) + "|"
        lines.append(header)
        lines.append(sep)
        for row in evaluation.rows:
            cells = row.cells.get(metric, {})
            rendered = []
            for config in evaluation.configs:
                cell = cells.get(config.label)
                rendered.append(_markdown_cell(cell))
            lines.append("| " + _escape_markdown(row.scenario_id) + " | " + " | ".join(rendered) + " |")

    return "\n".join(lines) + "\n"


def _markdown_cell(cell: MetricCell | None) -> str:
    if cell is None or cell.value is None:
        return "-"
    text = _format_number(cell.value)
    return f"**{text}**" if cell.is_best else text


# --------------------------------------------------------------------------- #
# Rendering: HTML dashboard
# --------------------------------------------------------------------------- #


def format_evaluation_html(evaluation: Evaluation) -> str:
    leaderboard = _html_leaderboard(evaluation)
    metric_charts = "\n".join(_html_metric_chart(evaluation, metric) for metric in evaluation.metrics)
    if not metric_charts:
        metric_charts = '<p class="muted">No comparable metrics.</p>'
    trajectory_sections = "\n".join(
        section for section in (_html_trajectory_overlay(evaluation, row) for row in evaluation.rows) if section
    )
    if not trajectory_sections:
        trajectory_sections = '<p class="muted">No trajectories captured.</p>'

    config_count = len(evaluation.configs)
    scenario_count = len(evaluation.scenario_ids)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nav2 Evaluation</title>
  <style>
    :root {{
      --bg: #0f1726;
      --panel: #16203455;
      --panel-solid: #182338;
      --text: #e8eef7;
      --muted: #9aa7bd;
      --border: #2a3850;
      --gold: #f5c542;
      --silver: #c6cedd;
      --bronze: #d08a4f;
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
    h2 {{ font-size: 20px; margin: 40px 0 14px; }}
    h3 {{ font-size: 15px; margin: 0 0 10px; color: var(--muted); font-weight: 600; }}
    .subtitle {{ color: var(--muted); margin: 8px 0 0; }}
    .leaderboard {{ display: grid; gap: 12px; }}
    .lb-card {{
      display: grid;
      grid-template-columns: 56px 1fr auto;
      align-items: center;
      gap: 18px;
      background: var(--panel-solid);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px 20px;
      position: relative;
      overflow: hidden;
    }}
    .lb-card.rank-1 {{ border-color: var(--gold); box-shadow: 0 0 0 1px var(--gold) inset, 0 8px 30px -12px var(--gold); }}
    .lb-rank {{ font-size: 26px; font-weight: 800; text-align: center; }}
    .lb-rank-1 {{ color: var(--gold); }}
    .lb-rank-2 {{ color: var(--silver); }}
    .lb-rank-3 {{ color: var(--bronze); }}
    .lb-name {{ font-size: 18px; font-weight: 700; display: flex; align-items: center; gap: 10px; }}
    .swatch {{ width: 14px; height: 14px; border-radius: 4px; flex: none; }}
    .lb-meta {{ color: var(--muted); font-size: 13px; margin-top: 2px; }}
    .lb-score {{ text-align: right; }}
    .lb-score strong {{ font-size: 30px; font-weight: 800; font-variant-numeric: tabular-nums; }}
    .lb-score span {{ display: block; color: var(--muted); font-size: 12px; }}
    .bar-track {{
      grid-column: 1 / -1;
      height: 8px;
      border-radius: 6px;
      background: #0d1524;
      overflow: hidden;
    }}
    .bar-fill {{ height: 100%; border-radius: 6px; }}
    .panel {{ background: var(--panel-solid); border: 1px solid var(--border); border-radius: 14px; padding: 18px 20px; }}
    .chart-row {{ display: grid; grid-template-columns: 150px 1fr; gap: 14px; align-items: center; margin: 10px 0; }}
    .chart-label {{ color: var(--muted); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 4px 0 18px; }}
    .legend span {{ display: inline-flex; align-items: center; gap: 7px; color: var(--muted); font-size: 13px; }}
    .traj-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .traj-card {{ background: var(--panel-solid); border: 1px solid var(--border); border-radius: 14px; padding: 14px 16px; }}
    .muted {{ color: var(--muted); }}
    .pill {{ font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #24314a; color: var(--muted); }}
    svg {{ display: block; }}
    .best-dot {{ color: var(--gold); }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Nav2 Evaluation</h1>
      <p class="subtitle">{config_count} configurations &middot; {scenario_count} scenarios &middot; composite score 0&ndash;100, higher is better</p>
    </header>

    <section>
      <h2>Leaderboard</h2>
      <div class="leaderboard">
        {leaderboard}
      </div>
    </section>

    <section>
      <h2>Metric Comparison</h2>
      <div class="legend">{_html_legend(evaluation)}</div>
      {metric_charts}
    </section>

    <section>
      <h2>Trajectory Overlay</h2>
      <div class="legend">{_html_legend(evaluation)}</div>
      <div class="traj-grid">
        {trajectory_sections}
      </div>
    </section>
  </main>
</body>
</html>
"""


def _html_legend(evaluation: Evaluation) -> str:
    return "".join(
        f'<span><i class="swatch" style="background:{config.color}"></i>{_html(config.label)}</span>'
        for config in evaluation.configs
    )


def _html_leaderboard(evaluation: Evaluation) -> str:
    cards = []
    best_composite = max((config.composite for config in evaluation.configs), default=0.0) or 1.0
    for config in evaluation.configs:
        fill_pct = (config.composite / best_composite) * 100 if best_composite else 0.0
        rank_class = f"lb-rank-{config.rank}" if config.rank <= 3 else ""
        medal = _medal(config.rank)
        cards.append(
            f"""<div class="lb-card rank-{config.rank}">
  <div class="lb-rank {rank_class}">{medal or config.rank}</div>
  <div>
    <div class="lb-name"><i class="swatch" style="background:{config.color}"></i>{_html(config.label)}</div>
    <div class="lb-meta">Pass {config.pass_rate * 100:.0f}% ({config.passed}/{config.total}) &middot; {config.wins} metric wins</div>
  </div>
  <div class="lb-score"><strong>{config.composite * 100:.1f}</strong><span>score</span></div>
  <div class="bar-track"><div class="bar-fill" style="width:{fill_pct:.1f}%;background:{config.color}"></div></div>
</div>"""
        )
    return "\n".join(cards)


def _html_metric_chart(evaluation: Evaluation, metric: str) -> str:
    # Bar length encodes normalized "goodness" so the longest bar is always the
    # winner regardless of metric direction; the label shows the real mean value.
    value_sums: dict[str, float] = {config.label: 0.0 for config in evaluation.configs}
    norm_sums: dict[str, float] = {config.label: 0.0 for config in evaluation.configs}
    counts: dict[str, int] = {config.label: 0 for config in evaluation.configs}
    for row in evaluation.rows:
        for label, cell in row.cells.get(metric, {}).items():
            if cell.value is not None and cell.normalized is not None:
                value_sums[label] += cell.value
                norm_sums[label] += cell.normalized
                counts[label] += 1
    present = [config.label for config in evaluation.configs if counts[config.label]]
    if not present:
        return ""

    mean_value = {label: value_sums[label] / counts[label] for label in present}
    mean_norm = {label: norm_sums[label] / counts[label] for label in present}
    best_norm = max(mean_norm.values())

    rows_html = []
    for config in evaluation.configs:
        if config.label not in mean_value:
            continue
        # Floor the width so a zero-goodness bar still shows a sliver of color.
        width = 6 + mean_norm[config.label] * 94
        is_best = abs(mean_norm[config.label] - best_norm) < 1e-9
        dot = ' <span class="best-dot">&#9733;</span>' if is_best else ""
        rows_html.append(
            f"""<div class="chart-row">
  <div class="chart-label">{_html(config.label)}</div>
  <div class="bar-track" style="height:18px">
    <div class="bar-fill" style="width:{width:.1f}%;background:{config.color};display:flex;align-items:center;justify-content:flex-end;padding-right:8px;font-size:12px;color:#06101f;font-weight:700">{_format_number(mean_value[config.label])}{dot}</div>
  </div>
</div>"""
        )
    arrow = "lower is better" if evaluation.directions.is_lower_better(metric) else "higher is better"
    return f"""<div class="panel" style="margin-bottom:16px">
  <h3>{_html(metric)} <span class="pill">{arrow}</span> <span class="pill">bar = relative goodness</span></h3>
  {''.join(rows_html)}
</div>"""


def _html_trajectory_overlay(evaluation: Evaluation, row: ScenarioRow) -> str:
    series = {label: points for label, points in row.trajectories.items() if len(points) >= 2}
    if not series:
        return ""

    width, height, padding = 360.0, 240.0, 18.0
    all_points = [point for points in series.values() for point in points]
    min_x = min(point["x"] for point in all_points)
    max_x = max(point["x"] for point in all_points)
    min_y = min(point["y"] for point in all_points)
    max_y = max(point["y"] for point in all_points)
    span_x = max(max_x - min_x, 0.1)
    span_y = max(max_y - min_y, 0.1)
    scale = min((width - 2 * padding) / span_x, (height - 2 * padding) / span_y)
    draw_w = span_x * scale
    draw_h = span_y * scale
    off_x = (width - draw_w) / 2
    off_y = (height - draw_h) / 2

    def project(point: dict[str, float]) -> tuple[float, float]:
        x = off_x + (point["x"] - min_x) * scale
        y = height - (off_y + (point["y"] - min_y) * scale)
        return x, y

    grid_id = _grid_id(row.scenario_id)
    polylines = []
    color_by_label = {config.label: config.color for config in evaluation.configs}
    for label, points in series.items():
        projected = [project(point) for point in points]
        polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in projected)
        color = color_by_label.get(label, "#235fb2")
        end_x, end_y = projected[-1]
        polylines.append(
            f'<polyline points="{_html(polyline)}" fill="none" stroke="{color}" '
            f'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" opacity="0.9"/>'
            f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="4" fill="{color}"/>'
        )

    return f"""<div class="traj-card">
  <h3>{_html(row.scenario_id)}</h3>
  <svg viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="Trajectory overlay for {_html(row.scenario_id)}" style="width:100%;height:auto;background:#0d1524;border:1px solid var(--border);border-radius:10px">
    <defs>
      <pattern id="{grid_id}" width="32" height="32" patternUnits="userSpaceOnUse">
        <path d="M 32 0 L 0 0 0 32" fill="none" stroke="#1c2740" stroke-width="1"/>
      </pattern>
    </defs>
    <rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="url(#{grid_id})"/>
    {''.join(polylines)}
  </svg>
</div>"""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


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


def _status(scenario: dict[str, Any] | None) -> str:
    if not scenario:
        return "absent"
    return str(scenario.get("status", "unknown"))


def _is_passing(scenario: dict[str, Any]) -> bool:
    return str(scenario.get("status", "")) in PASS_STATUSES


def _numeric_metric(scenario: dict[str, Any] | None, metric: str) -> float | None:
    if not scenario:
        return None
    metrics = scenario.get("metrics")
    if isinstance(metrics, dict) and metric in metrics:
        return _as_number(metrics[metric])
    if metric in scenario:
        return _as_number(scenario[metric])
    return None


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _trajectory_points(scenario: dict[str, Any] | None) -> list[dict[str, float]]:
    if not scenario:
        return []
    raw_points = _dict(scenario.get("metrics")).get("trajectory")
    points: list[dict[str, float]] = []
    for raw_point in raw_points if isinstance(raw_points, list) else []:
        if not isinstance(raw_point, dict):
            continue
        x = raw_point.get("x")
        y = raw_point.get("y")
        if (
            isinstance(x, (int, float))
            and isinstance(y, (int, float))
            and not isinstance(x, bool)
            and not isinstance(y, bool)
        ):
            points.append({"x": float(x), "y": float(y)})
    return points


def _medal(rank: int) -> str:
    return {1: "\U0001f947 ", 2: "\U0001f948 ", 3: "\U0001f949 "}.get(rank, "")


def _format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _grid_id(scenario_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", scenario_id).strip("-") or "scenario"
    return f"eval-grid-{safe[:48]}"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _escape_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _html(value: Any) -> str:
    return html_escape(str(value), quote=True)
