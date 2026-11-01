"""B4/B5 — die Stimme ignoriert das Label, Zahlen entscheiden (D6)."""

from __future__ import annotations

from docpipeline.dual.union import unite
from docpipeline.records import Entity


def e(label: str, text: str, start: int, score: float = 0.9, page: int = 1) -> Entity:
    return Entity(
        label=label, text=text, start=start, end=start + len(text), score=score, page=page
    )


def test_same_number_with_different_labels_is_one_finding() -> None:
    entities, warnings = unite(
        [
            ("paddleocr-vl", [e("amount", "98.765.00", 100, score=0.95)]),
            ("dots-mocr", [e("tax_number", "98.765", 120, score=0.80)]),
        ]
    )
    assert len(entities) == 1
    entry = entities[0]
    assert entry.agreement == "consensus"
    assert entry.label == "amount", "Label der besten Quelle gewinnt"
    assert {source.label for source in entry.sources} == {"amount", "tax_number"}
    assert warnings == ["label_conflict:1:98765"]


def test_three_readers_with_two_labels_still_vote() -> None:
    entities, warnings = unite(
        [
            ("paddleocr-vl", [e("amount", "12.345,00", 10)]),
            ("dots-mocr", [e("tax_number", "12.345", 20)]),
            ("rapidocr", [e("amount", "12.345,00", 30)]),
        ]
    )
    assert len(entities) == 1
    assert entities[0].agreement == "consensus"
    assert len(entities[0].sources) == 3
    assert warnings == ["label_conflict:1:12345"]


def test_different_numbers_with_different_labels_stay_separate() -> None:
    entities, _ = unite(
        [
            ("paddleocr-vl", [e("amount", "54.322,00", 10)]),
            ("dots-mocr", [e("tax_number", "54.321", 20)]),
        ]
    )
    assert len(entities) == 2
    assert {entry.agreement for entry in entities} == {"single"}


def test_text_values_keep_their_label_in_the_key() -> None:
    entities, warnings = unite(
        [
            ("paddleocr-vl", [e("supplier", "Beispiel & Partner GmbH", 10)]),
            ("dots-mocr", [e("taxpayer", "Beispiel & Partner GmbH", 20)]),
        ]
    )
    assert len(entities) == 2, "Text ohne Zahl bleibt am Label gebunden"
    assert warnings == []


def test_same_number_on_different_pages_stays_separate() -> None:
    entities, _ = unite(
        [
            ("paddleocr-vl", [e("amount", "432,00", 10, page=1)]),
            ("dots-mocr", [e("amount", "432,00", 20, page=2)]),
        ]
    )
    assert len(entities) == 2


def test_label_conflict_is_not_reported_for_a_single_source() -> None:
    entities, warnings = unite([("dots-mocr", [e("tax_number", "4711", 0)])])
    assert warnings == []
    assert entities[0].agreement == "single"


def test_conflict_warning_names_the_page_not_the_label() -> None:
    entities, warnings = unite(
        [
            ("paddleocr-vl", [e("taxpayer", "Beispiel & Partner GmbH", 10, page=1)]),
            ("dots-mocr", [e("taxpayer", "Beispiel und Partner GmbH", 20, page=1)]),
        ]
    )
    assert len(entities) == 2
    assert warnings == ["conflict:taxpayer:1"]
