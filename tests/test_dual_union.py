"""Union über Varianten: agreement, Konflikte, Reihenfolge, kein Verlust (B5, E2, I3)."""

from __future__ import annotations

from docpipeline.dual.union import unite
from docpipeline.records import Entity


def e(label: str, text: str, start: int, score: float = 0.9, page: int = 1) -> Entity:
    return Entity(
        label=label, text=text, start=start, end=start + len(text), score=score, page=page
    )


def test_two_engines_agree() -> None:
    entities, warnings = unite(
        [
            ("paddleocr-vl", [e("amount", "1.428,50 EUR", 100)]),
            ("dots-mocr", [e("amount", "1.428.50", 110, score=0.8)]),
        ]
    )
    assert len(entities) == 1
    entry = entities[0]
    assert entry.agreement == "both"
    assert len(entry.sources) == 2
    assert {source.engine for source in entry.sources} == {"paddleocr-vl", "dots-mocr"}
    assert entry.score == 0.9
    assert warnings == []


def test_text_layer_counts_as_confirmation() -> None:
    entities, _ = unite(
        [
            ("text_layer", [e("supplier", "Beispiel & Partner GmbH", 10)]),
            ("paddleocr-vl", [e("supplier", "beispiel & partner gmbh", 50)]),
        ]
    )
    assert entities[0].agreement == "text_layer"


def test_single_source_is_marked() -> None:
    entities, _ = unite([("dots-mocr", [e("date", "05.03.2024", 0)])])
    assert entities[0].agreement == "single"
    assert len(entities[0].sources) == 1


def test_different_numbers_on_same_page_conflict() -> None:
    entities, warnings = unite(
        [
            ("paddleocr-vl", [e("amount", "-9.874,00", 100)]),
            ("dots-mocr", [e("amount", "-9.876,00", 120)]),
        ]
    )
    assert len(entities) == 2
    assert all(entry.agreement == "single" for entry in entities)
    assert "conflict:amount:1" in warnings


def test_same_value_on_different_pages_stays_separate() -> None:
    entities, _ = unite(
        [
            ("paddleocr-vl", [e("amount", "87,00", 10, page=1)]),
            ("dots-mocr", [e("amount", "87,00", 900, page=2)]),
        ]
    )
    assert len(entities) == 2


def test_no_source_is_lost() -> None:
    per_variant = [
        ("text_layer", [e("a", "x", 0), e("b", "y", 5)]),
        ("paddleocr-vl", [e("a", "x", 0), e("a", "x", 400)]),
        ("dots-mocr", [e("b", "y", 7)]),
    ]
    entities, _ = unite(per_variant)
    total_sources = sum(len(entry.sources) for entry in entities)
    assert total_sources == sum(len(items) for _name, items in per_variant)


def test_sorted_by_page_offset_then_label() -> None:
    entities, _ = unite(
        [
            ("paddleocr-vl", [e("z", "b", 50), e("a", "y", 10)]),
            ("dots-mocr", [e("b", "c", 10, page=2)]),
        ]
    )
    assert [(entry.page, entry.start, entry.label) for entry in entities] == [
        (1, 10, "a"),
        (1, 50, "z"),
        (2, 10, "b"),
    ]


def test_empty_input() -> None:
    entities, warnings = unite([])
    assert entities == []
    assert warnings == []
