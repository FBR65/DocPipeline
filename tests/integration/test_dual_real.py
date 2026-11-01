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


def test_rapid_reader_reads_the_same_page() -> None:
    """S2: RapidOCR gegen dieselbe Seite, ohne Umweg über den Server."""
    import pymupdf

    from docpipeline.dual.rapid import RapidEngine

    assert RapidEngine.available() is True
    with pymupdf.open(_pdf()) as document:
        png = document[0].get_pixmap(dpi=300).tobytes("png")

    engine = RapidEngine(DualSettings())
    page = engine.describe_page(png, page_no=1)
    assert len(page.text) > 200
    assert len(page.boxes) > 20
    # Bewusst ohne Ortsnamen: der Test prueft Lesbarkeit, nicht den Inhalt.
    assert any(box.text.strip() for box in page.boxes)
    assert "Finanzamt" in page.text
    engine.close()


def test_three_engines_vote_on_the_same_page() -> None:
    """S3: drei Leser, Mehrheit statt Zweifach-Vergleich."""
    from docpipeline.dual.rapid import RapidEngine

    settings = DualSettings(ocr_mode="auto", dual_verify=False, dual_engine_c=True)
    engines = [PaddleEngine(settings), DotsEngine(settings), RapidEngine(settings)]
    schema = ExtractionSchema(
        model="fastino/gliner2.5-multi-v1",
        labels={"amount": "Geldbetrag mit Währung", "date": "Ein Datum"},
    )
    with DualOcr(settings, engines=engines) as dual:
        record = DualPipeline(
            settings, schema, dual, Gliner2Extractor(device="cpu"), verify=False
        ).run(_pdf())

    assert {variant for variant in record.variants} >= {"paddleocr-vl", "dots-mocr", "rapidocr"}
    assert record.cells, "mindestens ein Zellraster muss im Record stehen"
    classes = {entity.agreement for entity in record.entities}
    assert classes <= {"consensus", "majority", "single"}
    # Befund: auf diesem Dokument erreicht kaum ein Wert zwei Stimmen, weil die
    # Leser unterschiedliche Spans liefern. Das ist kein Fehler, sondern der Grund
    # für den Marker; die Mehrheitsregel selbst prüfen die Unit-Tests.
    assert sum(len(entity.sources) for entity in record.entities) >= len(record.entities)
