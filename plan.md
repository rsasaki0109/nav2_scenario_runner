# Plan: Capture a real **OSS Foxglove** Nav2 visualization GIF

> Status: implemented through Phase 4 (updated 2026-06-12)
> Owner: @rsasaki0109
> Phase 0: **PASS** on `sasaki-pc` — headless Chromium + SwiftShader renders
> Lichtblick 3D with live TF from the Jazzy + gz sim stack (`scripts/spike_foxglove_webgl.sh`).
> Theme: make the README hero and the live site show the *actual robotics
> visualization* — robot, costmaps, planned path, laser — from a real Nav2 +
> Gazebo run, rendered by an **open-source** Foxglove client (no login wall).

---

## 1. Why

The project's whole pitch is "real Nav2 in CI, not toy animations." We already
have:

- a real ROS 2 Jazzy + Nav2 + Gazebo stack that navigates 3 scenarios green
  (`docker/`, `examples/benchmark/`),
- a **Measured** dashboard track publishing real metrics
  (`docs/measured-viewer.html`),
- a README hero GIF (`docs/assets/nav2-scenario-runner-demo.gif`).

But that hero GIF is **not** a robotics visualization — it is a Playwright
recording of the runner's own **HTML report** (see §2). A short clip of an
actual Foxglove 3D scene — the TurtleBot3 driving through `tb3_sandbox`, the
global/local costmaps inflating, the planned path redrawing, the laser scan
sweeping — is far more visceral and immediately reads as "this is real."

The deliberate twist: use the **OSS** Foxglove client, self-hosted, so the
capture is reproducible by anyone with no foxglove.dev account and no paywall.
That doubles as a credibility signal (open stack, open viewer).

## 2. Current state (what exists today)

| Asset | What it really does |
| --- | --- |
| `scripts/record_nav2_foxglove_demo.sh` | **Misnamed.** Launches `nav2_bringup tb3_simulation_launch.py` (ROS *Humble* / Gazebo *Classic* assumptions), runs an attach-mode goal, then records the **generated HTML report** — never Foxglove. |
| `scripts/record_browser_demo.py` | Generic, reusable **URL → GIF** recorder: Playwright screenshots at N fps → `ffmpeg` palette GIF. Already parameterized (`--url`, `--browser`, `--wait-for-selector`, viewport). Docstring even says "such as Foxglove Studio." This is the workhorse we keep. |
| `docs/demo-capture.md` | Documents the HTML-report capture + an "Optional Foxglove Capture" section that points at the **hosted** `app.foxglove.dev` (sign-in gated) — exactly the friction we want to remove. |
| `foxglove_bridge` | Already a known dependency in the demo script (`ros-${ROS_DISTRO}-foxglove-bridge`). This is the ROS↔Foxglove WebSocket server we connect to. |

**Gap:** nothing self-hosts an OSS Foxglove client, loads a Nav2 layout, or
captures the 3D scene. And the working demo path is pinned to Humble/Gazebo
Classic, while our real green stack is **Jazzy + `gz sim`**.

## 3. Target outcome (definition of done)

- `docs/assets/nav2-foxglove-demo.gif`: 8–15 s, ≤ ~3 MB, showing a real Nav2
  goal being navigated in an **OSS Foxglove** 3D view (map + costmaps + robot +
  `/plan` + `/scan`).
- A committed, version-pinned Foxglove **layout** so the panels are identical
  on every capture.
- A one-command orchestrator that brings up the real Jazzy stack, the bridge,
  the OSS viewer, drives one goal, and records — reproducible on `sasaki-pc`.
- README hero swapped (or augmented) to lead with the Foxglove GIF; the old
  HTML-report GIF demoted or kept as a secondary "report" shot.
- `docs/demo-capture.md` rewritten: OSS-first, hosted/login path removed or
  demoted to a footnote.
- Honest provenance note: this is a **local** capture (heavy, WebGL), not a CI
  gate — same rule as the real benchmark (manual + weekly), no synthetic frames.

## 4. Which OSS Foxglove?

Foxglove archived the open-source **Foxglove Studio** (`foxglove/studio`,
MPL-2.0) in 2024 and moved to a closed hosted product. Two OSS routes remain:

