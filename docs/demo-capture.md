# Demo Capture

Use a real Nav2/Gazebo Sim run for the README demo. Do not commit synthetic or
toy recordings.

The default capture path is OSS-first:

- Nav2 + Gazebo Sim run in the local Jazzy Docker image.
- `foxglove_bridge` publishes the ROS graph over Foxglove WebSocket.
- Lichtblick, the open-source Foxglove Studio fork, renders the scene locally.
- Playwright records the browser with software WebGL enabled.

## Requirements

- Docker
- `ffmpeg`
- `python3 -m pip install playwright`
- `python3 -m playwright install chromium`
- The benchmark image built locally:

```bash
docker build -t nav2-scenario-runner:jazzy-gazebo -f docker/Dockerfile .
```

## One-Command OSS Capture

Run from the repository root:

```bash
scripts/record_nav2_foxglove_demo.sh
```

The script starts:

- the pinned Lichtblick container on `http://127.0.0.1:8080`
- the real Jazzy + `gz sim` `tb3_sandbox` stack in Docker
- `foxglove_bridge` on `ws://127.0.0.1:8765`
- one attach-mode `nav2_scenario_runner` goal timed to the recording window
- the Playwright GIF recorder against the Lichtblick 3D canvas

Default output:

```text
docs/assets/nav2-foxglove-demo.gif
```

Logs and generated reports are written under:

```text
reports/demo-capture/
```

Useful overrides:

```bash
OUTPUT=/tmp/nav2-foxglove.gif DURATION=10 FPS=8 scripts/record_nav2_foxglove_demo.sh
ROS_DOMAIN_ID=72 GZ_PARTITION=foxglove_demo_72 scripts/record_nav2_foxglove_demo.sh
LICHTBLICK_PORT=8081 BRIDGE_PORT=8766 scripts/record_nav2_foxglove_demo.sh
GOAL_X=0.7 GOAL_Y=0.5 GOAL_YAW=0.0 GOAL_NAME=ahead scripts/record_nav2_foxglove_demo.sh
```

The committed layout lives at:

```text
docs/assets/foxglove-nav2-layout.json
```

It is mounted into the Lichtblick container so repeated captures use the same 3D
panel, camera, map, costmaps, plan, laser scan, and robot TF settings.

## WebGL Notes

`scripts/record_browser_demo.py` accepts `--software-webgl`, which launches
Chromium with SwiftShader flags:

```bash
python3 scripts/record_browser_demo.py \
  --url "http://127.0.0.1:8080/?ds=foxglove-websocket&ds.url=ws%3A%2F%2F127.0.0.1%3A8765" \
  --output docs/assets/nav2-foxglove-demo.gif \
  --duration 12 \
  --fps 8 \
  --crop-left 240 \
  --wait-for-selector canvas \
  --click 228,56 \
  --software-webgl
```

Keep the GIF short, usually 8-15 seconds and about 3 MB or less for README use.
This capture is intentionally local/manual because it depends on Docker,
Gazebo, WebGL, and browser timing. It should not become a required CI gate.

## Fallbacks

If headless Chromium renders a black 3D panel, use the highest working fallback:

1. Lichtblick web + Chromium + SwiftShader (`--software-webgl`).
2. Lichtblick web under `xvfb` with Chromium.
3. Lichtblick Map/Plot/Image panels without 3D.
4. Lichtblick desktop under `xvfb` captured with `ffmpeg x11grab`.

Archived Foxglove Studio can use the same bridge URL and layout format for
manual experiments, but the reproducible project path is the pinned Lichtblick
container. No foxglove.dev account is required.
