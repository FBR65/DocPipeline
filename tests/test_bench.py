"""I3 — Recall/Precision gegen Ground Truth."""

from __future__ import annotations

import json
from pathlib import Path

from docpipeline.bench import compare, format_table, load_ground_truth
from docpipeline.records import DocumentRecord, Entity, OcrInfo


def _record(name: str, items: list[tuple[str, str]]) -> DocumentRecord:
    return DocumentRecord(
        source=name,
        sha256="0" * 64,
        pages=1,
        ocr=OcrInfo(model="fake", pages_ocr=1),
        text="",
        entities=[
            Entity(label=lab, text=txt, start=i * 10, end=i * 10 + len(txt), score=0.9)
            for i, (lab, txt) in enumerate(items)
        ],
        warnings=[],
        timings_ms={"render": 0.0, "ocr": 0.0, "extract": 0.0},
    )


def _gt(tmp_path: Path, name: str, items: list[tuple[str, str]]) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(
        json.dumps({"entities": [{"label": lab, "text": txt} for lab, txt in items]}),
        encoding="utf-8",
    )
    return path


def test_load_ground_truth(tmp_path: Path) -> None:
    _gt(tmp_path, "doc1", [("buyer", "ACME")])
    (tmp_path / "kaputt.json").write_text("{}", encoding="utf-8")
    gt = load_ground_truth(tmp_path)
    assert gt == {"doc1": [("buyer", "ACME")]}


def test_compare_counts_matches_case_insensitive(tmp_path: Path) -> None:
    _gt(tmp_path, "a", [("buyer", "ACME"), ("amount", "12 EUR")])
    records = {"a": _record("a", [("buyer", "acme"), ("buyer", "Fremd")])}
    report = compare(records, load_ground_truth(tmp_path))
    assert report["buyer"].recall == 1.0
    assert report["buyer"].precision == 0.5
    assert report["amount"].recall == 0.0
    assert report["buyer"].tp == 1


def test_compare_ignores_missing_documents(tmp_path: Path) -> None:
    _gt(tmp_path, "a", [("buyer", "ACME")])
    _gt(tmp_path, "fehlt", [("buyer", "ACME")])
    report = compare({"a": _record("a", [("buyer", "ACME")])}, load_ground_truth(tmp_path))
    assert report["buyer"].missed_docs == 1


def test_format_table_contains_numbers(tmp_path: Path) -> None:
    _gt(tmp_path, "a", [("buyer", "ACME")])
    report = compare({"a": _record("a", [("buyer", "ACME")])}, load_ground_truth(tmp_path))
    table = format_table(report)
    assert "buyer" in table
    assert "100" in table
    assert table.count("\n") >= 1


def test_whitespace_normalised_before_match(tmp_path: Path) -> None:
    _gt(tmp_path, "a", [("buyer", "ACME  GmbH")])
    report = compare({"a": _record("a", [("buyer", "acme gmbh")])}, load_ground_truth(tmp_path))
    assert report["buyer"].recall == 1.0
