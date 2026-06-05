# Trajectory Replay

The `replay` command turns a run report's recorded `/odom` trajectory into an
animated SVG. The robot marker travels the path on a loop, and when a ROS map is
supplied the trajectory is drawn over the real occupancy grid instead of a blank
grid — so a failure is easy to read in its spatial context.

## Workflow

```bash
nav2_scenario_runner replay reports/results.json \
  --map maps/warehouse.yaml \
  --html-output reports/replay.html \
  --duration 5
```

- `--map` is optional. Without it the trajectory is drawn on a blank grid,
  auto-scaled to the path bounds.
- `--scenario <id>` (repeatable) limits the replay to specific scenarios.
  By default every scenario that recorded a trajectory is rendered.
- `--duration` sets the seconds for one loop of the animation.

The trajectory comes from the `trajectory` metric (a list of `{x, y}` world
points), which the ROS attach backend integrates from `/odom`.

## Map support

The map is a standard ROS map description:

```yaml
image: warehouse.pgm
resolution: 0.05
origin: [-5.0, -3.75, 0.0]
negate: 0
```

- The image may be a binary `P5` or ASCII `P2` PGM (8-bit grayscale).
- `resolution` is metres per pixel; `origin` is the world pose of the
  bottom-left pixel. World points are projected as
  `svg_x = (x - origin_x) / resolution`,
  `svg_y = height - (y - origin_y) / resolution`.
- `negate: 1` inverts the grayscale, matching the ROS map server convention.

The PGM is re-encoded to a grayscale PNG and embedded as a `data:` URI using only
the Python standard library (`zlib` + a small PNG writer), so the output HTML is
fully self-contained with no Pillow/numpy dependency and no external image files.

## Animation

The moving robot marker uses SVG SMIL `<animateMotion>` along the trajectory
path with `rotate="auto"`, so it plays in any modern browser with no JavaScript.
The path is colored green for passing scenarios and red for failing ones, with
green start and red goal markers. This makes `replay.html` safe to upload as a CI
artifact or embed in GitHub Pages.
