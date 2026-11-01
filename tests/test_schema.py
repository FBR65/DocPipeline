"""E3 — Schema laden und prüfen."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docpipeline.errors import SchemaError
from docpipeline.schema import ExtractionSchema, load_schema

TOML_OK = """
model = "fastino/gliner2.5-multi-v1"
threshold = 0.4

[labels]
buyer = "Name des Käufers"
amount = "Geldbetrag"
"""


def test_load_toml(tmp_path: Path) -> None:
    path = tmp_path / "schema.toml"
    path.write_text(TOML_OK, encoding="utf-8")
    schema = load_schema(path)
    assert schema.model == "fastino/gliner2.5-multi-v1"
    assert schema.threshold == 0.4
    assert schema.labels == {"buyer": "Name des Käufers", "amount": "Geldbetrag"}


def test_load_json_without_descriptions(tmp_path: Path) -> None:
    path = tmp_path / "schema.json"
    path.write_text(json.dumps({"labels": {"buyer": ""}}), encoding="utf-8")
    schema = load_schema(path)
    assert schema.labels == {"buyer": ""}
    assert schema.threshold == ExtractionSchema.model_fields["threshold"].default


def test_empty_labels_rejected(tmp_path: Path) -> None:
    path = tmp_path / "s.toml"
    path.write_text('model = "m"\nthreshold = 0.3\n', encoding="utf-8")
    with pytest.raises(SchemaError, match="labels"):
        load_schema(path)


def test_threshold_out_of_range_rejected(tmp_path: Path) -> None:
    for bad in (1.5, -0.1):
        path = tmp_path / f"s{bad}.toml"
        path.write_text(
            f'model = "m"\nthreshold = {bad}\n\n[labels]\nbuyer = ""\n', encoding="utf-8"
        )
        with pytest.raises(SchemaError, match="threshold"):
            load_schema(path)


def test_unknown_key_rejected(tmp_path: Path) -> None:
    path = tmp_path / "s.toml"
    path.write_text(TOML_OK.replace("[labels]", 'farbe = "rot"\n\n[labels]'), encoding="utf-8")
    with pytest.raises(SchemaError, match="farbe"):
        load_schema(path)


def test_empty_label_name_rejected(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"labels": {"": "x"}}), encoding="utf-8")
    with pytest.raises(SchemaError, match="label"):
        load_schema(path)


def test_missing_file_is_schema_error(tmp_path: Path) -> None:
    with pytest.raises(SchemaError):
        load_schema(tmp_path / "gibt-es-nicht.toml")


def test_labels_for_model_keeps_descriptions() -> None:
    schema = ExtractionSchema(labels={"buyer": "Käufer", "amount": ""})
    assert schema.for_model() == {"buyer": "Käufer", "amount": ""}