1. **Lichtblick** (`lichtblick-suite/lichtblick`, MPL-2.0) — BMW's actively
   maintained fork of Studio. **Primary choice.** Ships a web build and prebuilt
   container images; same panels, same `foxglove-websocket` data source, same
   layout JSON format.
2. **Archived Foxglove Studio** — still builds/runs, but unmaintained. Fallback
   only, for users who specifically want the original.

Decision: **target Lichtblick**, document Studio as a drop-in fallback (the
orchestrator should take the image/URL as an env var so either works).

## 5. Architecture of the capture

```
              ┌──────────────────────────────────────────────┐
              │  real stack (reuse docker/ + examples/benchmark) │
              │  gz sim -r -s tb3_sandbox                       │
              │  tb3_simulation_launch use_simulator:=False     │
              │  → Nav2 (AMCL, costmaps, planner, controller)   │
              └───────────────┬──────────────────────────────┘
                              │ ROS 2 topics (/map /tf /plan /scan /global_costmap …)
                              ▼
                   ros-jazzy-foxglove-bridge   (ws://localhost:8765)
                              │ Foxglove WebSocket protocol
                              ▼
            Lichtblick (OSS) web app, self-hosted  (http://localhost:8080)
              ?ds=foxglove-websocket&ds.url=ws://localhost:8765
              + preloaded layout (3D panel: map, costmaps, robot, plan, scan)
                              │ rendered in Chromium (WebGL)
                              ▼
            scripts/record_browser_demo.py  → PNG frames → ffmpeg → GIF
                              ▲
                              │ during recording:
              nav2_scenario_runner run … --mode attach  (sends ONE goal)
              so the robot is actually moving in-frame
```

Key idea: **time the recording window to the navigation.** Start the goal, then
start the frame loop, so the GIF shows motion (path redraw, robot translating),
not a static scene.

## 6. Phased execution

### Phase 0 — Spike feasibility (½ day, throwaway)
- Pull/run Lichtblick container locally; confirm the web app loads in headless
  Chromium and that the **3D panel renders under software WebGL** (the single
  biggest risk — see §7).
- Manually point it at a bridge from the already-green docker stack and eyeball
  one frame screenshot.
- **Exit criterion:** one non-black PNG showing the robot + map. If WebGL is
  hopeless headless, jump to the §8 fallback ladder *before* building anything.

**Result (2026-06-09):** PASS via `scripts/spike_foxglove_webgl.sh`.
- Lichtblick `ghcr.io/lichtblick-suite/lichtblick:latest` loads headless with
  `--software-webgl` (`mean_rgb≈236`, WebGL renderer `WebKit WebGL`).
- Real Jazzy stack + `foxglove_bridge` on `:8765`; URL auto-connect works:
  `http://127.0.0.1:8080/?ds=foxglove-websocket&ds.url=ws://127.0.0.1:8765`.
- Default Lichtblick layout shows 3D TF frames (`base_link`, `scan`, …) on the
  grid — **map/costmaps not yet configured** (Phase 1 layout). Docker
  `ENTRYPOINT` is `bash -lc`; spike must use `--entrypoint /bin/bash`.
- Spike frame saved under `reports/demo-capture/spike-foxglove-frame.png`
  (gitignored).

### Phase 1 — Layout + connection, deterministic
- Author and **commit** `docs/assets/foxglove-nav2-layout.json`:
  - 3D panel: `/map` (occupancy), `/global_costmap/costmap`,
    `/local_costmap/costmap`, robot from `/tf` + URDF, `/plan` path,
    `/scan` laser, the goal pose marker. Sensible camera (top-down-ish, framed
    on the aisle the scenarios use, y≈0.5).
  - Optional: a small "Plot" panel for live `travel_time`/velocity, or a 2D
    "Map" panel as a WebGL-free safety net.
- Decide the **auto-load mechanism**: URL params for the data source +
  layout-by-id, or mount the layout file into the container's layouts dir and
  select it via URL. Whichever is deterministic headless.

