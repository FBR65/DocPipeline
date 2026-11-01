"""S1/S2 im Ablauf: Zellen im Record, dritte Engine, Prüfleser-Wahl."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from docpipeline.dual.engines import DualSettings, Variant
from docpipeline.dual.formats import Element, OcrPage, Table
from docpipeline.dual.pipeline import DualPipeline
from docpipeline.records import Entity
from docpipeline.schema import ExtractionSchema


class DigitExtractor:
    name = "digit"

    def __init__(self) -> None:
        self.batch_calls = 0

    def extract(self, text: str, labels: dict[str, str]) -> list[Entity]:
        out: list[Entity] = []
        for token in text.split():
            if any(char.isdigit() for char in token):
                start = text.find(token)
                out.append(
                    Entity(
                        label="amount", text=token, start=start, end=start + len(token), score=0.9
                    )
                )
        return out

    def extract_many(self, texts: list[str], labels: dict[str, str]) -> list[list[Entity]]:
        self.batch_calls += 1
        return [self.extract(text, labels) for text in texts]


class FakeDual:
    def __init__(self, variants: list[Variant], engines: list[object] | None = None) -> None:
        self._variants = variants
        self.engines = engines or []

    def variants(self, path: str | Path) -> list[Variant]:
        return self._variants


class StubEngine:
    def __init__(self, name: str, answer: str = "") -> None:
        self.name = name
        self.model = name
        self.dpi = 300
        self.answer = answer
        self.calls = 0

    def describe_page(self, image: bytes, page_no: int = 1) -> OcrPage:
        self.calls += 1
        return OcrPage(page_no=page_no, text=self.answer)

    def ping(self) -> bool:
        return True


def _table() -> Table:
    return Table(
        format="html",
        raw="",
        grid=(("Festgesetzt", "12.345,00"), ("Abzug", "-9.876,00")),
    )


def _variant(
    name: str = "dots-mocr", tables: tuple[tuple[Table, ...], ...] = ((_table(),),)
) -> Variant:
    return Variant(
        name=name,
        page_texts=("Text ohne Ziffern",),
        text="Text ohne Ziffern",
        boxes=((Element(1, (10.0, 10.0, 100.0, 40.0), "Text", "12.345,00"),),),
        tables=tables,
        dpi=200,
        pages_ocr=1,
    )


def _pdf(tmp_path: Path) -> Path:
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake")
    return path


def test_cell_hits_enter_the_record_with_origin(tmp_path: Path) -> None:
    dual = FakeDual([_variant()])
    pipeline = DualPipeline(
        DualSettings(dual_engine_c=False, dual_verify=False),
        ExtractionSchema(labels={"amount": "Betrag"}),
        dual,
        DigitExtractor(),
        verify=False,
    )
    record = pipeline.run(_pdf(tmp_path))
    amounts = [entity for entity in record.entities if entity.text == "12.345,00"]
    assert amounts, "Zelle muss einen Treffer liefern"
    assert amounts[0].sources[0].zelle == (0, 0, 1)
    assert amounts[0].page == 1


def test_cells_are_batched_not_one_call_per_cell(tmp_path: Path) -> None:
    extractor = DigitExtractor()
    DualPipeline(
        DualSettings(dual_engine_c=False, dual_verify=False),
        ExtractionSchema(labels={"amount": "Betrag"}),
        FakeDual([_variant()]),
        extractor,
        verify=False,
    ).run(_pdf(tmp_path))
    assert extractor.batch_calls == 1


def test_record_lists_cell_grids(tmp_path: Path) -> None:
    dual = FakeDual([_variant(), _variant("paddleocr-vl")])
    record = DualPipeline(
        DualSettings(dual_engine_c=False, dual_verify=False),
        ExtractionSchema(labels={"amount": "Betrag"}),
        dual,
        DigitExtractor(),
        verify=False,
    ).run(_pdf(tmp_path))
    assert len(record.cells) == 1
    grid = record.cells[0]
    assert (grid.page, grid.table, grid.rows, grid.cols) == (1, 0, 2, 2)
    assert set(grid.engines) == {"dots-mocr", "paddleocr-vl"}


def test_missing_third_engine_is_reported(tmp_path: Path) -> None:
    record = DualPipeline(
        DualSettings(dual_engine_c=True, dual_verify=False),
        ExtractionSchema(labels={"amount": "Betrag"}),
        FakeDual([_variant()], engines=[StubEngine("paddleocr-vl")]),
        DigitExtractor(),
        verify=False,
    ).run(_pdf(tmp_path))
    assert "engine_c_unavailable" in record.warnings


def test_no_warning_when_third_engine_present(tmp_path: Path) -> None:
    record = DualPipeline(
        DualSettings(dual_engine_c=True, dual_verify=False),
        ExtractionSchema(labels={"amount": "Betrag"}),
        FakeDual(
            [_variant()],
            engines=[StubEngine("paddleocr-vl"), StubEngine("rapidocr")],
        ),
        DigitExtractor(),
        verify=False,
    ).run(_pdf(tmp_path))
    assert "engine_c_unavailable" not in record.warnings


def test_verify_prefers_the_fast_reader(tmp_path: Path) -> None:
    paddle = StubEngine("paddleocr-vl", "12.345,00")
    rapid = StubEngine("rapidocr", "12.345,00")
    dual = FakeDual([_variant()], engines=[paddle, rapid])
    record = DualPipeline(
        DualSettings(dual_engine_c=True, dual_verify=True),
        ExtractionSchema(labels={"amount": "Betrag"}),
        dual,
        DigitExtractor(),
        verify=True,
        crop=lambda page_no, bbox: b"PNG",
    ).run(_pdf(tmp_path))
    assert rapid.calls > 0, "Prüfleser muss RapidOCR sein"
    assert paddle.calls == 0
    assert any(entity.verified for entity in record.entities)


def test_hash_and_source_are_kept(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path)
    record = DualPipeline(
        DualSettings(dual_engine_c=False, dual_verify=False),
        ExtractionSchema(labels={"amount": "Betrag"}),
        FakeDual([_variant()]),
        DigitExtractor(),
        verify=False,
    ).run(pdf)
    assert record.sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert record.source == "scan.pdf"


@pytest.mark.parametrize("name", ["dots-mocr", "paddleocr-vl"])
def test_cells_from_both_engines(tmp_path: Path, name: str) -> None:
    record = DualPipeline(
        DualSettings(dual_engine_c=False, dual_verify=False),
        ExtractionSchema(labels={"amount": "Betrag"}),
        FakeDual([_variant(name)]),
        DigitExtractor(),
        verify=False,
    ).run(_pdf(tmp_path))
    assert any(entity.sources and entity.sources[0].zelle for entity in record.entities)
