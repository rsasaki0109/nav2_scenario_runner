"""Trajectory replay: overlay robot paths on a map and animate them.

The ``replay`` command reads a run report's per-scenario ``trajectory`` and
renders each one as an animated SVG. When a ROS map (``map.yaml`` + image) is
supplied it is drawn underneath the path so the trajectory is shown in its real
occupancy-grid context instead of on a blank grid.

Animation uses SVG SMIL ``<animateMotion>`` so the robot marker travels the
path with no JavaScript, keeping the output a single self-contained HTML file.
The PGM/PNM map image is re-encoded to a grayscale PNG with the standard library
only (``zlib`` + a tiny PNG writer), so there is no Pillow/numpy dependency.
"""

from __future__ import annotations

import base64
import json
import struct
import zlib
from dataclasses import dataclass
from html import escape as html_escape
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MapImage:
    width: int
    height: int
    resolution: float
    origin_x: float
    origin_y: float
    png_base64: str

    def project(self, x: float, y: float) -> tuple[float, float]:
        """World (x, y) in metres -> SVG pixel coords over the map image."""

        svg_x = (x - self.origin_x) / self.resolution
        svg_y = self.height - (y - self.origin_y) / self.resolution
        return svg_x, svg_y


@dataclass(frozen=True)
class ReplayScenario:
    scenario_id: str
    status: str
    points: list[dict[str, float]]
    metrics: dict[str, Any]


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_replay_scenarios(report: dict[str, Any], only: set[str] | None = None) -> list[ReplayScenario]:
    scenarios: list[ReplayScenario] = []
    for scenario in report.get("scenarios", []) if isinstance(report, dict) else []:
        if not isinstance(scenario, dict):
            continue
        scenario_id = str(scenario.get("scenario_id") or scenario.get("name") or "")
        if not scenario_id:
            continue
        if only and scenario_id not in only:
            continue
        points = _trajectory_points(scenario)
        if len(points) < 2:
            continue
        scenarios.append(
            ReplayScenario(
                scenario_id=scenario_id,
                status=str(scenario.get("status", "unknown")),
                points=points,
                metrics=_dict(scenario.get("metrics")),
            )
        )
    return scenarios


