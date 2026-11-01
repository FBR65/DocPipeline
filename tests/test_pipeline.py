"""B7 — Dokument-Record über die ganze Pipeline."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest

from conftest import FakeExtractor, FakeOcr
from docpipeline.config import Settings
from docpipeline.errors import OcrError
from docpipeline.pipeline import DocumentPipeline
from docpipeline.schema import ExtractionSchema


@pytest.fixture
def two_page_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "zwei.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    doc.save(path)
    doc.close()
    return path


def _schema() -> ExtractionSchema:
    return ExtractionSchema(model="fake", threshold=0.3, labels={"buyer": "Käufer"})


def test_entities_are_mapped_to_document_offsets_and_pages(
    settings: Settings, two_page_pdf: Path
) -> None:
    ocr = FakeOcr({1: "ACME kauft Ware", 2: "ACME zahlt spaeter"})
    pipe = DocumentPipeline(settings, _schema(), ocr, FakeExtractor({"buyer": "ACME"}))
    record = pipe.run(two_page_pdf)

    assert record.pages == 2
    assert record.text == "ACME kauft Ware\n\nACME zahlt spaeter"
    assert [e.page for e in record.entities] == [1, 2]
    for ent in record.entities:
        assert record.text[ent.start : ent.end] == ent.text
    assert record.ocr.pages_ocr == 2
    assert record.ocr.model == "fake-ocr"


def test_record_hash_matches_file(settings: Settings, two_page_pdf: Path) -> None:
    pipe = DocumentPipeline(
        settings, _schema(), FakeOcr({1: "a", 2: "b"}), FakeExtractor({"buyer": "ACME"})
    )
    record = pipe.run(two_page_pdf)
    assert record.sha256 == hashlib.sha256(two_page_pdf.read_bytes()).hexdigest()
    assert record.source == "zwei.pdf"


def test_empty_page_warns_and_continues(settings: Settings, two_page_pdf: Path) -> None:
    ocr = FakeOcr({1: "", 2: "ACME hier"})
    pipe = DocumentPipeline(settings, _schema(), ocr, FakeExtractor({"buyer": "ACME"}))
    record = pipe.run(two_page_pdf)
    assert "empty_page:1" in record.warnings
    assert len(record.entities) == 1
    assert record.entities[0].page == 2


def test_entities_are_sorted_and_unique(settings: Settings, two_page_pdf: Path) -> None:
    ocr = FakeOcr({1: "ACME A", 2: "ACME B"})
    pipe = DocumentPipeline(settings, _schema(), ocr, FakeExtractor({"buyer": "ACME"}))
    record = pipe.run(two_page_pdf)
    keys = [(e.start, e.label) for e in record.entities]
    assert keys == sorted(keys)


def test_ocr_failure_aborts_without_record(settings: Settings, two_page_pdf: Path) -> None:
    class FailingOcr(FakeOcr):
        def ocr_page(self, image: bytes, page_no: int = 1) -> str:
            raise OcrError("OCR kaputt", page=page_no, status=500)

    pipe = DocumentPipeline(settings, _schema(), FailingOcr(), FakeExtractor({}))
    with pytest.raises(OcrError):
        pipe.run(two_page_pdf)


def test_text_layer_is_used_without_ocr(settings: Settings, text_pdf: Path) -> None:
    settings.min_text_layer_chars = 5
    ocr = FakeOcr()
    pipe = DocumentPipeline(settings, _schema(), ocr, FakeExtractor({"buyer": "ACME"}))
    record = pipe.run(text_pdf)
    assert ocr.calls == []
    assert record.ocr.pages_ocr == 0
    assert record.entities[0].page == 1
    assert record.entities[0].text == "ACME"


def test_timings_present(settings: Settings, two_page_pdf: Path) -> None:
    pipe = DocumentPipeline(
        settings, _schema(), FakeOcr({1: "a", 2: "b"}), FakeExtractor({"buyer": "ACME"})
    )
    record = pipe.run(two_page_pdf)
    assert set(record.timings_ms) == {"render", "ocr", "extract"}
    assert all(v >= 0 for v in record.timings_ms.values())


def test_schema_labels_reach_extractor(settings: Settings, two_page_pdf: Path) -> None:
    extractor = FakeExtractor({"buyer": "ACME", "amount": "EUR"})
    schema = ExtractionSchema(labels={"buyer": "Käufer"})
    pipe = DocumentPipeline(settings, schema, FakeOcr({1: "ACME", 2: "ACME"}), extractor)
    pipe.run(two_page_pdf)
    assert extractor.seen, "Extractor muss aufgerufen werden"