### Phase 2 — Orchestrator script (replace the Humble path)
- New `scripts/record_nav2_foxglove_demo.sh` (or a v2) that:
  1. reuses the **Jazzy + `gz sim`** bring-up from `docker/run_benchmark.sh`
     (bare `gz sim -r -s` + `tb3_simulation_launch use_simulator:=False`,
     `set_initial_pose`), under an isolated `ROS_DOMAIN_ID`/`GZ_PARTITION`;
  2. launches `foxglove_bridge` (`port:=8765`);
  3. starts the **Lichtblick** container served on `:8080` with the committed
     layout (image/URL overridable via env for the Studio fallback);
  4. waits for `/map`, `/tf`, `/plan` readiness (reuse the runner's
     `--wait-for-navigation-data` style check);
  5. kicks off `nav2_scenario_runner run … --mode attach` to send one goal;
  6. runs `record_browser_demo.py` against `http://localhost:8080/?ds=…`,
     timed to the goal so motion is in-frame;
  7. cleans up all PIDs/containers (extend the existing trap/cleanup).
- Run everything inside the existing benchmark **docker image** (it already has
  Jazzy + Nav2 + gz). Decide: Lichtblick as a sibling container on a shared
  network, or add it to a compose file. Lean toward a tiny
  `docker/foxglove-demo.compose.yml`.

### Phase 3 — Capture, tune, encode
- Extend `record_browser_demo.py` with launch args for **software WebGL**
  (`--use-gl=angle --use-angle=swiftshader` / `--enable-unsafe-swiftshader`,
  `--ignore-gpu-blocklist`) behind a flag, so 3D renders headless.
- Tune duration/fps/viewport for a crisp ≤3 MB GIF (start 12 s @ 8 fps, 960 px).
- Use `--wait-for-selector` on a Foxglove panel/canvas element so capture starts
  only after the scene is live.

### Phase 4 — Wire into the project
- Swap README hero to `nav2-foxglove-demo.gif` (keep the HTML-report GIF as a
  secondary "structured report" visual; keep the interactive explorer link).
- Optionally publish the GIF on the Pages site near the **Measured** section
  ("this is the real scene behind the numbers").
- Rewrite `docs/demo-capture.md`: OSS-first, the new one-command flow, the WebGL
  caveat + fallback ladder; demote the hosted-login path.
- `CHANGELOG.md` entry. Pin the Lichtblick image tag for reproducibility.

### Phase 5 — Optional automation (stretch)
- A manual `workflow_dispatch` job that produces the GIF as an artifact (not a
  gate) so it can be regenerated without a local machine — *only if* headless
  WebGL proves reliable on GitHub runners (it may not; keep local-first).

## 7. Risks & mitigations

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| **Headless Chromium WebGL** renders the 3D panel black/garbled (swiftshader). | High — *the* risk | Phase 0 spike gates everything. Flags in §6.3. If it fails → §8 ladder. |
| Layout doesn't auto-load deterministically headless. | Med | Commit the layout; prefer mounted-file + URL-by-id over hand-built panels; `--wait-for-selector` on the canvas. |
| Lichtblick image/version drift changes URL params or layout schema. | Med | Pin the image tag; keep the layout JSON in-repo; env-overridable image/URL. |
| Robot not moving during the captured window (static, dull GIF). | Med | Sequence goal → record; verify `/plan` updates land inside the window. |
| GIF too large for README. | Low | 960 px, bayer-dither palette (already in the encoder), cap duration/fps. |
| Heavy/slow; flaky in CI. | Low (we keep it local) | Local-first, manual workflow only as stretch; never a required check. |

## 8. Fallback ladder (if headless WebGL 3D won't cooperate)

1. **Lichtblick web + headless Chromium + swiftshader** (primary).
2. **Lichtblick web + `xvfb` + Chromium with real GL** (virtual display, capture
   via Playwright as today, or `ffmpeg x11grab`).
3. **WebGL-free panels**: Foxglove **Map** (2D) + **Plot** + **Image** panels —
   still a genuine Foxglove view of the real run, no 3D canvas. Less flashy, very
   robust.
4. **Lichtblick desktop (Electron) under `xvfb`** + `ffmpeg x11grab` — full
   fidelity, captured as a desktop window instead of a browser page.

Pick the highest rung that yields a clean, real capture; document which one
shipped.

## 9. Deliverables checklist