def load_map(map_yaml_path: Path) -> MapImage:
    try:
        raw = map_yaml_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read map {map_yaml_path}: {exc}") from exc
    try:
        meta = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid map YAML {map_yaml_path}: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError(f"Map YAML must be a mapping: {map_yaml_path}")

    image_name = meta.get("image")
    if not image_name:
        raise ValueError(f"Map YAML missing 'image': {map_yaml_path}")
    resolution = _as_float(meta.get("resolution"))
    if resolution is None or resolution <= 0:
        raise ValueError(f"Map YAML needs a positive 'resolution': {map_yaml_path}")
    origin = meta.get("origin") or [0.0, 0.0, 0.0]
    if not isinstance(origin, (list, tuple)) or len(origin) < 2:
        raise ValueError(f"Map YAML 'origin' must be [x, y, yaw]: {map_yaml_path}")
    negate = bool(_as_float(meta.get("negate")) or 0.0)

    image_path = (map_yaml_path.parent / str(image_name)).resolve()
    width, height, pixels = _read_pnm(image_path)
    if negate:
        pixels = bytes(255 - value for value in pixels)

    return MapImage(
        width=width,
        height=height,
        resolution=resolution,
        origin_x=float(origin[0]),
        origin_y=float(origin[1]),
        png_base64=_encode_png_gray(width, height, pixels),
    )


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def format_replay_html(
    scenarios: list[ReplayScenario],
    map_image: MapImage | None = None,
    duration_seconds: float = 4.0,
) -> str:
    cards = "\n".join(_replay_card(scenario, map_image, duration_seconds) for scenario in scenarios)
    if not cards:
        cards = '<p class="muted">No trajectories to replay.</p>'
    map_note = (
        f"map {map_image.width}&times;{map_image.height}px @ {map_image.resolution:g} m/px"
        if map_image
        else "no map underlay"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nav2 Replay</title>
  <style>
    :root {{
      --bg: #0f1726;
      --panel-solid: #182338;
      --text: #e8eef7;
      --muted: #9aa7bd;
      --border: #2a3850;
      --pass: #3ad29f;
      --fail: #ff6b6b;
      --path: #4aa3ff;
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
    h3 {{ font-size: 15px; margin: 0 0 10px; display: flex; align-items: center; gap: 10px; }}
    .subtitle {{ color: var(--muted); margin: 8px 0 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; margin-top: 18px; }}
    .card {{ background: var(--panel-solid); border: 1px solid var(--border); border-radius: 14px; padding: 14px 16px; }}
    .muted {{ color: var(--muted); }}
    .pill {{ font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #24314a; color: var(--muted); }}
    .pill.pass {{ background: #123a2c; color: var(--pass); }}
    .pill.fail {{ background: #3a1620; color: var(--fail); }}
    .meta {{ color: var(--muted); font-size: 12px; margin-top: 8px; display: flex; gap: 14px; flex-wrap: wrap; }}
    .meta strong {{ color: var(--text); }}
    svg {{ display: block; width: 100%; height: auto; background: #0d1524; border: 1px solid var(--border); border-radius: 10px; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Nav2 Replay</h1>
      <p class="subtitle">{len(scenarios)} trajectory replay(s) &middot; {map_note} &middot; looping animation</p>
    </header>
    <div class="grid">
      {cards}
    </div>
  </main>
</body>
</html>
"""


def _replay_card(scenario: ReplayScenario, map_image: MapImage | None, duration_seconds: float) -> str:
    passing = scenario.status in {"passed", "dry_run_passed"}
    pill_class = "pass" if passing else "fail"
    svg = _replay_svg(scenario, map_image, duration_seconds)
    distance = _metric(scenario.metrics, "path_length_traveled", "path_length")
    travel_time = _metric(scenario.metrics, "travel_time")
    meta_parts = [f"<span>Samples <strong>{len(scenario.points)}</strong></span>"]
    if distance is not None:
        meta_parts.append(f"<span>Path <strong>{_fmt(distance)} m</strong></span>")
    if travel_time is not None:
        meta_parts.append(f"<span>Time <strong>{_fmt(travel_time)} s</strong></span>")
    return f"""<div class="card">
  <h3>{_html(scenario.scenario_id)} <span class="pill {pill_class}">{_html(scenario.status)}</span></h3>
  {svg}
  <div class="meta">{''.join(meta_parts)}</div>
</div>"""


def _replay_svg(scenario: ReplayScenario, map_image: MapImage | None, duration_seconds: float) -> str:
    if map_image is not None:
        width = float(map_image.width)
        height = float(map_image.height)
        projected = [map_image.project(point["x"], point["y"]) for point in scenario.points]
        background = (
            f'<image href="data:image/png;base64,{map_image.png_base64}" x="0" y="0" '
            f'width="{width:.0f}" height="{height:.0f}" preserveAspectRatio="none" '
            f'style="image-rendering:pixelated"/>'
        )
        marker_r = max(2.0, min(width, height) * 0.012)
    else:
        width, height = 480.0, 320.0
        projected = _project_freeform(scenario.points, width, height, padding=22.0)
        background = _grid_background(width, height)
        marker_r = 6.0

    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in projected)
    path_d = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in projected)
    start_x, start_y = projected[0]
    end_x, end_y = projected[-1]
    dur = max(0.5, float(duration_seconds))
    path_color = "#3ad29f" if scenario.status in {"passed", "dry_run_passed"} else "#ff6b6b"

    return f"""<svg viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="Replay of {_html(scenario.scenario_id)}">
  {background}
  <polyline points="{_html(polyline)}" fill="none" stroke="{path_color}" stroke-width="{max(1.5, marker_r * 0.45):.2f}" stroke-linecap="round" stroke-linejoin="round" opacity="0.85"/>
  <circle cx="{start_x:.2f}" cy="{start_y:.2f}" r="{marker_r:.2f}" fill="#3ad29f"/>
  <circle cx="{end_x:.2f}" cy="{end_y:.2f}" r="{marker_r:.2f}" fill="#ff6b6b"/>
  <circle r="{marker_r * 1.15:.2f}" fill="#ffffff" stroke="#06101f" stroke-width="1.5">
    <animateMotion path="{_html(path_d)}" dur="{dur:.2f}s" repeatCount="indefinite" rotate="auto"/>
  </circle>
</svg>"""


def _project_freeform(
    points: list[dict[str, float]], width: float, height: float, padding: float
) -> list[tuple[float, float]]:
    min_x = min(point["x"] for point in points)
    max_x = max(point["x"] for point in points)
    min_y = min(point["y"] for point in points)
    max_y = max(point["y"] for point in points)
    span_x = max(max_x - min_x, 0.1)
    span_y = max(max_y - min_y, 0.1)
    scale = min((width - 2 * padding) / span_x, (height - 2 * padding) / span_y)
    draw_w = span_x * scale
    draw_h = span_y * scale
    off_x = (width - draw_w) / 2
    off_y = (height - draw_h) / 2
    projected = []
    for point in points:
        x = off_x + (point["x"] - min_x) * scale
        y = height - (off_y + (point["y"] - min_y) * scale)
        projected.append((x, y))
    return projected


def _grid_background(width: float, height: float) -> str:
    return (
        f'<defs><pattern id="replay-grid" width="32" height="32" patternUnits="userSpaceOnUse">'
        f'<path d="M 32 0 L 0 0 0 32" fill="none" stroke="#1c2740" stroke-width="1"/></pattern></defs>'
        f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="url(#replay-grid)"/>'
    )


# --------------------------------------------------------------------------- #
# PNM (PGM/PPM) reading and PNG writing -- standard library only
# --------------------------------------------------------------------------- #


def _read_pnm(path: Path) -> tuple[int, int, bytes]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Cannot read map image {path}: {exc}") from exc
    if len(data) < 2 or data[0:1] != b"P":
        raise ValueError(f"Unsupported map image (not PNM): {path}")
    magic = data[0:2]
    if magic not in (b"P5", b"P2"):
        raise ValueError(f"Unsupported PNM type {magic!r} (need P2 or P5): {path}")

    tokens, body_offset = _pnm_header_tokens(data, needed=3)
    width, height, maxval = (int(token) for token in tokens)
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid map image dimensions in {path}")
    count = width * height

    if magic == b"P5":
        if maxval >= 256:
            raise ValueError(f"16-bit PGM not supported: {path}")
        pixels = data[body_offset : body_offset + count]
        if len(pixels) < count:
            raise ValueError(f"Truncated PGM data in {path}")
        return width, height, bytes(pixels)

    # P2 ASCII
    values = data[body_offset:].split()
    if len(values) < count:
        raise ValueError(f"Truncated P2 data in {path}")
    scale = 255.0 / maxval if maxval else 1.0
    pixels = bytes(min(255, int(int(token) * scale)) for token in values[:count])
    return width, height, pixels


def _pnm_header_tokens(data: bytes, needed: int) -> tuple[list[str], int]:
    """Read `needed` integer tokens after the magic, skipping comments/whitespace."""

    tokens: list[str] = []
    index = 2  # past magic
    length = len(data)
    while len(tokens) < needed and index < length:
        char = data[index : index + 1]
        if char in b" \t\r\n":
            index += 1
            continue
        if char == b"#":
            while index < length and data[index : index + 1] != b"\n":
                index += 1
            continue
        start = index
        while index < length and data[index : index + 1] not in b" \t\r\n":
            index += 1
        tokens.append(data[start:index].decode("ascii"))
    # Skip the single whitespace byte that terminates the last header token.
    if index < length and data[index : index + 1] in b" \t\r\n":
        index += 1
    return tokens, index


def _encode_png_gray(width: int, height: int, pixels: bytes) -> str:
    raw = bytearray()
    for row in range(height):
        raw.append(0)  # filter type 0 (None) per scanline
        start = row * width
        raw.extend(pixels[start : start + width])
    compressed = zlib.compress(bytes(raw), 9)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)  # 8-bit grayscale
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode("ascii")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _trajectory_points(scenario: dict[str, Any]) -> list[dict[str, float]]:
    raw = _dict(scenario.get("metrics")).get("trajectory")
    points: list[dict[str, float]] = []
    for raw_point in raw if isinstance(raw, list) else []:
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


def _metric(metrics: dict[str, Any], key: str, fallback: str | None = None) -> float | None:
    value = metrics.get(key)
    number = _as_float(value)
    if number is not None:
        return number
    if fallback:
        return _as_float(metrics.get(fallback))
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _html(value: Any) -> str:
    return html_escape(str(value), quote=True)
