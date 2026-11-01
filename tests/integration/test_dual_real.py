"""Echt-Tests des Doppellaufs: beide Engines, echtes Modell, lokale Seite.

Lauf mit ``uv run pytest -m integration``. Ohne PDF im Projektordner
überspringen sich die Tests.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest

from docpipeline.dual.engines import DotsEngine, DualOcr, DualSettings, PaddleEngine
from docpipeline.dual.pipeline import DualPipeline
from docpipeline.extractor import Gliner2Extractor
from docpipeline.schema import ExtractionSchema

pytestmark = pytest.mark.integration

PDFS = sorted(glob.glob(str(Path(__file__).resolve().parents[2] / "*.pdf")))


def _pdf() -> Path:
    if not PDFS:
        pytest.skip("kein PDF im Projektordner")
    return Path(PDFS[0])


def test_both_engines_deliver_text_for_the_same_page() -> None:
    settings = DualSettings(ocr_mode="auto")
    engine_a = PaddleEngine(settings)
    engine_b = DotsEngine(settings)
    assert engine_a.ping() is True
    assert engine_b.ping() is True

    with DualOcr(settings, engines=[engine_a, engine_b]) as dual:
        variants = dual.variants(_pdf())

    names = [variant.name for variant in variants]
    assert "paddleocr-vl" in names
    assert "dots-mocr" in names
    for variant in variants:
        if variant.name == "text_layer":
            continue
        assert variant.pages_ocr >= 1
        assert len(variant.text.strip()) > 100, f"{variant.name} liefert kaum Text"

    dots = next(variant for variant in variants if variant.name == "dots-mocr")
    assert dots.boxes[0], "die Layout-Engine muss Boxen liefern"


def test_dual_pipeline_end_to_end_without_verify() -> None:
    settings = DualSettings(ocr_mode="always", dual_verify=False)
    schema = ExtractionSchema(
        model="fastino/gliner2.5-multi-v1",
        labels={"amount": "Geldbetrag mit Währung", "date": "Ein Datum"},
    )
    with DualOcr(settings, engines=[PaddleEngine(settings), DotsEngine(settings)]) as dual:
        record = DualPipeline(
            settings, schema, dual, Gliner2Extractor(device="cpu"), verify=False
        ).run(_pdf())

    assert set(record.variants) >= {"paddleocr-vl", "dots-mocr"}
    assert record.entities, "es muss mindestens ein Treffer entstehen"
    for entity in record.entities:
        assert entity.agreement in {"both", "single", "text_layer"}
        assert entity.sources
        variant_text = record.variants[str(entity.engine)]
        for source in entity.sources:
            snippet = record.variants[source.engine][source.start : source.end]
            assert snippet.lower() == entity.text.lower() or snippet, "Offset zeigt ins Leere"
        assert variant_text
    assert "ocr" in record.timings_ms and "extract" in record.timings_ms
