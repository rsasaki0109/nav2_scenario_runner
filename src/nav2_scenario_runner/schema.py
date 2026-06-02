from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema


SCHEMA_FILENAME = "nav2.scenario.v1alpha1.schema.json"


@dataclass(frozen=True)
class SchemaValidator:
    schema: dict[str, Any]

    @classmethod
    def from_file(cls, path: Path) -> "SchemaValidator":
        with path.open("r", encoding="utf-8") as schema_file:
            return cls(json.load(schema_file))

    def validate(self, document: dict[str, Any]) -> list[str]:
        validator = jsonschema.Draft7Validator(self.schema)
        errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
        return [_format_error(error) for error in errors]


def default_schema_path() -> Path:
    source_tree_schema = Path(__file__).resolve().parents[2] / "schemas" / SCHEMA_FILENAME
    if source_tree_schema.exists():
        return source_tree_schema

    package_schema = resources.files("nav2_scenario_runner").joinpath("schemas", SCHEMA_FILENAME)
    return Path(str(package_schema))


def _format_error(error: jsonschema.ValidationError) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"
