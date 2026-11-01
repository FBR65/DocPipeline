"""S2 — RapidOCR als dritter Leser (B3, E3)."""

from __future__ import annotations

import builtins

import pytest

from docpipeline.dual.engines import DualSettings
from docpipeline.dual.rapid import RapidEngine
from docpipeline.errors import OcrError


class FakeResult:
    def __init__(self, lines: list[str], scores: list[float]) -> None:
        self.txts = tuple(lines)
        self.scores = tuple(scores)
        self.boxes = tuple(
            [
                [10.0, 100.0 + 20 * index],
                [90.0, 100.0 + 20 * index],
                [90.0, 112.0 + 20 * index],
                [10.0, 112.0 + 20 * index],
            ]
            for index in range(len(lines))
        )


class FakeRapid:
    """Doppelgänger des rapidocr-Aufrufs ``engine(image)``."""

    def __init__(self, lines: list[str], scores: list[float] | None = None) -> None:
        self.lines = lines
        self.scores = scores or [0.9] * len(lines)
        self.calls = 0

    def __call__(self, image: object) -> FakeResult:
        self.calls += 1
        return FakeResult(self.lines, self.scores)


def test_engine_reports_name_and_dpi() -> None:
    settings = DualSettings()
    engine = RapidEngine(settings, engine=FakeRapid([]))
    assert engine.name == "rapidocr"
    assert engine.dpi == settings.engine_c_dpi


def test_lines_become_boxes_with_confidence() -> None:
    rapid = FakeRapid(["12.345,00", "-9.876,00"], [0.99, 0.81])
    page = RapidEngine(DualSettings(), engine=rapid).describe_page(b"PNG", page_no=3)
    assert page.page_no == 3
    assert page.text.splitlines() == ["12.345,00", "-9.876,00"]
    assert page.tables == ()
    assert [box.text for box in page.boxes] == ["12.345,00", "-9.876,00"]
    assert page.boxes[0].bbox == (10.0, 100.0, 90.0, 112.0)
    assert page.boxes[1].score == pytest.approx(0.81)
    assert rapid.calls == 1


def test_empty_result_is_not_an_error() -> None:
    page = RapidEngine(DualSettings(), engine=FakeRapid([])).describe_page(b"PNG")
    assert page.text == ""
    assert page.boxes == ()


def test_engine_failure_becomes_ocr_error() -> None:
    class Broken:
        def __call__(self, image: object) -> object:
            raise RuntimeError("onnx kaputt")

    engine = RapidEngine(DualSettings(), engine=Broken())
    with pytest.raises(OcrError):
        engine.describe_page(b"PNG", page_no=2)


def test_availability_is_false_without_import(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("rapidocr"):
            raise ImportError("nicht installiert")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert RapidEngine.available() is False


def test_missing_engine_reports_unavailable() -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(RapidEngine, "available", staticmethod(lambda: False))
    try:
        engine = RapidEngine(DualSettings())
        assert engine.ping() is False
        with pytest.raises(OcrError):
            engine.describe_page(b"PNG")
    finally:
        monkeypatch.undo()
