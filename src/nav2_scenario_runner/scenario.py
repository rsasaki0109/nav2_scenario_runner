from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


SCENARIO_EXTENSIONS = {".yaml", ".yml"}


@dataclass(frozen=True)
class Scenario:
    path: Path
    document: dict[str, Any]
    scenario_id: str
    name: str
    tags: set[str]
    step_count: int
    assertion_count: int


@dataclass
class LoadResult:
    path: Path
    scenario: Scenario | None = None
    errors: list[str] = field(default_factory=list)


def discover_scenarios(paths: list[str | Path]) -> list[Path]:
    discovered: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file():
            if path.suffix in SCENARIO_EXTENSIONS:
                discovered.append(path)
            continue
        if path.is_dir():
            discovered.extend(
                child
                for child in path.rglob("*")
                if child.is_file() and child.suffix in SCENARIO_EXTENSIONS
            )
            continue
        discovered.append(path)

    return sorted(dict.fromkeys(discovered))


def load_scenario(path: Path) -> LoadResult:
    result = LoadResult(path=path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        result.errors.append(f"Cannot read file: {exc}")
        return result

    try:
        document = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        result.errors.append(f"YAML parse error: {exc}")
        return result

    if not isinstance(document, dict):
        result.errors.append("Scenario document must be a YAML mapping.")
        return result

    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    name = metadata.get("name") or path.stem
    tags_raw = metadata.get("tags") or []
    tags = {str(tag) for tag in tags_raw} if isinstance(tags_raw, list) else set()

    steps_raw = document.get("steps") or []
    assertions_raw = document.get("assertions") or []

    result.scenario = Scenario(
        path=path,
        document=document,
        scenario_id=str(name),
        name=str(name),
        tags=tags,
        step_count=len(steps_raw) if isinstance(steps_raw, list) else 0,
        assertion_count=len(assertions_raw) if isinstance(assertions_raw, list) else 0,
    )
    return result
