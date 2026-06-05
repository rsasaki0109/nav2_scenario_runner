"""Validate a community benchmark submission before it lands on the leaderboard.

A submission is a single Nav2 run report dropped under
``examples/benchmark/submissions/<label>.json``. The public dashboard includes
every such file automatically (see ``scripts/build_dashboards.sh``), so a
malformed one would break the deployed leaderboard. The ``validate-submission``
command runs these checks in CI on each submission PR and renders a sticky
review comment that *previews where the configuration would rank* — turning a
chore into instant feedback that nudges contributors to participate.

The module is dependency-free and reuses the evaluate/replay loaders so the
review uses exactly the same scoring and map-bounds logic as the live site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .replay import MapImage, load_replay_scenarios

# A bot looks for this marker to find and replace its previous review comment.
REVIEW_MARKER = "<!-- nav2-scenario-runner:submission-review -->"

DEFAULT_REPO_URL = "https://github.com/rsasaki0109/nav2_scenario_runner"

# Core scenarios every submission must cover for an apples-to-apples comparison.
CORE_SCENARIO_IDS = ("straight_line", "narrow_corridor", "u_turn")

# Submission file stems must be descriptive, unique, kebab-case labels.
_LABEL_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


@dataclass
class SubmissionCheck:
    """The outcome of validating one submission file."""

    label: str
    path: str = ""
    ok: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scenario_ids: list[str] = field(default_factory=list)
    trajectory_scenarios: int = 0


def validate_submission(
    label: str,
    report: Any,
    *,
    map_image: MapImage | None = None,
    core_ids: tuple[str, ...] = CORE_SCENARIO_IDS,
    existing_labels: set[str] | None = None,
    path: str = "",
) -> SubmissionCheck:
    """Validate a single submission report and return a structured verdict.

    Checks: kebab-case unique label, well-formed ``scenarios`` array, coverage of
    the core scenario ids, presence of numeric metrics, and (when a map is given)
    that every trajectory point projects inside the map bounds.
    """

    check = SubmissionCheck(label=label, path=path)
    errors: list[str] = []
    warnings: list[str] = []
    existing = existing_labels or set()

    if not _LABEL_RE.match(label):
        errors.append(
            f"Label `{label}` must be kebab-case (lowercase letters, digits, single hyphens)."
        )
    if label in existing:
        errors.append(
            f"Label `{label}` collides with an existing config/submission — pick a unique filename."
        )

    if not isinstance(report, dict) or not isinstance(report.get("scenarios"), list):
        errors.append("Report must be a JSON object with a `scenarios` array.")
        check.errors = errors
        check.warnings = warnings
        check.ok = False
        return check

    scenario_ids: list[str] = []
    for scenario in report["scenarios"]:
        if isinstance(scenario, dict):
            sid = str(scenario.get("scenario_id") or scenario.get("name") or "")
            if sid:
                scenario_ids.append(sid)
    check.scenario_ids = scenario_ids

    missing = [sid for sid in core_ids if sid not in scenario_ids]
    if missing:
        errors.append("Missing core scenario(s): " + ", ".join(f"`{m}`" for m in missing))

    metric_scenarios = sum(
        1
        for scenario in report["scenarios"]
        if isinstance(scenario, dict)
        and isinstance(scenario.get("metrics"), dict)
        and any(key != "trajectory" for key in scenario["metrics"])
    )
    if metric_scenarios == 0:
        warnings.append("No numeric metrics found — the entry will score 0 on every metric.")

    if map_image is not None:
        replay = load_replay_scenarios(report)
        check.trajectory_scenarios = len(replay)
        out_of_bounds = 0
        for scenario in replay:
            for point in scenario.points:
                x, y = map_image.project(point["x"], point["y"])
                if not (-1.0 <= x <= map_image.width + 1.0 and -1.0 <= y <= map_image.height + 1.0):
                    out_of_bounds += 1
        if out_of_bounds:
            errors.append(
                f"{out_of_bounds} trajectory point(s) fall outside the warehouse map bounds."
            )
        elif not replay:
            warnings.append(
                "No trajectories — the entry won't appear on the trajectory overlay."
            )

    check.errors = errors
    check.warnings = warnings
    check.ok = not errors
    return check


def _check_block(check: SubmissionCheck) -> list[str]:
    icon = "✅" if check.ok else "❌"
    lines = [f"### {icon} `{check.label}`", ""]
    if check.ok:
        traj = (
            f" · {check.trajectory_scenarios} with trajectories"
            if check.trajectory_scenarios
            else ""
        )
        lines.append(f"Valid — {len(check.scenario_ids)} scenario(s){traj}.")
    else:
        lines.append(f"**{len(check.errors)} problem(s) must be fixed:**")
        lines.extend(f"- ❌ {error}" for error in check.errors)
    if check.warnings:
        lines.append("")
        lines.extend(f"- ⚠️ {warning}" for warning in check.warnings)
    lines.append("")
    return lines


def _preview_table(leaderboard: list[dict[str, Any]], submitted: set[str]) -> list[str]:
    lines = [
        "### 🏁 Leaderboard preview (with your submission)",
        "",
        "| Rank | Config | Score | Pass | Wins |",
        "|:--:|:--|--:|:--:|--:|",
    ]
    for entry in leaderboard:
        rank = int(entry["rank"])
        label = str(entry["label"])
        medal = _MEDALS.get(rank, f"#{rank}")
        mine = label in submitted
        name = f"**{label}** ⬅️ your entry" if mine else label
        score = f"{float(entry['score']):.1f}"
        passed, total = int(entry["passed"]), int(entry["total"])
        pass_str = f"{100.0 * passed / total:.0f}% ({passed}/{total})" if total else "n/a"
        lines.append(f"| {medal} | {name} | {score} | {pass_str} | {int(entry['wins'])} |")
    lines.append("")
    return lines


def build_review_comment(
    checks: list[SubmissionCheck],
    *,
    leaderboard: list[dict[str, Any]] | None = None,
    submitted_labels: set[str] | None = None,
    title: str = "Submission review",
    repo_url: str = DEFAULT_REPO_URL,
    dashboard_url: str | None = None,
) -> str:
    """Render the sticky Markdown review comment (including the hidden marker)."""

    if not checks:
        raise ValueError("build_review_comment needs at least one submission check")

    submitted = submitted_labels or set()
    failures = [check for check in checks if not check.ok]

    lines: list[str] = [REVIEW_MARKER, f"## 🧪 {title}", ""]
    if failures:
        lines.append(
            f"❌ **{len(failures)} of {len(checks)} submission(s) need changes** before merge."
        )
    else:
        lines.append(
            f"✅ **All {len(checks)} submission(s) valid** — ready to join the public leaderboard."
        )
    lines.append("")

    for check in checks:
        lines.extend(_check_block(check))

    if not failures and leaderboard:
        lines.extend(_preview_table(leaderboard, submitted))

    lines.append("---")
    footer = f"<sub>Checked by [nav2_scenario_runner]({repo_url})"
    if dashboard_url:
        footer += f" · [live leaderboard]({dashboard_url})"
    footer += "</sub>"
    lines.append(footer)
    lines.append("")
    return "\n".join(lines)
