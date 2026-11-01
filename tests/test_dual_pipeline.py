"""B7 — Doppellauf bis zum Record."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from conftest import FakeExtractor
from docpipeline.dual.engines import DualSettings, Variant
from docpipeline.dual.pipeline import DualPipeline
from docpipeline.extractor import EntityExtractor
from docpipeline.records import Entity
from docpipeline.schema import ExtractionSchema


class FakeDual:
    def __init__(self, variants: list[Variant]) -> None:
        self._variants = variants
        self.calls: list[Path] = []

    def variants(self, path: str | Path) -> list[Variant]:
        self.calls.append(Path(path))
        return self._variants


def _variant(name: str, pages: list[str], dpi: int | None = 300) -> Variant:
    return Variant(
        name=name,
        page_texts=tuple(pages),
        text="\n\n".join(pages),
        boxes=tuple(() for _ in pages),
        tables=tuple(() for _ in pages),
        dpi=dpi,
        pages_ocr=len(pages) if name != "text_layer" else 0,
    )


@pytest.fixture
def settings() -> DualSettings:
    return DualSettings(
        engine_a_model="paddleocr-vl",
        engine_b_model="dots-mocr",
        engine_a_dpi=300,
        engine_b_dpi=200,
        dual_verify=False,
    )


@pytest.fixture
def schema() -> ExtractionSchema:
    return ExtractionSchema(model="fake", labels={"buyer": "Käufer"})


def _pdf(tmp_path: Path) -> Path:
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake")
    return path


def test_record_carries_all_variants(
    settings: DualSettings, schema: ExtractionSchema, tmp_path: Path
) -> None:
    dual = FakeDual(
        [
            _variant("paddleocr-vl", ["ACME kauft"], 300),
            _variant("dots-mocr", ["ACME kauft"], 200),
            _variant("text_layer", ["ACME kauft"], None),
        ]
    )
    pipeline = DualPipeline(settings, schema, dual, FakeExtractor({"buyer": "ACME"}))
    record = pipeline.run(_pdf(tmp_path))
    assert set(record.variants) == {"paddleocr-vl", "dots-mocr", "text_layer"}
    assert record.text == "ACME kauft"
    assert record.entities[0].agreement == "consensus"
    assert len(record.entities[0].sources) == 3


def test_engine_information_is_recorded(
    settings: DualSettings, schema: ExtractionSchema, tmp_path: Path
) -> None:
    dual = FakeDual([_variant("paddleocr-vl", ["a"], 300), _variant("dots-mocr", ["a"], 200)])
    record = DualPipeline(settings, schema, dual, FakeExtractor({})).run(_pdf(tmp_path))
    assert record.ocr.pages_ocr == 2
    assert [(engine.name, engine.dpi) for engine in record.ocr.engines] == [
        ("paddleocr-vl", 300),
        ("dots-mocr", 200),
    ]


def test_text_prefers_text_layer(
    settings: DualSettings, schema: ExtractionSchema, tmp_path: Path
) -> None:
    dual = FakeDual(
        [
            _variant("paddleocr-vl", ["ACME kauft"]),
            _variant("dots-mocr", ["ACME kauft"]),
            _variant("text_layer", ["ACME kauft genau"]),
        ]
    )
    record = DualPipeline(settings, schema, dual, FakeExtractor({"buyer": "ACME"})).run(
        _pdf(tmp_path)
    )
    assert record.text == "ACME kauft genau"


def test_hash_source_and_timings(
    settings: DualSettings, schema: ExtractionSchema, tmp_path: Path
) -> None:
    pdf = _pdf(tmp_path)
    dual = FakeDual([_variant("paddleocr-vl", ["a"])])
    record = DualPipeline(settings, schema, dual, FakeExtractor({})).run(pdf)
    assert record.sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert record.source == "scan.pdf"
    assert set(record.timings_ms) == {"ocr", "extract"}


def test_verify_false_leaves_flags_empty(
    settings: DualSettings, schema: ExtractionSchema, tmp_path: Path
) -> None:
    dual = FakeDual([_variant("paddleocr-vl", ["ACME"])])
    record = DualPipeline(settings, schema, dual, FakeExtractor({"buyer": "ACME"})).run(
        _pdf(tmp_path)
    )
    assert record.entities[0].verified is None
    assert "verify" not in record.timings_ms


def test_verify_true_uses_engine(
    settings: DualSettings, schema: ExtractionSchema, tmp_path: Path
) -> None:
    from docpipeline.dual.formats import Element, OcrPage

    class Engine:
        name = "paddleocr-vl"
        dpi = 300

        def describe_page(self, image: bytes, page_no: int = 1) -> OcrPage:
            return OcrPage(page_no=page_no, text="ACME")

        def ping(self) -> bool:
            return True

    dual = FakeDual(
        [
            Variant(
                name="paddleocr-vl",
                page_texts=("ACME",),
                text="ACME",
                boxes=((Element(1, (0, 0, 5, 5), "Text", "ACME"),),),
                tables=((),),
                dpi=300,
                pages_ocr=1,
            )
        ]
    )
    pipeline = DualPipeline(
        settings,
        schema,
        dual,
        FakeExtractor({"buyer": "ACME"}),
        verify=True,
        verify_engine=Engine(),
        crop=lambda page_no, bbox: b"PNG",
    )
    record = pipeline.run(_pdf(tmp_path))
    assert record.entities[0].verified is True
    assert "verify" in record.timings_ms


def test_conflict_warning_reaches_record(
    settings: DualSettings, schema: ExtractionSchema, tmp_path: Path
) -> None:
    dual = FakeDual(
        [
            _variant("paddleocr-vl", ["ACME 1.428,50"]),
            _variant("dots-mocr", ["ACME 1.500,00"]),
        ]
    )
    record = DualPipeline(
        settings,
        ExtractionSchema(model="fake", labels={"amount": "Betrag"}),
        dual,
        _AmountExtractor(),
    ).run(_pdf(tmp_path))
    assert any(warning.startswith("conflict:amount:1") for warning in record.warnings)


class _AmountExtractor(EntityExtractor):
    name = "amount-extractor"

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
