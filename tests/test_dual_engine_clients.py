"""B2 — die beiden Engine-Klassen gegen einen Chat-Client-Doppelgänger."""

from __future__ import annotations

import pytest

from docpipeline.dual.engines import DotsEngine, DualSettings, PaddleEngine
from docpipeline.errors import OcrError


class FakeChat:
    model = "fake"

    def __init__(self, answers: list[tuple[str, str | None]]) -> None:
        self.answers = answers
        self.calls: list[dict] = []

    def complete(self, image: bytes, prompt: str, page_no: int = 1, max_tokens=None):
        self.calls.append({"prompt": prompt, "page": page_no, "max_tokens": max_tokens})
        return self.answers.pop(0)

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        return None


def _settings() -> DualSettings:
    return DualSettings()


def test_paddle_engine_parses_plain_text() -> None:
    chat = FakeChat([("Finanzamt Musterstadt\n05.03.2024", "stop")])
    page = PaddleEngine(_settings(), chat=chat).describe_page(b"PNG", page_no=2)
    assert page.page_no == 2
    assert "Finanzamt Musterstadt" in page.text
    assert page.tables == ()


def test_paddle_engine_parses_ots() -> None:
    chat = FakeChat([("<fcel>A<fcel>1,00<nl>", "stop")])
    page = PaddleEngine(_settings(), chat=chat).describe_page(b"PNG")
    assert page.tables[0].grid == (("A", "1,00"),)


def test_paddle_engine_rejects_truncated_answer() -> None:
    chat = FakeChat([("<fcel>A", "length")])
    with pytest.raises(OcrError, match="abgeschnitten"):
        PaddleEngine(_settings(), chat=chat).describe_page(b"PNG")


def test_dots_engine_parses_layout_and_passes_max_tokens() -> None:
    chat = FakeChat(
        [('{"elements": [{"bbox": [0,0,9,9], "category": "Text", "text": "ACME"}]}', "stop")]
    )
    engine = DotsEngine(_settings(), chat=chat)
    page = engine.describe_page(b"PNG")
    assert page.boxes[0].text == "ACME"
    assert chat.calls[0]["max_tokens"] == _settings().engine_b_max_tokens
    assert "layout information" in chat.calls[0]["prompt"]


def test_dots_engine_rejects_truncated_layout() -> None:
    chat = FakeChat([("[]", "length")])
    with pytest.raises(OcrError, match="abgeschnitten"):
        DotsEngine(_settings(), chat=chat).describe_page(b"PNG")


def test_engines_report_their_dpi() -> None:
    settings = _settings()
    assert PaddleEngine(settings, chat=FakeChat([])).dpi == settings.engine_a_dpi
    assert DotsEngine(settings, chat=FakeChat([])).dpi == settings.engine_b_dpi


def test_engine_names_come_from_settings() -> None:
    settings = _settings()
    assert PaddleEngine(settings, chat=FakeChat([])).name == settings.engine_a_model
    assert DotsEngine(settings, chat=FakeChat([])).name == settings.engine_b_model


def test_closing_engine_closes_client() -> None:
    class Tracking(FakeChat):
        closed = False

        def close(self) -> None:
            self.closed = True

    chat = Tracking([])
    engine = PaddleEngine(_settings(), chat=chat).close()
    assert engine is None
    assert chat.closed is True
