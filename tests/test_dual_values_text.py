"""B4 — Zahlenschlüssel bei gemischtem Text (Befunde aus dem Echtlauf)."""

from __future__ import annotations

import pytest

from docpipeline.dual.values import normalize_value


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("432,00 4", "432.00"),
        ("87,00 101", "98.00"),
        ("432.00\n4.00", "432.00"),
        ("1 428,50", "1428.50"),
        ("Euro 1.428,50 EUR", "1428.50"),
        ("654.32", "654.32"),
    ],
)
def test_number_inside_mixed_text(raw: str, expected: str) -> None:
    assert normalize_value(raw) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Beispiel & Partner GmbH",
        "Familie Beispiel Musterstraße 12\n12345 Musterstadt",
        "Finanzamt Musterstadt",
    ],
)
def test_text_with_little_numbers_stays_text(text: str) -> None:
    assert normalize_value(text) == normalize_value(text.lower())
    assert normalize_value(text) != normalize_value(text.rsplit(maxsplit=1)[-1])


def test_short_text_with_one_number_is_numeric() -> None:
    assert normalize_value("A211") == "211"
    assert normalize_value("B421") == "421"
    assert normalize_value("12/345/67890") == "079"
