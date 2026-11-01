"""Schema-Datei: Modell, Schwelle, Label mit Beschreibung (E3)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from docpipeline.errors import SchemaError


class ExtractionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = "fastino/gliner2.5-multi-v1"
    threshold: float = 0.35
    labels: dict[str, str]

    @field_validator("threshold")
    @classmethod
    def _threshold_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("threshold muss in [0,1] liegen")
        return value

    @field_validator("labels")
    @classmethod
    def _labels_valid(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("labels darf nicht leer sein")
        for name in value:
            if not name.strip():
                raise ValueError("label-Name darf nicht leer sein")
        return value

    def for_model(self) -> dict[str, str]:
        """Label → Beschreibung, wie GLiNER2 es erwartet."""
        return dict(self.labels)


def _read_data(path: Path) -> Any:
    raw = path.read_bytes()
    if path.suffix.lower() in {".toml", ".tml"}:
        return tomllib.loads(raw.decode("utf-8"))
    return json.loads(raw.decode("utf-8"))


def load_schema(path: str | Path) -> ExtractionSchema:
    schema_path = Path(path)
    if not schema_path.is_file():
        raise SchemaError(f"Schema-Datei nicht gefunden: {schema_path}")
    try:
        data = _read_data(schema_path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SchemaError(f"Schema-Datei nicht lesbar: {schema_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SchemaError(f"Schema-Datei muss ein Objekt sein: {schema_path}")
    try:
        return ExtractionSchema(**data)
    except ValidationError as exc:
        details = []
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "schema"
            details.append(f"{field}: {error['msg']}")
        raise SchemaError("; ".join(details)) from exc
