"""B6 — Box-Suche in Tabellen und mehrzeiligen Feldern (Befund aus dem Echtlauf).

Die Layout-Engine fasst ganze Tabellen in ein Element mit HTML-Text. Dort stehen
die Beträge als Zellen, nicht als erstes Zahl-Token. Die Suche muss die Zahlen
im Element durchsuchen, sonst bleibt fast jede Entität ungeprüft.
"""

from __future__ import annotations

from docpipeline.dual.formats import Element, OcrPage
from docpipeline.dual.verify import verify_entities
from docpipeline.records import Entity

TABLE_HTML = (
    "<table><tr><td>verbleibende Steuer</td><td>-9.874,00</td><td>-56,78</td></tr>"
    "<tr><td>ausgezahlt</td><td>98.765,00</td><td>432,00</td></tr></table>"
)


class Reader:
    name = "paddleocr-vl"
    dpi = 300

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    def describe_page(self, image: bytes, page_no: int = 1) -> OcrPage:
        self.calls += 1
        return OcrPage(page_no=page_no, text=self.answer)

    def ping(self) -> bool:
        return True


def _entity(text: str, normalized: str) -> Entity:
    return Entity(
        label="amount",
        text=text,
        start=0,
        end=len(text),
        page=1,
        score=0.8,
        normalized=normalized,
    )


def _boxes() -> dict[int, tuple[Element, ...]]:
    return {
        1: (
            Element(1, (10, 10, 100, 20), "Text", "Finanzamt Musterstadt"),
            Element(1, (10, 100, 400, 300), "Table", TABLE_HTML),
        )
    }


def test_value_inside_table_cell_is_found() -> None:
    engine = Reader("Bemessungsgrundlage -9.874,00 EUR")
    entities, warnings = verify_entities(
        [_entity("-9.874,00", "-9874.00")], _boxes(), lambda p, b: b"PNG", engine
    )
    assert engine.calls == 1
    assert entities[0].verified is True
    assert warnings == []


def test_second_table_row_is_found() -> None:
    engine = Reader("432,00")
    entities, _ = verify_entities(
        [_entity("432,00", "432.00")], _boxes(), lambda p, b: b"PNG", engine
    )
    assert entities[0].verified is True


def test_value_not_in_any_box_is_reported_with_value() -> None:
    engine = Reader("1.428,50")
    entities, warnings = verify_entities(
        [_entity("777,77", "777.77")], _boxes(), lambda p, b: b"PNG", engine
    )
    assert entities[0].verified is None
    assert warnings == ["verify_skipped:amount:1:777,77"]
    assert engine.calls == 0


def test_box_for_plain_text_is_still_found() -> None:
    engine = Reader("Finanzamt Musterstadt")
    entities, _ = verify_entities(
        [_entity("Finanzamt Musterstadt", "finanzamt musterstadt")], _boxes(), lambda p, b: b"PNG", engine
    )
    assert entities[0].verified is True


def test_same_box_is_read_once() -> None:
    engine = Reader("-9.874,00 98.765,00")
    entities = [_entity("-9.874,00", "-9874.00"), _entity("98.765,00", "98765.00")]
    verified, _warnings = verify_entities(entities, _boxes(), lambda p, b: b"PNG", engine)
    assert [entry.verified for entry in verified] == [True, True]
    assert engine.calls == 1
