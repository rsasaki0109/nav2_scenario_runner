# Demo Capture

Use a real Nav2/Gazebo/Foxglove run for the README demo. Do not commit synthetic or toy recordings.

The repository includes a Playwright-based browser recorder:

```bash
python3 scripts/record_browser_demo.py \
  --url http://localhost:8080 \
  --output docs/assets/nav2-scenario-runner-demo.gif \
  --duration 12 \
  --fps 8 \
  --width 1440 \
  --height 900
```

## Requirements

- A real browser target, for example Foxglove Studio web, already connected to a Nav2/Gazebo run.
- `python3 -m pip install playwright`
- `python3 -m playwright install chromium`
- `ffmpeg`
- For the bundled Nav2 TurtleBot3 demo capture script:
  - ROS 2 Humble
  - `nav2_bringup`
  - `foxglove_bridge`
  - Gazebo Classic `gzserver`
  - `gazebo_ros`

On Ubuntu 22.04 with ROS 2 Humble, the missing demo packages are usually:

```bash
sudo apt-get update
sudo apt-get install -y gazebo ros-humble-gazebo-ros-pkgs ros-humble-foxglove-bridge
```

## One-Command Nav2/Foxglove Demo Capture

After the packages above are installed, run:

```bash
scripts/record_nav2_foxglove_demo.sh
```

The script starts:

- `nav2_bringup`'s TurtleBot3 simulation in headless Gazebo Classic
- `foxglove_bridge` on `ws://localhost:8765`
- the Playwright browser recorder
- a temporary `nav2_scenario_runner --mode attach` scenario that sends a short real Nav2 goal

Default output:

```text
docs/assets/nav2-scenario-runner-demo.gif
```

Logs and generated reports are written under:

```text
reports/demo-capture/
```

Useful overrides:

```bash
OUTPUT=/tmp/demo.gif DURATION=20 FPS=8 scripts/record_nav2_foxglove_demo.sh
```

## Recommended README Demo

Record the dynamic obstacle scenario, not a dry-run or mock animation:

1. Start the real Nav2/Gazebo scenario stack.
2. Open Foxglove Studio in a browser and connect it to the robot/simulation data.
3. Arrange panels so the viewer can see the map, robot pose, planned path, and obstacle movement.
4. Run `nav2_scenario_runner` for `examples/turtlebot3_gazebo/dynamic_obstacle.yaml`.
5. Capture the Foxglove browser window with `scripts/record_browser_demo.py`.
6. Keep the GIF short, ideally 8-15 seconds, and under a few MB when possible.

Once the GIF exists, add this near the top of `README.md`:

```md
<p align="center">
  <img src="docs/assets/nav2-scenario-runner-demo.gif"
       alt="nav2_scenario_runner running a Nav2 dynamic obstacle scenario and generating reports"
       width="900">
</p>
```

## Notes

- Playwright records browser content. It will not capture desktop RViz/Gazebo windows directly.
- For desktop GUI capture, use a native screen recorder and keep the same "real run only" rule.
- If Foxglove is served on another port, pass that URL to `--url`.
- Use `--wait-for-selector` when the target page needs a specific panel to finish loading before capture starts.
