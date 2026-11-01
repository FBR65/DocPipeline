"""B4 — verglichen wird der Zahlenwert, nicht die Zeichenfolge (Auftrag: nur Zahlen)."""

from __future__ import annotations

import pytest

from docpipeline.dedup import normalize
from docpipeline.dual.union import unite
from docpipeline.dual.values import normalize_value, number_key
from docpipeline.records import Entity


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("98.765", "98.765,00"),
        ("98.765", "98.765.00"),
        ("432,00", "432.00"),
        ("432", "432,00"),
        ("12.345", "12.345,00 EUR"),
        ("-9.876,00", "-9.876"),
        ("456,78", "456.78"),
        ("0,00", "0"),
        ("14", "14,00"),
    ],
)
def test_same_number_same_key(left: str, right: str) -> None:
    assert number_key(left) == number_key(right)


def test_different_numbers_stay_different() -> None:
    assert number_key("54.321") != number_key("54.322")
    assert number_key("201,45") != number_key("201,46")


def test_key_drops_trailing_zeros() -> None:
    assert number_key("98.765,00") == "98765"
    assert number_key("-9.876,00") == "-9876"
    assert number_key("456,78") == "456.78"


def test_display_form_keeps_decimals() -> None:
    assert normalize_value("98.765,00") == "98765.00"
    assert number_key("98.765,00") == "98765"


def test_text_falls_back_to_normalised_text() -> None:
    assert number_key("  Postbank   Stuttgart ") == normalize("Postbank Stuttgart")


def test_three_readers_with_different_strings_vote_together() -> None:
    def e(text: str, start: int) -> Entity:
        return Entity(
            label="amount", text=text, start=start, end=start + len(text), page=1, score=0.9
        )

    entities, warnings = unite(
        [
            ("dots-mocr", [e("98.765", 100)]),
            ("paddleocr-vl", [e("98.765.00", 110)]),
            ("rapidocr", [e("98.765,00", 120)]),
        ]
    )
    assert len(entities) == 1
    assert entities[0].agreement == "consensus"
    assert len(entities[0].sources) == 3
    assert warnings == []


def test_entity_with_trailing_zeros_is_confirmed_by_shorter_reading() -> None:
    from docpipeline.dual.formats import Element, OcrPage
    from docpipeline.dual.verify import verify_entities

    class Reader:
        name = "rapidocr"
        dpi = 300

        def describe_page(self, image: bytes, page_no: int = 1) -> OcrPage:
            return OcrPage(page_no=page_no, text="98.765")

        def ping(self) -> bool:
            return True

    entity = Entity(
        label="amount",
        text="98.765.00",
        start=0,
        end=9,
        page=1,
        score=0.9,
        normalized="98765.00",
    )
    boxes = {1: (Element(1, (0.0, 0.0, 50.0, 20.0), "Text", "98.765.00"),)}
    verified, warnings = verify_entities([entity], boxes, lambda p, b: b"PNG", Reader())
    assert verified[0].verified is True
    assert warnings == []