- [x] Phase 0 spike: non-black Foxglove 3D frame from the real stack.
- [x] `docs/assets/foxglove-nav2-layout.json` (committed, pinned panels).
- [x] `docker/foxglove-demo.compose.yml` (or equivalent) for the OSS viewer.
- [x] Rewritten `scripts/record_nav2_foxglove_demo.sh` (Jazzy + gz sim + bridge +
      Lichtblick + timed goal + capture).
- [x] `record_browser_demo.py`: software-WebGL launch-arg flag.
- [x] `docs/assets/nav2-foxglove-demo.gif` (≤3 MB, 8–15 s, real motion).
- [x] README hero swap; HTML-report GIF demoted to secondary.
- [x] `docs/demo-capture.md` rewritten OSS-first.
- [x] `CHANGELOG.md` entry; image tag pinned.
- [ ] (Stretch) manual `workflow_dispatch` artifact job.

## 10. Acceptance criteria

- A reviewer on `sasaki-pc` can run **one command** and regenerate the GIF.
- The GIF unmistakably shows a **Foxglove (OSS)** UI and a **moving** TurtleBot3
  over the real `tb3_sandbox` map with costmaps + path.
- No foxglove.dev account, no synthetic/mock frames, no toy animation.
- README + Pages updated; docs match the shipped fallback rung.

## 11. Open questions

- Lichtblick **web** (browser-capturable, primary) vs **desktop** (needs xvfb)
  — confirm in Phase 0.
- Auto-load layout via **URL** vs **mounted file** — pick the deterministic one.
- Capture the **demo** scenario or a **measured** benchmark scenario (tie the
  GIF to the published numbers)? Leaning measured for narrative coherence.
- One hero GIF, or **two** (synthetic explorer GIF for "compare planners" +
  Foxglove GIF for "real scene")?

---
---

# Part 2: Post-demo development tracks

> Status: draft / idea backlog (added 2026-06-12)
> Owner: @rsasaki0109
> Scope: the next product-level features after the Foxglove demo (Part 1)
> ships. Ordered by recommended priority. Each track is independently
> shippable; dependencies are called out explicitly.

## Overview & recommended order

| Track | One-liner | Playwright analogy | Depends on | Size |
| --- | --- | --- | --- | --- |
| **B** | Trace-on-failure: auto-record MCAP, "open in Lichtblick" from the report | `trace: 'retain-on-failure'` + Trace Viewer | Part 1 (layout, compose, bridge) | M |
| **C** | v0.4-lite: declarative dynamic-obstacle events + replan/recovery metrics | `page.route()` fault injection | — | M–L |
| **D** | Scenario recording: subscribe to goals/teleop, emit YAML | `playwright codegen` | — | S–M |
| **E** | Flake management pulled forward: retries + `flaky_pass` classification | `retries` + flaky reporting | — | S |
| **F** | pytest plugin: scenarios as collected pytest items | `pytest-playwright` | — | S |

Recommended sequence: **B → C → E → D → F**. B is first because it converts
the Part 1 demo infrastructure (committed layout, compose file, bridge
bring-up) into a *product feature* the same week it lands — highest reuse,
highest narrative payoff ("CI failure → replay the 3D scene locally"). C is
the roadmap's own v0.4 and the biggest differentiation vs. static smoke
tests. E is small and removes the #1 adoption objection (sim flakiness in
CI). D and F are adoption/DX plays that can be slotted in whenever a breather
is needed — both are small and demo well.

---

## Track B — Trace-on-failure (MCAP capture + "open in Lichtblick")

### B.1 Why

Playwright's killer debugging feature is not the report — it is the **trace**:
when a test fails in CI, you download one artifact and replay the entire run
locally in a purpose-built viewer. Nav2 failures are *exactly* the kind of
failure where a pass/fail line is useless ("goal not reached in 120 s" — but
*why*? Costmap inflation? AMCL divergence? Oscillating controller?). The data
needed to answer that already flows through the stack during every run; we
just drop it on the floor today.

Part 1 builds everything needed to *view* such a trace: a self-hosted OSS
Lichtblick, a committed Nav2 layout (`docs/assets/foxglove-nav2-layout.json`),
and a compose file. Track B makes the runner *produce* the trace and wires the
two together. The demo GIF infrastructure stops being decoration and becomes
the debugging story.

