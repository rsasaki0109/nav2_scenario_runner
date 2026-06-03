# Demo Capture

Use a real Nav2/Gazebo run for the README demo. Do not commit synthetic or toy recordings.

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

- A real browser target, for example a generated `nav2_scenario_runner` HTML report or a logged-in Foxglove Studio web session connected to a Nav2/Gazebo run.
- `python3 -m pip install playwright`
- `python3 -m playwright install chromium`
- `ffmpeg`
- For the bundled Nav2 TurtleBot3 demo capture script:
  - ROS 2 Humble
  - Gazebo Classic setup at `/usr/share/gazebo/setup.sh`
  - `nav2_bringup`
  - Gazebo Classic `gzserver`
  - `gazebo_ros`
  - `turtlebot3_gazebo`
  - `turtlebot3_description`

On Ubuntu 22.04 with ROS 2 Humble, the missing demo packages are usually:

```bash
sudo apt-get update
sudo apt-get install -y gazebo ros-humble-gazebo-ros-pkgs ros-humble-turtlebot3-gazebo ros-humble-turtlebot3-description
```

## One-Command Nav2 Demo Capture

After the packages above are installed, run:

```bash
scripts/record_nav2_foxglove_demo.sh
```

The script starts:

- `nav2_bringup`'s TurtleBot3 simulation in headless Gazebo Classic
- a temporary `nav2_scenario_runner --mode attach` scenario that sends a short real Nav2 goal
- the Playwright browser recorder against the generated HTML report

By default the script runs in `ROS_DOMAIN_ID=42` to avoid mixing with any existing ROS graph on the machine. Override it when needed:

```bash
ROS_DOMAIN_ID=43 scripts/record_nav2_foxglove_demo.sh
```

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

## Optional Foxglove Capture

Foxglove Studio web may require sign-in. If you have a logged-in browser target connected to `foxglove_bridge`, record that URL explicitly:

```bash
python3 scripts/record_browser_demo.py \
  --url "https://app.foxglove.dev/~/view?ds=foxglove-websocket&ds.url=ws%3A%2F%2Flocalhost%3A8765" \
  --output docs/assets/nav2-scenario-runner-demo.gif \
  --duration 12 \
  --fps 8
```

For a live Foxglove capture, record the dynamic obstacle scenario, not a dry-run or mock animation:

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
