"""Extraktor-Adapter (B5) — Parsing ohne Modell geprüft."""

from __future__ import annotations

from typing import Any

import pytest

from docpipeline.extractor import Gliner2Extractor, to_entities
from docpipeline.records import Entity

TEXT = (
    "Rechnung Nr. RE-2026-0042\n"
    "Lieferant: Musterwerke GmbH\n"
    "Gesamtbetrag: 1.428,50 EUR\n"
)

# Echte Antwortform von fastino/gliner2.5-multi-v1 mit include_spans=True.
REAL_SHAPE = {
    "entities": {
        "invoice_number": [
            {"text": "RE-2026-0042", "confidence": 0.9958, "start": 13, "end": 25}
        ],
        "supplier": [
            {"text": "Musterwerke GmbH", "confidence": 0.9064, "start": 37, "end": 53}
        ],
        "amount": [
            {"text": "1.428,50 EUR", "confidence": 0.9928, "start": 68, "end": 80}
        ],
    }
}


class FakeModel:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    def extract_entities(self, text: str, labels: Any, **kwargs: Any) -> Any:
        self.calls.append({"text": text, "labels": labels, **kwargs})
        return self.answer


def test_real_answer_shape_becomes_entities() -> None:
    entities = to_entities(REAL_SHAPE, TEXT)
    assert len(entities) == 3
    supplier = next(e for e in entities if e.label == "supplier")
    assert (supplier.start, supplier.end) == (37, 53)
    assert TEXT[supplier.start : supplier.end] == supplier.text
    assert supplier.score == pytest.approx(0.9064)


def test_plain_string_answer_is_located() -> None:
    entities = to_entities({"entities": {"buyer": ["Musterwerke GmbH"]}}, TEXT)
    assert entities == [
        Entity(
            label="buyer",
            text="Musterwerke GmbH",
            start=37,
            end=53,
            score=0.0,
        )
    ]


def test_missing_span_is_recovered_from_text() -> None:
    raw = {"entities": {"buyer": [{"text": "RE-2026-0042", "confidence": 0.5}]}}
    assert to_entities(raw, TEXT)[0].start == 13


def test_unknown_text_is_dropped() -> None:
    raw = {"entities": {"buyer": [{"text": "nicht im Text"}]}}
    assert to_entities(raw, TEXT) == []


def test_empty_and_garbage_answers() -> None:
    assert to_entities({}, TEXT) == []
    assert to_entities(None, TEXT) == []
    assert to_entities({"entities": {"buyer": None}}, TEXT) == []
    assert to_entities({"entities": {"buyer": [42]}}, TEXT) == []


def test_extractor_passes_labels_schema_and_spans() -> None:
    model = FakeModel(REAL_SHAPE)
    extractor = Gliner2Extractor(model="m", threshold=0.4, loader=lambda: model)
    out = extractor.extract(TEXT, {"invoice_number": "Nummer"})
    assert [e.label for e in out] == ["invoice_number", "supplier", "amount"]
    call = model.calls[0]
    assert call["labels"] == {"invoice_number": "Nummer"}
    assert call["threshold"] == 0.4
    assert call["include_spans"] is True
    assert call["format_results"] is True


def test_extractor_skips_empty_input() -> None:
    model = FakeModel(REAL_SHAPE)
    extractor = Gliner2Extractor(loader=lambda: model)
    assert extractor.extract("   ", {"buyer": ""}) == []
    assert extractor.extract(TEXT, {}) == []
    assert model.calls == []
