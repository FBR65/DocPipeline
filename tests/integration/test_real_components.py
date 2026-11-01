"""Echt-Tests: echtes OCR (llama-swap) und echtes GLiNER2-Modell.

Lauf mit ``uv run pytest -m integration``. Standardlauf schließt sie aus.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docpipeline.config import Settings
from docpipeline.extractor import Gliner2Extractor
from docpipeline.ocr import OcrClient
from docpipeline.pipeline import DocumentPipeline
from docpipeline.schema import ExtractionSchema

ARTICLE = (
    Path(__file__).resolve().parents[2]
    / "Extract Anything From Anywhere_ Building Document AI Pipeline with GLINER"
    " Beyond Zero Shot _ by Dhanya Shanbhag _ Oct, 2026 _ Towards AI.pdf"
)

pytestmark = pytest.mark.integration


def test_ocr_endpoint_is_reachable() -> None:
    settings = Settings()
    with OcrClient(settings) as client:
        assert client.ping() is True


def test_ocr_reads_a_page() -> None:
    import pymupdf

    if not ARTICLE.is_file():
        pytest.skip("Artikel-PDF fehlt")
    with pymupdf.open(ARTICLE) as document:
        png = document[0].get_pixmap(dpi=100).tobytes("png")
    with OcrClient(Settings()) as client:
        text = client.ocr_page(png, page_no=1)
    assert len(text) > 200
    assert "GLINER" in text.upper()


def test_model_extracts_from_real_text() -> None:
    extractor = Gliner2Extractor(device="cpu")
    entities = extractor.extract(
        "Rechnung Nr. RE-2026-0042 von Musterwerke GmbH ueber 1.428,50 EUR.",
        {
            "invoice_number": "Rechnungsnummer",
            "supplier": "Name des Lieferanten",
            "amount": "Geldbetrag mit Waehrung",
        },
    )
    labels = {entity.label for entity in entities}
    assert "invoice_number" in labels
    assert "amount" in labels
    assert all(entity.text for entity in entities)


def test_pipeline_on_article_uses_text_layer() -> None:
    if not ARTICLE.is_file():
        pytest.skip("Artikel-PDF fehlt")
    settings = Settings(ocr_mode="auto", window_words=220, overlap_words=40)

    class NoOcr:
        model = "nicht-benutzt"

        def ocr_page(self, image: bytes, page_no: int = 1) -> str:
            raise AssertionError("Textlayer hätte reichen müssen")

        def ping(self) -> bool:
            return True

    schema = ExtractionSchema(labels={"title": "Titel des Artikels", "author": "Name des Autors"})
    pipeline = DocumentPipeline(settings, schema, NoOcr(), Gliner2Extractor(device="cpu"))
    record = pipeline.run(ARTICLE)

    assert record.pages == 6
    assert record.ocr.pages_ocr == 0
    assert record.text is not None
    for entity in record.entities:
        assert record.text[entity.start : entity.end] == entity.text
