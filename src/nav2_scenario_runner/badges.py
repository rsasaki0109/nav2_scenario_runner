"""Render shields.io *endpoint* badge JSON from evaluate/trend JSON.

A shields endpoint badge is a tiny JSON document hosted at a public URL:

    {"schemaVersion": 1, "label": "...", "message": "...", "color": "..."}

Pointing shields at it (``https://img.shields.io/endpoint?url=<json-url>``)
renders a live badge. Because GitHub Pages serves the JSON we already generate
for the benchmark, the README badges update themselves whenever the benchmark
is regenerated — no CI secret, no external service.
"""

from __future__ import annotations

from typing import Any

KINDS = ("winner", "score", "passrate", "regressions")

_MEDAL = {1: "🥇", 2: "🥈", 3: "🥉"}


def _score_color(score: float) -> str:
    if score >= 80:
        return "brightgreen"
    if score >= 60:
        return "green"
    if score >= 40:
        return "yellowgreen"
    if score >= 20:
        return "orange"
    return "red"


def _passrate_color(rate: float) -> str:
    if rate >= 1.0:
        return "brightgreen"
    if rate >= 0.8:
        return "green"
    if rate >= 0.5:
        return "yellow"
    return "red"


def _regression_color(count: int) -> str:
    if count == 0:
        return "brightgreen"
    if count <= 2:
        return "yellow"
    return "red"


def _winner(evaluation: dict[str, Any]) -> dict[str, Any]:
    leaderboard = evaluation.get("leaderboard") or []
    if not leaderboard:
        raise ValueError("evaluation JSON has an empty leaderboard")
    return leaderboard[0]


def _count_regressions(trend: dict[str, Any]) -> int:
    count = 0
    for scenarios in (trend.get("latest_deltas") or {}).values():
        for info in scenarios.values():
            if info.get("improved") is False:
                count += 1
    return count


def build_badge(
    kind: str,
    evaluation: dict[str, Any],
    trend: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a shields endpoint badge dict for ``kind``.

    ``kind`` is one of :data:`KINDS`. ``regressions`` requires ``trend``.
    """

    if kind not in KINDS:
        raise ValueError(f"unknown badge kind {kind!r}; expected one of {', '.join(KINDS)}")

    if kind == "winner":
        top = _winner(evaluation)
        return {
            "schemaVersion": 1,
            "label": "nav2 benchmark",
            "message": f"{top['label']} {_MEDAL.get(int(top['rank']), '')}".strip(),
            "color": "blue",
        }

    if kind == "score":
        score = float(_winner(evaluation)["score"])
        return {
            "schemaVersion": 1,
            "label": "benchmark score",
            "message": f"{score:.1f}/100",
            "color": _score_color(score),
        }

    if kind == "passrate":
        top = _winner(evaluation)
        rate = float(top["passed"]) / float(top["total"]) if top["total"] else 0.0
        return {
            "schemaVersion": 1,
            "label": "pass rate",
            "message": f"{rate * 100:.0f}%",
            "color": _passrate_color(rate),
        }

    # kind == "regressions"
    if trend is None:
        raise ValueError("the 'regressions' badge requires trend JSON")
    count = _count_regressions(trend)
    return {
        "schemaVersion": 1,
        "label": "regressions",
        "message": str(count),
        "color": _regression_color(count),
    }
