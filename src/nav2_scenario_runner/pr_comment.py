"""Render a compact, PR-ready benchmark comment from evaluate/trend JSON.

The functions here intentionally consume the *machine-readable* dictionaries
emitted by ``evaluate --json-output`` and ``trend --json-output`` rather than
the in-memory dataclasses. That keeps the PR bot a clean, composable pipeline
step: run ``evaluate``/``trend``, then ``pr-comment`` over their artifacts.

The output carries a hidden HTML marker so a CI step can *upsert* (create or
update) a single sticky comment per pull request instead of spamming a new
comment on every push.
"""

from __future__ import annotations

from typing import Any

# A bot looks for this marker to find and replace its previous comment.
COMMENT_MARKER = "<!-- nav2-scenario-runner:benchmark -->"

DEFAULT_REPO_URL = "https://github.com/rsasaki0109/nav2_scenario_runner"

_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# How many regressions to list before collapsing the rest into a count.
_MAX_REGRESSION_ROWS = 8


def _medal(rank: int) -> str:
    return _MEDALS.get(rank, f"#{rank}")


def _fmt_pct(passed: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{100.0 * passed / total:.0f}% ({passed}/{total})"


def _fmt_delta(delta: float) -> str:
    return f"+{delta:.2f}" if delta >= 0 else f"{delta:.2f}"


def summarize_trend(trend: dict[str, Any]) -> dict[str, Any]:
    """Reduce a trend dict to comment-friendly counts and a regression list.

    Returns ``{"runs", "improvements", "regressions", "rows"}`` where ``rows``
    is the regressions sorted by absolute delta (largest first).
    """

    improvements = 0
    regressions = 0
    rows: list[dict[str, Any]] = []

    for metric, scenarios in (trend.get("latest_deltas") or {}).items():
        for scenario_id, info in scenarios.items():
            improved = info.get("improved")
            if improved is True:
                improvements += 1
            elif improved is False:
                regressions += 1
                rows.append(
                    {
                        "metric": metric,
                        "scenario": scenario_id,
                        "delta": float(info.get("delta", 0.0)),
                        "latest": info.get("latest"),
                    }
                )

    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return {
        "runs": int(trend.get("runs", 0)),
        "improvements": improvements,
        "regressions": regressions,
        "rows": rows,
    }


def _leaderboard_table(leaderboard: list[dict[str, Any]]) -> list[str]:
    lines = ["| Rank | Config | Score | Pass | Wins |", "|:--:|:--|--:|:--:|--:|"]
    for entry in leaderboard:
        rank = int(entry["rank"])
        label = str(entry["label"])
        name = f"**{label}**" if rank == 1 else label
        score = f"{float(entry['score']):.1f}"
        pass_str = _fmt_pct(int(entry["passed"]), int(entry["total"]))
        lines.append(f"| {_medal(rank)} | {name} | {score} | {pass_str} | {int(entry['wins'])} |")
    return lines


def _trend_section(trend: dict[str, Any]) -> list[str]:
    summary = summarize_trend(trend)
    lines: list[str] = ["", "### 📈 Trend vs previous run"]

    if summary["runs"] < 2:
        lines.append("")
        lines.append("First recorded run — no previous run to compare against yet.")
        return lines

    regressions = summary["regressions"]
    improvements = summary["improvements"]
    verdict = "⚠️" if regressions else "✅"
    lines.append("")
    lines.append(
        f"{verdict} **{regressions} regression(s)**, {improvements} improvement(s) "
        f"across the latest run."
    )

    rows = summary["rows"]
    if rows:
        lines.append("")
        lines.append("<details><summary>Regressions</summary>")
        lines.append("")
        lines.append("| Metric | Scenario | Δ | Latest |")
        lines.append("|:--|:--|--:|--:|")
        for row in rows[:_MAX_REGRESSION_ROWS]:
            latest = row["latest"]
            latest_str = f"{float(latest):.2f}" if isinstance(latest, (int, float)) else "—"
            lines.append(
                f"| {row['metric']} | {row['scenario']} | {_fmt_delta(row['delta'])} | {latest_str} |"
            )
        hidden = len(rows) - _MAX_REGRESSION_ROWS
        if hidden > 0:
            lines.append("")
            lines.append(f"_…and {hidden} more regression(s)._")
        lines.append("")
        lines.append("</details>")
    return lines


def build_comment(
    evaluation: dict[str, Any],
    trend: dict[str, Any] | None = None,
    *,
    title: str = "Nav2 Benchmark",
    dashboard_url: str | None = None,
    repo_url: str = DEFAULT_REPO_URL,
) -> str:
    """Build the full sticky-comment Markdown body (including the marker)."""

    leaderboard = evaluation.get("leaderboard") or []
    if not leaderboard:
        raise ValueError("evaluation JSON has an empty leaderboard")

    winner = leaderboard[0]
    scenario_count = int(evaluation.get("scenario_count", 0))

    lines: list[str] = [COMMENT_MARKER, f"## 🤖 {title}", ""]
    lines.append(
        f"🏆 **Winner: `{winner['label']}`** — score "
        f"{float(winner['score']):.1f} / 100 · pass {_fmt_pct(int(winner['passed']), int(winner['total']))}"
    )
    lines.append("")
    lines.append(
        f"{len(leaderboard)} configurations across {scenario_count} scenario(s)."
    )
    lines.append("")
    lines.extend(_leaderboard_table(leaderboard))

    if trend is not None:
        lines.extend(_trend_section(trend))

    lines.append("")
    lines.append("---")
    footer = f"<sub>Generated by [nav2_scenario_runner]({repo_url})"
    if dashboard_url:
        footer += f" · [full dashboard]({dashboard_url})"
    footer += "</sub>"
    lines.append(footer)
    lines.append("")
    return "\n".join(lines)
