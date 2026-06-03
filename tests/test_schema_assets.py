from __future__ import annotations

import json
from pathlib import Path


def test_root_and_packaged_schema_are_in_sync():
    root_schema = Path("schemas/nav2.scenario.v1alpha1.schema.json")
    packaged_schema = Path("src/nav2_scenario_runner/schemas/nav2.scenario.v1alpha1.schema.json")

    assert json.loads(root_schema.read_text(encoding="utf-8")) == json.loads(
        packaged_schema.read_text(encoding="utf-8")
    )