### B.2 Current state / building blocks

- `reporting.py` / `report_view.py`: HTML report with per-scenario sections —
  the natural place for an "open trace" link.
- `runner.py` / `execution.py`: own the scenario lifecycle (setup → goal →
  assertions → teardown), so they know exactly when to start/stop a recorder
  and whether the outcome was pass/fail.
- The benchmark docker image already has the full Jazzy stack; `ros2 bag
  record` with the MCAP storage plugin (`ros-jazzy-rosbag2-storage-mcap`) is
  either present or a one-line apt addition.
- Lichtblick opens local MCAP files natively (drag-and-drop or
  `?ds=file`-style sources), and the Part 1 layout applies to a file source
  exactly as it does to a live websocket source.

### B.3 Design sketch

```
scenario start
  └─ spawn recorder:  ros2 bag record -s mcap -o <artifact_dir>/<scenario>/trace \
        /tf /tf_static /map /scan /odom /plan /cmd_vel \
        /global_costmap/costmap /local_costmap/costmap \
        /amcl_pose /goal_pose /behavior_tree_log [+ user-extendable list]
scenario end
  ├─ stop recorder (SIGINT, wait for bag finalize)
  ├─ outcome == pass  → delete trace            (default: retain-on-failure)
  └─ outcome == fail  → keep trace, register path in results.json
report generation
  └─ failed scenario section gets:
       • trace file size + topic/message counts (sanity signal)
       • "Open in Lichtblick" instructions: one command
         (docker compose -f docker/foxglove-demo.compose.yml up viewer)
         + drag the .mcap in, or a `nav2_scenario_runner trace <path>` helper
         that starts the viewer with the committed layout and the file mounted
```

Scenario-schema surface (small, additive):

```yaml
trace:
  mode: retain-on-failure   # off | on | retain-on-failure (default)
  topics: [...]             # optional extension of the default set
  max_size_mb: 200          # safety cap; recorder stopped + warning if hit
```

CLI surface:

- `--trace {off,on,retain-on-failure}` (overrides YAML; default
  `retain-on-failure` when recording is possible, `off` in `--dry-run`).
- `nav2_scenario_runner trace <file.mcap>`: convenience launcher — starts the
  Lichtblick container with the committed layout and prints the URL. This is
  the "Playwright trace viewer" moment and should be one command.

### B.4 Phases

1. **Recorder lifecycle** — start/stop `ros2 bag record` around scenario
   execution in `--mode attach` and `--mode gazebo-sim --execute-nav2`;
   retain-on-failure semantics; size cap; results.json gets a `trace` field
   per scenario. Unit-test the lifecycle with a fake recorder process.
2. **Report integration** — HTML report and GitHub summary link/mention the
   trace; JUnit attachment-style note. CI workflow template uploads
   `<artifact_dir>/**/trace*` as an artifact only when the job failed.
3. **Viewer hand-off** — `nav2_scenario_runner trace` subcommand reusing the
   Part 1 compose file + layout; docs page "Debugging a failed run" with a
   30-second walkthrough (download artifact → one command → scrub the 3D
   scene).
4. **Polish** — default topic set tuned so a typical failed scenario trace is
   ≤ ~50 MB; document how to add `/camera/*` etc. and the cost of doing so.

### B.5 Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Bag recorder adds CPU load and perturbs timing-sensitive scenarios. | Default topic set excludes images/pointclouds; document the perturbation honestly; `--trace off` escape hatch; measure overhead once on `sasaki-pc` and put the number in the docs. |
| Trace too large for GitHub artifacts. | `max_size_mb` cap + curated default topics; costmaps are the big ones — record them throttled (`/global_costmap/costmap` is latched/slow anyway). |
| Recorder not finalized on crash → corrupt MCAP. | SIGINT + bounded wait + finalize check; mark trace `incomplete: true` in results.json rather than dropping it. |
| Lichtblick file-source UX differs across versions. | Image tag already pinned by Part 1; `trace` subcommand owns the invocation details so users never hand-assemble URLs. |

### B.6 Deliverables

