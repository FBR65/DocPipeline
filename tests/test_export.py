"""S4 — Label-Studio-Export."""

from __future__ import annotations

from docpipeline.export import to_label_studio
from docpipeline.records import DocumentRecord, Entity, OcrInfo


def _record() -> DocumentRecord:
    text = "ACME zahlt 12 EUR"
    return DocumentRecord(
        source="rechnung.pdf",
        sha256="1" * 64,
        pages=1,
        ocr=OcrInfo(model="fake", pages_ocr=1),
        text=text,
        entities=[
            Entity(label="buyer", text="ACME", start=0, end=4, page=1, score=0.9),
            Entity(label="amount", text="12 EUR", start=11, end=17, page=1, score=0.8),
        ],
        warnings=[],
        timings_ms={"render": 0.0, "ocr": 0.0, "extract": 0.0},
    )


def test_label_studio_shape() -> None:
    out = to_label_studio(_record())
    assert out["data"]["text"] == "ACME zahlt 12 EUR"
    assert out["meta"]["source"] == "rechnung.pdf"
    results = out["annotations"][0]["result"]
    assert len(results) == 2
    first = results[0]
    assert first["value"] == {"start": 0, "end": 4, "text": "ACME", "labels": ["buyer"]}
    assert "from" not in first


def test_offsets_match_text() -> None:
    rec = _record()
    out = to_label_studio(rec)
    for item in out["annotations"][0]["result"]:
        v = item["value"]
        assert rec.text is not None
        assert rec.text[v["start"] : v["end"]] == v["text"]
