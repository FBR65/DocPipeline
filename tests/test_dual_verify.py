"""B6/E3 — Regionen-Nachlesen einer Entität."""

from __future__ import annotations

from docpipeline.dual.formats import Element, OcrPage
from docpipeline.dual.verify import verify_entities
from docpipeline.errors import OcrError
from docpipeline.records import Entity


class ReadingEngine:
    """Gibt je Aufruf einen vorgegebenen Text zurück."""

    name = "paddleocr-vl"
    dpi = 300

    def __init__(self, answers: list[str] | None = None, boom: bool = False) -> None:
        self.answers = answers or []
        self.boom = boom
        self.crops: list[tuple[int, tuple[float, float, float, float]]] = []

    def describe_page(self, image: bytes, page_no: int = 1) -> OcrPage:
        if self.boom:
            raise OcrError("Nachlesen kaputt", page=page_no, status=500)
        self.crops.append((page_no, (0, 0, 0, 0)))
        text = self.answers.pop(0) if self.answers else ""
        return OcrPage(page_no=page_no, text=text)

    def ping(self) -> bool:
        return True


def _entity(text: str = "1.428,50", page: int = 1) -> Entity:
    return Entity(
        label="amount",
        text=text,
        start=0,
        end=len(text),
        page=page,
        score=0.9,
        normalized="1428.50",
    )


def _boxes(text: str = "1.428,50") -> dict[int, tuple[Element, ...]]:
    return {1: (Element(page_no=1, bbox=(10, 20, 30, 40), category="Text", text=text),)}


def test_matching_region_verifies() -> None:
    engine = ReadingEngine(["Betrag: 1.428,50 EUR"])
    entities, warnings = verify_entities(
        [_entity()], _boxes(), crop=lambda page, bbox: b"PNG", engine=engine
    )
    assert entities[0].verified is True
    assert warnings == []
    assert engine.crops and engine.crops[0][0] == 1


def test_differing_region_marks_false() -> None:
    engine = ReadingEngine(["Betrag: 1.500,00 EUR"])
    entities, _ = verify_entities(
        [_entity()], _boxes(), crop=lambda page, bbox: b"PNG", engine=engine
    )
    assert entities[0].verified is False


def test_missing_box_is_unavailable_with_warning() -> None:
    engine = ReadingEngine(["1.428,50"])
    entities, warnings = verify_entities(
        [_entity()], {}, crop=lambda page, bbox: b"PNG", engine=engine
    )
    assert entities[0].verified is None
    assert warnings == ["verify_skipped:amount:1:1.428,50"]
    assert engine.crops == []


def test_ocr_error_is_unavailable_with_warning() -> None:
    engine = ReadingEngine(boom=True)
    entities, warnings = verify_entities(
        [_entity()], _boxes(), crop=lambda page, bbox: b"PNG", engine=engine
    )
    assert entities[0].verified is None
    assert warnings == ["verify_skipped:amount:1:1.428,50"]


def test_entity_without_page_is_skipped() -> None:
    entities, warnings = verify_entities(
        [_entity(page=None)], _boxes(), crop=lambda p, b: b"PNG", engine=ReadingEngine()
    )
    assert entities[0].verified is None
    assert warnings == []


def test_input_is_not_modified() -> None:
    original = _entity()
    verify_entities(
        [original], _boxes(), crop=lambda p, b: b"PNG", engine=ReadingEngine(["1.428,50"])
    )
    assert original.verified is None


def test_crop_receives_box() -> None:
    seen: list[tuple[int, tuple[float, float, float, float]]] = []
    verify_entities(
        [_entity()],
        _boxes(),
        crop=lambda page, bbox: seen.append((page, bbox)) or b"PNG",
        engine=ReadingEngine(["1.428,50"]),
    )
    assert seen == [(1, (10, 20, 30, 40))]