- [ ] Recorder lifecycle in runner (`trace:` schema field + `--trace` flag).
- [ ] results.json / HTML report / GH summary trace integration.
- [ ] CI template: upload traces on failure.
- [ ] `nav2_scenario_runner trace <file.mcap>` viewer launcher.
- [ ] `docs/debugging-failed-runs.md` + README "Debugging" subsection.
- [ ] CHANGELOG entry.

### B.7 Acceptance criteria

- A scenario forced to fail on `sasaki-pc` leaves exactly one `.mcap` behind;
  a passing run leaves none (default mode).
- From a fresh shell: `nav2_scenario_runner trace out/.../trace.mcap` →
  browser shows the committed Nav2 layout replaying the failed run, robot +
  costmaps + plan visible, scrubbing works.
- The weekly Measured CI job uploads traces for any failed scenario without
  pushing the artifact budget past ~100 MB.

---

## Track C — v0.4-lite: declarative dynamic-obstacle events

### C.1 Why

This is the roadmap's own v0.4 ("a scenario can spawn an obstacle during
navigation and measure replanning or recovery changes") and the single
biggest differentiator over "send a goal, assert it arrived" smoke tests.
Static-world tests barely exercise Nav2; the interesting regressions are in
costmap updates, replanning latency, and recovery behavior — all of which
only show up when the world changes mid-run.

**Deliberate scope cut ("-lite"):** the full v0.4 (generic event bus,
`on_event`, `parallel`, robot profiles) is a large DSL commitment that risks
freezing the wrong abstractions. The 80 % value is a *declarative timeline of
world mutations* + two new metrics. Ship that; let the event bus be informed
by real usage before designing it.

### C.2 Design sketch

Schema (additive, `v1alpha1`-compatible):

```yaml
world_events:
  - at: { progress: 0.4 }        # or { time_s: 12.0 } — exactly one
    spawn_obstacle:
      name: surprise_box
      sdf: builtin://box_0.5     # built-in primitives; user SDF path allowed
      pose: { x: 1.2, y: 0.5, yaw: 0.0 }
  - at: { time_s: 30.0 }
    remove_obstacle: { name: surprise_box }

metrics:
  - replan_count                  # new
  - recovery_count                # exists per roadmap v0.3 — verify coverage
assertions:
  - expect_goal_reached: { timeout_s: 180 }
  - expect_metric: { name: replan_count, op: ">=", value: 1 }
```

Mechanics:

- **Triggering:** a small monitor task subscribes to `/plan` + progress along
  it (or sim time for `time_s`) and fires events when thresholds cross.
  `progress` is fraction of the *initial* planned path traversed — defined
  precisely in docs since the path changes after replans.
- **Spawning:** `gz service /world/<w>/create` (Jazzy/gz sim path, matches the
  green stack). The runner already shells out to `gz` for `--reset-world`, so
  the plumbing pattern exists.
- **Metrics:** `replan_count` from distinct `/plan` publications after the
  first (debounced — controller-server replans on a timer in some configs;
  count *geometry changes* above a threshold, not raw messages).
  `recovery_count` from `/behavior_tree_log` recovery-node activations.
- **Benchmark tie-in:** add one obstacle scenario to `examples/benchmark/` and
  the Measured weekly run → the public dashboard gets a "with dynamic
  obstacle" row, which strengthens the published numbers' story.

### C.3 Phases

1. Schema + lint for `world_events` (validation: unique names, exactly one
   `at` key, spawn-before-remove ordering).
2. Event monitor + gz spawn/remove execution in `gazebo-sim` mode; dry-run
   prints the timeline.
3. `replan_count` metric (debounced geometry-diff) + recovery-count
   verification; both into results.json/report/compare.
4. Example scenario (`examples/turtlebot3_gazebo/dynamic_obstacle.yaml`) +
   one benchmark/Measured scenario + docs.
5. Timeline artifact (when each event fired, in sim time) appended to the
   per-scenario report — pairs beautifully with a Track B trace.

### C.4 Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Spawn timing is nondeterministic relative to robot motion → flaky asserts. | `progress`-based triggers (robot-relative, not wall-clock) as the recommended form; docs steer away from `time_s` for assertions. |
| `replan_count` is config-dependent noise (timer-based replanning). | Debounce by path-geometry delta; document the threshold; assert with `>=`/ranges, never exact counts. |
| gz service API drift across gz sim versions. | Already pinned by the benchmark docker image; keep all gz calls in one adapter module (`backends/`). |
| Scope creep toward the full event bus. | Hard rule for this track: events are *world mutations on a timeline*, nothing reacts to anything. `on_event` stays in v0.4-full. |

