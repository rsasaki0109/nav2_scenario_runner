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
