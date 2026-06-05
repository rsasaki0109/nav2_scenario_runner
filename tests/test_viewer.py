from __future__ import annotations

import json

import pytest

from nav2_scenario_runner.evaluate import ConfigEntry
from nav2_scenario_runner.replay import MapImage
from nav2_scenario_runner.viewer import build_viewer_data, format_viewer_html


def _report(scenarios: list[dict]) -> dict:
    return {"runner_version": "0.1.0", "scenarios": scenarios}


def _scenario(sid: str, status: str, metrics: dict) -> dict:
    return {"scenario_id": sid, "name": sid, "status": status, "metrics": metrics}


def _entries() -> list[ConfigEntry]:
    a = _report([
        _scenario("straight", "passed", {
            "travel_time": 10.0, "collision_free": True,
            "trajectory": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.5}, {"x": 2.0, "y": 0.0}],
            "artifact_dir": "x/",
        }),
    ])
    b = _report([
        _scenario("straight", "failed", {
            "travel_time": 14.0, "collision_free": False,
            "trajectory": [[0.0, 0.0], [1.0, -0.5], [2.0, 0.0]],
        }),
    ])
    return [
        ConfigEntry(label="fast", path="fast.json", report=a),
        ConfigEntry(label="slow", path="slow.json", report=b),
    ]


def test_build_viewer_data_shapes():
    data = build_viewer_data(_entries())
    assert data["scenario_ids"] == ["straight"]
    assert [c["label"] for c in data["configs"]] == ["fast", "slow"]
    assert data["map"] is None
    # distinct palette colors per config
    assert data["configs"][0]["color"] != data["configs"][1]["color"]


def test_scalar_metrics_only_and_bool_coercion():
    data = build_viewer_data(_entries())
    fast = data["configs"][0]["scenarios"]["straight"]
    assert fast["metrics"] == {"travel_time": 10.0, "collision_free": 1.0}
    assert "trajectory" not in fast["metrics"]
    assert "artifact_dir" not in fast["metrics"]
    # trajectory preserved separately, normalized to [x, y] pairs
    assert fast["trajectory"][1] == [1.0, 0.5]


def test_dict_and_list_trajectory_forms_both_parse():
    data = build_viewer_data(_entries())
    slow = data["configs"][1]["scenarios"]["straight"]
    assert slow["trajectory"] == [[0.0, 0.0], [1.0, -0.5], [2.0, 0.0]]
    assert slow["status"] == "failed"


def test_build_viewer_data_includes_map():
    map_image = MapImage(width=240, height=180, resolution=0.05, origin_x=-6.0, origin_y=-4.5, png_base64="AAAA")
    data = build_viewer_data(_entries(), map_image)
    assert data["map"]["width"] == 240
    assert data["map"]["origin"] == [-6.0, -4.5]
    assert data["map"]["png"].startswith("data:image/png;base64,")


def test_build_viewer_data_requires_a_config():
    with pytest.raises(ValueError, match="at least one"):
        build_viewer_data([])


def test_format_viewer_html_embeds_parseable_data():
    data = build_viewer_data(_entries())
    html = format_viewer_html(data, title="My Explorer")
    assert "<title>My Explorer</title>" in html
    assert "<canvas" in html
    assert 'id="benchmark-data"' in html
    # The only literal </script> tokens are the two real closing tags.
    assert html.count("</script>") == 2
    # Embedded JSON round-trips after unescaping the "<" guard.
    start = html.index('id="benchmark-data">') + len('id="benchmark-data">')
    end = html.index("</script>", start)
    parsed = json.loads(html[start:end].replace("\\u003c", "<"))
    assert parsed["scenario_ids"] == ["straight"]


def test_format_viewer_html_escapes_script_breakout():
    # A pathological label must not be able to close the data <script>.
    entries = _entries()
    entries[0].report["scenarios"][0]["scenario_id"] = "</script><b>x"
    html = format_viewer_html(build_viewer_data(entries))
    assert "</script><b>x" not in html
    assert html.count("</script>") == 2