### C.5 Acceptance criteria

- A 15-line YAML spawns a box at 40 % progress; Nav2 replans around it; the
  run is green and `replan_count >= 1` is asserted — repeatedly (10/10) on
  `sasaki-pc`.
- The Measured dashboard publishes at least one dynamic-obstacle scenario
  weekly.
- Removing the obstacle event from the YAML flips `replan_count` to 0 on the
  same map (i.e., the metric measures the event, not background noise).

---

## Track D — Scenario recording (`codegen` analogue)

### D.1 Why

`playwright codegen` is the feature that makes the first five minutes magical:
you *do* the thing once, and the test writes itself. The runner's pitch
("Playwright DX for Nav2") makes this an expected verb. For Nav2 the
equivalent interaction already exists: an operator clicking **2D Pose
Estimate** and **Nav2 Goal** in RViz (or the Foxglove equivalents publishing
to the same topics). Those clicks are just messages — recording them is cheap.

### D.2 Design sketch

```
nav2_scenario_runner record --out scenarios/recorded.yaml [--profile tb3]
  subscribes:  /initialpose          → set_initial_pose step
               /goal_pose            → send_goal step (+ expect_goal_reached)
               NavigateToPose action goal topic (covers RViz default flow)
  watches:     goal result           → fills a measured timeout_s hint
                                       (actual travel time × safety factor)
  on Ctrl-C:   writes YAML, prints `lint` + `run` next-step commands
```

- Output is deliberately *plain v1alpha1 YAML* — the value is a correct,
  runnable starting point, not a high-fidelity replay. Waypoint sequences
  (multiple goals) become sequential `send_goal` steps.
- `--annotate` (stretch): also snapshot current planner/controller params into
  a comment block, so the recorded scenario documents the config it was
  recorded under.
- Teleop capture (`/cmd_vel` → `follow_path`-ish steps) is explicitly **out of
  scope** — it records executions, not intents, and produces brittle
  scenarios. Goals are intents; record those.

### D.3 Phases

1. MVP: subscribe `/initialpose` + `/goal_pose` + NavigateToPose action goals,
   emit YAML on Ctrl-C, round-trip through `lint` clean.
2. Timeout calibration from observed travel time; multi-goal sequences.
3. Docs + a 20-second GIF for the README (click in RViz → YAML appears) —
   this demos extremely well and is cheap to capture with Part 1 tooling.

### D.4 Risks / notes

- RViz's "Nav2 Goal" tool sends an **action goal**, not a `/goal_pose` topic
  message, depending on config — MVP must handle both paths or it will look
  broken in the most common setup. Verify on the real stack first.
- Keep the recorder read-only (pure subscriber) so it can run against any live
  system, including a real robot, with zero risk.

### D.5 Acceptance criteria

- Fresh terminal: `record`, click initial pose + one goal in RViz, Ctrl-C →
  the emitted YAML passes `lint` and goes green under `run --mode attach`
  without hand-editing.

---

## Track E — Flake management pulled forward (v0.7 slice)

### E.1 Why

The #1 objection to putting simulation in CI is "it'll be flaky and the team
will start ignoring red." Playwright answered this with built-in `retries` +
honest **flaky** classification (pass-on-retry is reported as flaky, not
quietly green). The roadmap has this at v0.7, but it is small, independent,
and removes an *adoption* blocker — every week it ships earlier, every CI
template generated by `init` is more trustworthy. Pull forward just the
retry/classification slice; statistical baselines stay in v0.7.

### E.2 Design sketch

```yaml
# scenario or runner config
retries: 2            # default 0 — opt-in, no silent behavior change
```

- Outcome taxonomy in results.json/report/JUnit: `pass`, **`flaky_pass`**
  (failed ≥1 attempt, then passed), `fail` (all attempts failed). Exit code:
  flaky_pass is green by default; `--fail-on-flaky` makes it red (mirrors
  Playwright).
