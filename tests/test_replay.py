from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

import pytest

from nav2_scenario_runner.replay import (
    MapImage,
    format_replay_html,
    load_map,
    load_replay_scenarios,
)


def _report(scenarios: list[dict]) -> dict:
    return {"runner_version": "0.1.0", "mode": "attach", "scenarios": scenarios}


def _scenario(scenario_id: str, points: list[dict], status: str = "passed", metrics: dict | None = None) -> dict:
    base_metrics = {"trajectory": points}
    if metrics:
        base_metrics.update(metrics)
    return {
        "scenario_id": scenario_id,
        "name": scenario_id,
        "status": status,
        "metrics": base_metrics,
    }


def _line_points() -> list[dict]:
    return [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.5}, {"x": 2.0, "y": 0.0}]


def test_load_replay_scenarios_keeps_only_those_with_trajectories():
    report = _report(
        [
            _scenario("with_traj", _line_points()),
            _scenario("no_traj", [{"x": 0.0, "y": 0.0}]),  # single point -> dropped
            {"scenario_id": "empty", "status": "passed", "metrics": {}},
        ]
    )
    scenarios = load_replay_scenarios(report)
    assert [s.scenario_id for s in scenarios] == ["with_traj"]


def test_load_replay_scenarios_filter():
    report = _report([_scenario("a", _line_points()), _scenario("b", _line_points())])
    scenarios = load_replay_scenarios(report, only={"b"})
    assert [s.scenario_id for s in scenarios] == ["b"]


def test_replay_html_without_map_has_animation():
    html = format_replay_html(load_replay_scenarios(_report([_scenario("a", _line_points())])))
    assert "<title>Nav2 Replay</title>" in html
    assert "<animateMotion" in html
    assert "replay-grid" in html  # blank-grid background when no map
    assert "no map underlay" in html


def test_replay_html_status_colors_path():
    passing = format_replay_html(load_replay_scenarios(_report([_scenario("ok", _line_points(), status="passed")])))
    failing = format_replay_html(load_replay_scenarios(_report([_scenario("bad", _line_points(), status="failed")])))
    assert "#3ad29f" in passing  # pass green path
    assert "#ff6b6b" in failing  # fail red path


def _write_pgm_p5(path: Path, width: int, height: int, fill: int = 200) -> None:
    header = f"P5\n# test map\n{width} {height}\n255\n".encode("ascii")
    path.write_bytes(header + bytes([fill]) * (width * height))


def _write_map_yaml(path: Path, image_name: str, resolution: float = 0.05) -> None:
    path.write_text(
        f"image: {image_name}\nresolution: {resolution}\norigin: [-1.0, -1.0, 0.0]\nnegate: 0\n",
        encoding="utf-8",
    )


def test_load_map_parses_p5_pgm(tmp_path: Path):
    _write_pgm_p5(tmp_path / "map.pgm", 8, 6, fill=128)
    _write_map_yaml(tmp_path / "map.yaml", "map.pgm")
    map_image = load_map(tmp_path / "map.yaml")
    assert (map_image.width, map_image.height) == (8, 6)
    assert map_image.resolution == 0.05
    assert (map_image.origin_x, map_image.origin_y) == (-1.0, -1.0)
    # png_base64 should decode to a valid PNG signature.
    png = base64.b64decode(map_image.png_base64)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_load_map_parses_p2_ascii_pgm(tmp_path: Path):
    width, height = 3, 2
    values = " ".join(["100"] * (width * height))
    (tmp_path / "map.pgm").write_text(f"P2\n{width} {height}\n255\n{values}\n", encoding="utf-8")
    _write_map_yaml(tmp_path / "map.yaml", "map.pgm")
    map_image = load_map(tmp_path / "map.yaml")
    assert (map_image.width, map_image.height) == (3, 2)


def test_png_is_decodable_and_correct_size(tmp_path: Path):
    _write_pgm_p5(tmp_path / "map.pgm", 5, 4, fill=200)
    _write_map_yaml(tmp_path / "map.yaml", "map.pgm")
    map_image = load_map(tmp_path / "map.yaml")
    png = base64.b64decode(map_image.png_base64)
    # IHDR width/height live at bytes 16..24.
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (5, 4)
    # IDAT must inflate without error.
    idat_start = png.index(b"IDAT") + 4
    idat_len = struct.unpack(">I", png[idat_start - 8 : idat_start - 4])[0]
    inflated = zlib.decompress(png[idat_start : idat_start + idat_len])
    assert len(inflated) == height * (width + 1)  # +1 filter byte per row


def test_map_projection_maps_origin_to_bottom_left():
    map_image = MapImage(width=20, height=20, resolution=0.5, origin_x=-5.0, origin_y=-5.0, png_base64="")
    # World origin-x/-y is the bottom-left pixel -> svg (0, height).
    x, y = map_image.project(-5.0, -5.0)
    assert x == pytest.approx(0.0)
    assert y == pytest.approx(20.0)
    # One resolution step right and up.
    x2, y2 = map_image.project(-4.5, -4.5)
    assert x2 == pytest.approx(1.0)
    assert y2 == pytest.approx(19.0)


def test_replay_html_with_map_embeds_image(tmp_path: Path):
    _write_pgm_p5(tmp_path / "map.pgm", 10, 10)
    _write_map_yaml(tmp_path / "map.yaml", "map.pgm")
    map_image = load_map(tmp_path / "map.yaml")
    scenarios = load_replay_scenarios(_report([_scenario("a", _line_points())]))
    html = format_replay_html(scenarios, map_image)
    assert "data:image/png;base64," in html
    assert "image-rendering:pixelated" in html
    assert "m/px" in html


def test_load_map_rejects_missing_image_key(tmp_path: Path):
    (tmp_path / "map.yaml").write_text("resolution: 0.05\norigin: [0,0,0]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing 'image'"):
        load_map(tmp_path / "map.yaml")
