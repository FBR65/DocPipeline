"""S3 — Mehrheit, Konsens, Gleichstand (B4, D2, D5)."""

from __future__ import annotations

from docpipeline.dual.union import unite
from docpipeline.records import Entity, SourceRef


def e(label: str, text: str, start: int, score: float = 0.9, page: int = 1) -> Entity:
    return Entity(
        label=label, text=text, start=start, end=start + len(text), score=score, page=page
    )


def test_two_of_two_is_consensus() -> None:
    entities, warnings = unite(
        [
            ("paddleocr-vl", [e("amount", "1.428,50 EUR", 100)]),
            ("dots-mocr", [e("amount", "1.428.50", 110, score=0.8)]),
        ]
    )
    assert len(entities) == 1
    entry = entities[0]
    assert entry.agreement == "consensus"
    assert len(entry.sources) == 2
    assert {source.engine for source in entry.sources} == {"paddleocr-vl", "dots-mocr"}
    assert entry.score == 0.9
    assert warnings == []


def test_three_of_three_is_consensus() -> None:
    entities, warnings = unite(
        [
            ("paddleocr-vl", [e("amount", "-9.876,00", 100)]),
            ("dots-mocr", [e("amount", "-9.876,00", 120)]),
            ("rapidocr", [e("amount", "-9.876,00", 90)]),
        ]
    )
    assert entities[0].agreement == "consensus"
    assert len(entities[0].sources) == 3
    assert warnings == []


def test_text_layer_counts_as_a_vote() -> None:
    entities, _ = unite(
        [
            ("text_layer", [e("supplier", "Beispiel & Partner GmbH", 10)]),
            ("paddleocr-vl", [e("supplier", "beispiel & partner gmbh", 50)]),
        ]
    )
    assert entities[0].agreement == "consensus"
    assert {source.engine for source in entities[0].sources} == {"text_layer", "paddleocr-vl"}


def test_single_source_is_marked() -> None:
    entities, _ = unite([("dots-mocr", [e("date", "05.03.2024", 0)])])
    assert entities[0].agreement == "single"
    assert len(entities[0].sources) == 1


def test_majority_beats_a_single_different_value() -> None:
    entities, warnings = unite(
        [
            ("paddleocr-vl", [e("amount", "54.322,00", 100)]),
            ("dots-mocr", [e("amount", "54.322,00", 120)]),
            ("rapidocr", [e("amount", "54.326,00", 140)]),
        ]
    )
    by_value = {entry.text: entry.agreement for entry in entities}
    assert by_value["54.322,00"] == "majority"
    assert by_value["54.326,00"] == "single"
    assert len(entities) == 2
    assert warnings == []


def test_tie_keeps_both_values_and_warns() -> None:
    entities, warnings = unite(
        [
            ("paddleocr-vl", [e("amount", "-9.874,00", 100)]),
            ("dots-mocr", [e("amount", "-9.876,00", 120)]),
        ]
    )
    assert len(entities) == 2
    assert all(entry.agreement == "single" for entry in entities)
    assert warnings == ["conflict:amount:1"]


def test_same_value_on_different_pages_stays_separate() -> None:
    entities, _ = unite(
        [
            ("paddleocr-vl", [e("amount", "87,00", 10, page=1)]),
            ("dots-mocr", [e("amount", "87,00", 900, page=2)]),
        ]
    )
    assert len(entities) == 2
    assert {entry.page for entry in entities} == {1, 2}


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


def test_cell_origin_survives_the_union() -> None:
    cell_entity = e("amount", "-9.876,00", 0).model_copy(
        update={
            "engine": "dots-mocr",
            "sources": [SourceRef(engine="dots-mocr", start=0, end=11, score=0.9, zelle=(0, 1, 1))],
        }
    )
    entities, _ = unite([("dots-mocr", [cell_entity])])
    assert entities[0].sources[0].zelle == (0, 1, 1)


def test_empty_input() -> None:
    entities, warnings = unite([])
    assert entities == []
    assert warnings == []