- Per-attempt records kept (durations, failure reason of failed attempts) —
  and each failed attempt keeps its **Track B trace**, which is where the
  combination gets genuinely powerful: flaky tests are precisely the ones
  whose failures you can never reproduce live.
- Retry hygiene in sim modes: re-run includes `--reset-world` / re-set initial
  pose so attempt 2 isn't poisoned by attempt 1's end state. This is the only
  subtle part; in `attach` mode, document that retries assume the user's
  stack is re-entrant.
- JUnit: standard flaky representation (rerun elements) so GitHub/Jenkins UIs
  show it natively; `pr_comment.py` gains a "⚠ N flaky" line.
- `compare`/`history`: flaky counts tracked over time → the existing badge
  set could gain a flake-rate badge later (not in scope).

### E.3 Phases

1. Retry loop + classification + exit-code policy in `runner.py`/`evaluate.py`
   (pure-Python, fully unit-testable with simulated outcomes).
2. Reporting surfaces: results.json schema bump (additive), HTML, JUnit
   reruns, GH summary, PR comment.
3. World-reset hygiene between attempts in `gazebo-sim` mode; docs on
   attach-mode caveats.

### E.4 Acceptance criteria

- A scenario scripted to fail once then pass is reported `flaky_pass`, job
  green; with `--fail-on-flaky`, job red — verified by unit tests.
- JUnit output renders the retry visibly in the GitHub Actions UI.
- No behavior change whatsoever when `retries` is unset.

---

## Track F — pytest plugin

### F.1 Why

Most ROS 2 Python repos already run pytest in CI (often via `colcon test`).
A plugin that makes YAML scenarios appear as collected pytest items means
adoption is *one line in an existing pipeline*, not a new CI job — the
cheapest possible on-ramp. `pytest-playwright` proved this distribution
strategy.

### F.2 Design sketch

- New (sub)package `pytest-nav2-scenario-runner` exposing a pytest11 entry
  point; keep it in-repo (same version, extras: `pip install
  nav2_scenario_runner[pytest]`).
- Collection: `--nav2-scenarios <dir>` (or `nav2_scenarios = scenarios/` in
  ini config) → each scenario file becomes a test item named by scenario id;
  tags map to pytest marks (`-m smoke` just works).
- Execution: items call the existing runner API in-process (`runner.py` is
  already importable — no subprocess); per-item artifacts (report fragment,
  Track B trace path) attach via `record_property` so they appear in JUnit.
- Mode/config via ini/CLI passthrough (`--nav2-mode attach`, etc.). Flaky
  classification (Track E) maps onto `pytest-rerunfailures`-compatible
  reporting if present, otherwise onto our own outcome.
- Honest scope: this is a *collection/reporting adapter*, ~300 lines. It must
  not grow scenario logic of its own.

### F.3 Phases

1. Collector + runner-API invocation + pass/fail mapping; works under plain
   `pytest` against `--dry-run` scenarios (CI-testable without ROS).
2. Marks-from-tags, ini config, artifact attachment.
3. Docs: "Add Nav2 scenario tests to an existing colcon/pytest repo in 5
   minutes" — this page *is* the feature.

### F.4 Acceptance criteria

- In a scratch repo: `pip install -e .[pytest]`, add `nav2_scenarios =`
  to `pytest.ini`, run `pytest -m smoke --nav2-mode dry-run` → scenarios
  collected, named, and green, with zero imports written by the user.
- `colcon test` picks the items up unmodified.

---

## Cross-track notes

- **Shared thread:** B, C, E all enrich `results.json` — sequence their schema
  changes additively and bump the report schema once per release, not per
  track (the roadmap's v0.9 freeze gets easier).
- **Compounding demo:** after B + C land, the flagship docs walkthrough writes
  itself: *dynamic obstacle appears → Nav2 fails → CI uploads trace → one
  command replays the exact 3D scene*. That sequence is the product thesis in
  30 seconds and should become a Pages-site section (and possibly the second
  GIF from Part 1's open question §11).
- **Out of scope (deliberately):** Nav2-upstream benchmark-bot outreach is
  excluded from this plan per decision on 2026-06-12; revisit after B/C are
  public and the Measured track has more weeks of history.
