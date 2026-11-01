"""B1/E1 — zwei Engines je Seite, Phasenlauf, Auflösung je Engine, Abbruch."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pymupdf
import pytest

from docpipeline.dual.engines import DualOcr, DualSettings, Variant
from docpipeline.dual.formats import Element, OcrPage
from docpipeline.errors import OcrError


class FakeEngine:
    def __init__(self, name: str, dpi: int, fail_on: set[int] | None = None) -> None:
        self.name = name
        self.dpi = dpi
        self.model = name
        self.fail_on = fail_on or set()
        self.calls: list[int] = []
        self._active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def describe_page(self, image: bytes, page_no: int = 1) -> OcrPage:
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            time.sleep(0.01)
            if page_no in self.fail_on:
                raise OcrError(f"{self.name} kaputt", page=page_no, status=500)
            self.calls.append(page_no)
            text = f"{self.name} Seite {page_no}"
            return OcrPage(
                page_no=page_no,
                text=text,
                boxes=(Element(page_no=page_no, bbox=(0, 0, 10, 10), category="Text", text=text),),
            )
        finally:
            with self._lock:
                self._active -= 1

    def ping(self) -> bool:
        return not self.fail_on


@pytest.fixture
def two_page_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "zwei.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def layer_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "mit-text.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Rechnung RE-1 von ACME", fontsize=12)
    doc.save(path)
    doc.close()
    return path


def _settings(**kwargs) -> DualSettings:
    base = {"ocr_mode": "auto", "min_text_layer_chars": 5, "dual_workers": 2}
    base.update(kwargs)
    return DualSettings(**base)


def test_both_engines_on_every_page(two_page_pdf: Path) -> None:
    a = FakeEngine("paddleocr-vl", 300)
    b = FakeEngine("dots-mocr", 200)
    dual = DualOcr(_settings(), engines=[a, b])
    variants = dual.variants(two_page_pdf)
    assert sorted(a.calls) == [1, 2]
    assert sorted(b.calls) == [1, 2]
    assert [variant.name for variant in variants] == ["paddleocr-vl", "dots-mocr"]
    assert all(isinstance(variant, Variant) for variant in variants)


def test_each_engine_renders_with_its_own_dpi(two_page_pdf: Path) -> None:
    rendered: list[tuple[int, int]] = []

    def renderer(page_no: int, dpi: int) -> bytes:
        rendered.append((page_no, dpi))
        return b"PNG"

    dual = DualOcr(
        _settings(),
        engines=[FakeEngine("paddleocr-vl", 300), FakeEngine("dots-mocr", 200)],
        renderer=renderer,
    )
    dual.variants(two_page_pdf)
    assert (1, 300) in rendered and (2, 300) in rendered
    assert (1, 200) in rendered and (2, 200) in rendered


def test_phases_are_batched_per_engine(two_page_pdf: Path) -> None:
    order: list[str] = []

    class Recording(FakeEngine):
        def describe_page(self, image: bytes, page_no: int = 1) -> OcrPage:
            order.append(self.name)
            return super().describe_page(image, page_no)

    dual = DualOcr(
        _settings(dual_workers=1),
        engines=[Recording("paddleocr-vl", 300), Recording("dots-mocr", 200)],
        renderer=lambda page_no, dpi: b"PNG",
    )
    dual.variants(two_page_pdf)
    assert order == ["paddleocr-vl", "paddleocr-vl", "dots-mocr", "dots-mocr"]


def test_two_pages_run_in_parallel(two_page_pdf: Path) -> None:
    a = FakeEngine("paddleocr-vl", 300)
    dual = DualOcr(_settings(dual_workers=2), engines=[a], renderer=lambda page_no, dpi: b"PNG")
    dual.variants(two_page_pdf)
    assert a.max_active == 2


def test_text_layer_becomes_third_variant(layer_pdf: Path) -> None:
    a = FakeEngine("paddleocr-vl", 300)
    dual = DualOcr(_settings(), engines=[a], renderer=lambda page_no, dpi: b"PNG")
    variants = {variant.name: variant for variant in dual.variants(layer_pdf)}
    assert "text_layer" in variants
    assert "ACME" in variants["text_layer"].text
    assert a.calls == [1], "Textlayer ersetzt die OCR nicht (D2)"


def test_no_text_layer_variant_for_scans(two_page_pdf: Path) -> None:
    dual = DualOcr(
        _settings(), engines=[FakeEngine("paddleocr-vl", 300)], renderer=lambda p, d: b"PNG"
    )
    assert "text_layer" not in [variant.name for variant in dual.variants(two_page_pdf)]


def test_page_texts_and_offsets(two_page_pdf: Path) -> None:
    dual = DualOcr(
        _settings(), engines=[FakeEngine("paddleocr-vl", 300)], renderer=lambda p, d: b"PNG"
    )
    variant = dual.variants(two_page_pdf)[0]
    assert variant.page_texts == ("paddleocr-vl Seite 1", "paddleocr-vl Seite 2")
    assert variant.text == "paddleocr-vl Seite 1\n\npaddleocr-vl Seite 2"
    assert variant.pages_ocr == 2


def test_engine_failure_aborts(two_page_pdf: Path) -> None:
    broken = FakeEngine("dots-mocr", 200, fail_on={2})
    dual = DualOcr(
        _settings(), engines=[FakeEngine("paddleocr-vl", 300), broken], renderer=lambda p, d: b"PNG"
    )
    with pytest.raises(OcrError) as err:
        dual.variants(two_page_pdf)
    assert err.value.page == 2


def test_close_closes_all_engines(two_page_pdf: Path) -> None:
    class Closable(FakeEngine):
        closed = False

        def close(self) -> None:
            self.closed = True

    first = Closable("paddleocr-vl", 300)
    second = Closable("dots-mocr", 200)
    dual = DualOcr(_settings(), engines=[first, second], renderer=lambda p, d: b"PNG")
    dual.close()
    assert first.closed and second.closed
