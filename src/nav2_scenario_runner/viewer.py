"""Interactive, self-contained HTML benchmark viewer.

Unlike the static dashboards, the viewer ships the benchmark data *inside* the
page as an embedded JSON blob and renders it with dependency-free vanilla JS:
toggle planner configs, pick a scenario, and scrub/play the robot along each
recorded trajectory over the real map. Everything is one file, so it opens from
``file://`` and from GitHub Pages alike — ideal for sharing a clip on social.
"""

from __future__ import annotations

import json
from typing import Any

from .evaluate import CONFIG_PALETTE, ConfigEntry, MetricDirections
from .replay import MapImage

# Metric keys that are not scalar measurements and should not show in the table.
_NON_METRIC_KEYS = {"trajectory", "artifact_dir", "artifacts"}


def _scalar_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in metrics.items():
        if key in _NON_METRIC_KEYS:
            continue
        if isinstance(value, bool):
            out[key] = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            out[key] = float(value)
    return out


def _trajectory(metrics: dict[str, Any]) -> list[list[float]]:
    raw = metrics.get("trajectory")
    points: list[list[float]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and "x" in item and "y" in item:
                points.append([float(item["x"]), float(item["y"])])
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                points.append([float(item[0]), float(item[1])])
    return points


def build_viewer_data(
    entries: list[ConfigEntry],
    map_image: MapImage | None = None,
    directions: MetricDirections | None = None,
) -> dict[str, Any]:
    """Assemble the embedded data document the viewer page renders."""

    if len(entries) < 1:
        raise ValueError("viewer needs at least one configuration")

    directions = directions or MetricDirections()
    scenario_ids: list[str] = []
    metric_keys: list[str] = []
    configs: list[dict[str, Any]] = []

    for index, entry in enumerate(entries):
        color = CONFIG_PALETTE[index % len(CONFIG_PALETTE)]
        scenarios: dict[str, Any] = {}
        for scenario in entry.report.get("scenarios", []):
            if not isinstance(scenario, dict):
                continue
            sid = str(scenario.get("scenario_id") or scenario.get("name") or "")
            if not sid:
                continue
            if sid not in scenario_ids:
                scenario_ids.append(sid)
            metrics = scenario.get("metrics") or {}
            scalar = _scalar_metrics(metrics)
            for key in scalar:
                if key not in metric_keys:
                    metric_keys.append(key)
            scenarios[sid] = {
                "status": str(scenario.get("status", "unknown")),
                "metrics": scalar,
                "trajectory": _trajectory(metrics),
            }
        configs.append({"label": entry.label, "color": color, "scenarios": scenarios})

    data: dict[str, Any] = {
        "schema": "nav2_scenario_runner.viewer/v1alpha1",
        "scenario_ids": scenario_ids,
        "metrics": metric_keys,
        "lower_is_better": sorted(directions.lower_is_better),
        "higher_is_better": sorted(directions.higher_is_better),
        "configs": configs,
        "map": None,
    }
    if map_image is not None:
        data["map"] = {
            "png": f"data:image/png;base64,{map_image.png_base64}",
            "width": map_image.width,
            "height": map_image.height,
            "resolution": map_image.resolution,
            "origin": [map_image.origin_x, map_image.origin_y],
        }
    return data


def format_viewer_html(data: dict[str, Any], title: str = "Nav2 Benchmark Explorer") -> str:
    # Embed JSON safely: escaping "<" prevents a "</script>" break-out.
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return _PAGE.replace("__TITLE__", title).replace("__DATA__", payload)


# --------------------------------------------------------------------------- #
# Page template (single self-contained file; vanilla JS, no dependencies)
# --------------------------------------------------------------------------- #

_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; font: 15px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0f1115; color: #e6e8ec; }
  header { padding: 18px 22px; border-bottom: 1px solid #232733; }
  h1 { margin: 0; font-size: 20px; }
  .sub { color: #9aa3b2; font-size: 13px; margin-top: 4px; }
  main { display: grid; grid-template-columns: 240px 1fr; gap: 0; min-height: calc(100vh - 64px); }
  aside { padding: 18px 18px 28px; border-right: 1px solid #232733; }
  section { padding: 18px 22px; }
  .panel { margin-bottom: 22px; }
  .panel h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .08em;
              color: #8b94a6; margin: 0 0 10px; }
  label.cfg { display: flex; align-items: center; gap: 8px; padding: 5px 0; cursor: pointer; }
  label.cfg .dot { width: 12px; height: 12px; border-radius: 3px; flex: none; }
  label.cfg.off { opacity: .4; }
  select, button { font: inherit; color: inherit; background: #1a1d26; border: 1px solid #2c313f;
                   border-radius: 6px; padding: 6px 10px; }
  button { cursor: pointer; }
  button:hover, select:hover { border-color: #3a8df0; }
  .stage { position: relative; background: #161a22; border: 1px solid #232733; border-radius: 10px;
           overflow: hidden; }
  canvas { display: block; width: 100%; height: auto; }
  .controls { display: flex; align-items: center; gap: 12px; margin: 14px 0 6px; }
  .controls input[type=range] { flex: 1; accent-color: #3a8df0; }
  .time { font-variant-numeric: tabular-nums; color: #9aa3b2; min-width: 44px; text-align: right; }
  table { border-collapse: collapse; width: 100%; margin-top: 16px; font-size: 14px; }
  th, td { padding: 7px 10px; text-align: right; border-bottom: 1px solid #232733; }
  th:first-child, td:first-child { text-align: left; }
  thead th { color: #8b94a6; font-weight: 600; }
  td.best { font-weight: 700; }
  td.best::after { content: " \2605"; color: #f5c043; }
  .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px;
            vertical-align: baseline; }
  .status-pass { color: #43d17a; }
  .status-fail { color: #f06a6a; }
  footer { padding: 14px 22px; color: #6c7589; font-size: 12px; border-top: 1px solid #232733; }
  a { color: #6fb1ff; }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <div class="sub">Toggle planners, pick a scenario, and scrub the robot along each recorded trajectory.</div>
</header>
<main>
  <aside>
    <div class="panel">
      <h2>Scenario</h2>
      <select id="scenario"></select>
    </div>
    <div class="panel">
      <h2>Planners</h2>
      <div id="configs"></div>
    </div>
  </aside>
  <section>
    <div class="stage"><canvas id="map"></canvas></div>
    <div class="controls">
      <button id="play">&#9654; Play</button>
      <input id="scrub" type="range" min="0" max="1000" value="0">
      <span class="time" id="pct">0%</span>
    </div>
    <table id="metrics"><thead></thead><tbody></tbody></table>
  </section>
</main>
<footer>Generated by <a href="https://github.com/rsasaki0109/nav2_scenario_runner">nav2_scenario_runner</a>.</footer>

<script type="application/json" id="benchmark-data">__DATA__</script>
<script>
(function () {
  "use strict";
  const DATA = JSON.parse(document.getElementById("benchmark-data").textContent);
  const lower = new Set(DATA.lower_is_better || []);
  const higher = new Set(DATA.higher_is_better || []);
  const enabled = new Set(DATA.configs.map(c => c.label));
  let scenarioId = DATA.scenario_ids[0];
  let t = 0;            // scrub position in [0, 1]
  let playing = false;

  const canvas = document.getElementById("map");
  const ctx = canvas.getContext("2d");
  const scrub = document.getElementById("scrub");
  const pct = document.getElementById("pct");
  const playBtn = document.getElementById("play");

  // ---- view transform -----------------------------------------------------
  const MAXW = 760, MAXH = 520;
  let mapImg = null;
  if (DATA.map) { mapImg = new Image(); mapImg.onload = draw; mapImg.src = DATA.map.png; }

  function visibleConfigs() {
    return DATA.configs.filter(c => enabled.has(c.label));
  }

  function tracks() {
    // [{label, color, pts:[[x,y]...]}] for the active scenario among enabled configs
    return visibleConfigs().map(c => {
      const s = c.scenarios[scenarioId];
      return { label: c.label, color: c.color, status: s && s.status,
               pts: (s && s.trajectory) || [] };
    }).filter(tr => tr.pts.length >= 2);
  }

  function transform() {
    if (DATA.map) {
      const m = DATA.map;
      const scale = Math.min(MAXW / m.width, MAXH / m.height, 3);
      const W = Math.round(m.width * scale), H = Math.round(m.height * scale);
      const project = (x, y) => [ ((x - m.origin[0]) / m.resolution) * scale,
                                  (m.height - (y - m.origin[1]) / m.resolution) * scale ];
      return { W, H, project, drawMap: () => { if (mapImg && mapImg.complete) ctx.drawImage(mapImg, 0, 0, W, H); } };
    }
    // No map: fit a bounding box over visible trajectories.
    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    tracks().forEach(tr => tr.pts.forEach(([x, y]) => {
      minx = Math.min(minx, x); miny = Math.min(miny, y);
      maxx = Math.max(maxx, x); maxy = Math.max(maxy, y);
    }));
    if (!isFinite(minx)) { minx = -1; miny = -1; maxx = 1; maxy = 1; }
    const pad = 0.1 * Math.max(maxx - minx, maxy - miny, 1);
    minx -= pad; miny -= pad; maxx += pad; maxy += pad;
    const scale = Math.min(MAXW / (maxx - minx), MAXH / (maxy - miny));
    const W = Math.round((maxx - minx) * scale), H = Math.round((maxy - miny) * scale);
    const project = (x, y) => [ (x - minx) * scale, H - (y - miny) * scale ];
    return { W, H, project, drawMap: () => {} };
  }

  function lerp(pts, u) {
    if (pts.length === 0) return null;
    if (pts.length === 1) return pts[0];
    const f = u * (pts.length - 1);
    const i = Math.min(Math.floor(f), pts.length - 2);
    const r = f - i;
    return [ pts[i][0] + (pts[i + 1][0] - pts[i][0]) * r,
             pts[i][1] + (pts[i + 1][1] - pts[i][1]) * r ];
  }

  function draw() {
    const tf = transform();
    if (canvas.width !== tf.W || canvas.height !== tf.H) { canvas.width = tf.W; canvas.height = tf.H; }
    ctx.clearRect(0, 0, tf.W, tf.H);
    ctx.fillStyle = "#11141b"; ctx.fillRect(0, 0, tf.W, tf.H);
    tf.drawMap();

    tracks().forEach(tr => {
      ctx.lineWidth = 2.5; ctx.strokeStyle = tr.color; ctx.globalAlpha = 0.9;
      ctx.beginPath();
      tr.pts.forEach((p, i) => { const [px, py] = tf.project(p[0], p[1]);
        i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
      ctx.stroke();
      // travelled portion brighter
      ctx.globalAlpha = 1; ctx.lineWidth = 4;
      const upto = Math.max(1, Math.round(t * (tr.pts.length - 1)));
      ctx.beginPath();
      for (let i = 0; i <= upto; i++) { const [px, py] = tf.project(tr.pts[i][0], tr.pts[i][1]);
        i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }
      ctx.stroke();
      // robot marker
      const here = lerp(tr.pts, t);
      if (here) { const [px, py] = tf.project(here[0], here[1]);
        ctx.beginPath(); ctx.arc(px, py, 6, 0, Math.PI * 2);
        ctx.fillStyle = tr.color; ctx.fill();
        ctx.lineWidth = 2; ctx.strokeStyle = "#0f1115"; ctx.stroke(); }
    });
    ctx.globalAlpha = 1;
  }

  // ---- metrics table ------------------------------------------------------
  function renderTable() {
    const cfgs = visibleConfigs();
    const thead = document.querySelector("#metrics thead");
    const tbody = document.querySelector("#metrics tbody");
    thead.innerHTML = "<tr><th>Metric</th>" +
      cfgs.map(c => `<th><span class="swatch" style="background:${c.color}"></span>${esc(c.label)}</th>`).join("") + "</tr>";

    const rows = ["status"].concat(DATA.metrics);
    tbody.innerHTML = rows.map(metric => {
      const cells = cfgs.map(c => {
        const s = c.scenarios[scenarioId];
        if (metric === "status") {
          const st = s ? s.status : "absent";
          const cls = st === "passed" ? "status-pass" : (st === "absent" ? "" : "status-fail");
          return `<td class="${cls}">${esc(st)}</td>`;
        }
        const v = s && s.metrics ? s.metrics[metric] : undefined;
        return { v, raw: (v === undefined || v === null) ? "&mdash;" : fmt(v) };
      });
      if (metric === "status") return `<tr><td>status</td>${cells.join("")}</tr>`;
      // mark best cell for this metric row
      const vals = cells.map(c => c.v).filter(v => typeof v === "number");
      let best = null;
      if (vals.length) best = higher.has(metric) ? Math.max.apply(null, vals)
                                                 : (lower.has(metric) ? Math.min.apply(null, vals) : null);
      const tds = cells.map(c => {
        const isBest = best !== null && typeof c.v === "number" && c.v === best && vals.length > 1;
        return `<td class="${isBest ? "best" : ""}">${c.raw}</td>`;
      }).join("");
      return `<tr><td>${esc(metric)}</td>${tds}</tr>`;
    }).join("");
  }

  // ---- UI wiring ----------------------------------------------------------
  const scenarioSel = document.getElementById("scenario");
  scenarioSel.innerHTML = DATA.scenario_ids.map(id => `<option>${esc(id)}</option>`).join("");
  scenarioSel.onchange = () => { scenarioId = scenarioSel.value; t = 0; scrub.value = 0; pct.textContent = "0%"; refresh(); };

  const cfgBox = document.getElementById("configs");
  cfgBox.innerHTML = DATA.configs.map(c =>
    `<label class="cfg" data-label="${esc(c.label)}"><input type="checkbox" checked>` +
    `<span class="dot" style="background:${c.color}"></span>${esc(c.label)}</label>`).join("");
  cfgBox.querySelectorAll("label.cfg").forEach(el => {
    const label = el.getAttribute("data-label");
    el.querySelector("input").onchange = e => {
      e.target.checked ? enabled.add(label) : enabled.delete(label);
      el.classList.toggle("off", !e.target.checked);
      refresh();
    };
  });

  scrub.oninput = () => { t = scrub.value / 1000; pct.textContent = Math.round(t * 100) + "%"; pause(); draw(); };
  playBtn.onclick = () => playing ? pause() : play();

  let raf = null, last = 0;
  function play() {
    playing = true; playBtn.innerHTML = "&#10073;&#10073; Pause";
    last = performance.now();
    const step = now => {
      if (!playing) return;
      t += (now - last) / 4000; last = now;       // ~4s per loop
      if (t >= 1) t = 0;
      scrub.value = Math.round(t * 1000); pct.textContent = Math.round(t * 100) + "%";
      draw(); raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
  }
  function pause() { playing = false; playBtn.innerHTML = "&#9654; Play"; if (raf) cancelAnimationFrame(raf); }

  function refresh() { renderTable(); draw(); }
  function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  function fmt(v) { return Number.isInteger(v) ? String(v) : v.toFixed(2); }

  refresh();
})();
</script>
</body>
</html>
"""
