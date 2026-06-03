from __future__ import annotations

from pathlib import Path

import yaml


def test_turtlebot3_gazebo_examples_reference_existing_worlds():
    for path in sorted(Path("examples/turtlebot3_gazebo").glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        world = document["simulator"]["world"]
        assert (path.parent / world).exists(), f"{path} references missing world {world}"
