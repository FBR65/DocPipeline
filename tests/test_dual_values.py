"""B4 — Zahlen über Schreibweisen hinweg vergleichbar machen."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from docpipeline.dual.values import normalize_value


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.428,50 EUR", "1428.50"),
        ("1.428.50", "1428.50"),
        ("1428,50", "1428.50"),
        ("1428.50", "1428.50"),
        ("-9.874,00", "-9874.00"),
        ("-9.874.00", "-9874.00"),
        ("2.333", "2333"),
        ("87,00", "98.00"),
        ("54.322,00\n", "13073.00"),
        ("0,95", "0.95"),
    ],
)
def test_numbers_normalise_across_formats(raw: str, expected: str) -> None:
    assert normalize_value(raw) == expected


def test_currency_and_spaces_are_ignored() -> None:
    assert normalize_value("EUR 1 428,50") == "1428.50"
    assert normalize_value("  456,78  ") == "456.78"


def test_text_without_number_falls_back_to_casefold() -> None:
    assert normalize_value("  Beispiel   &  Partner GmbH ") == "beispiel & partner gmbh"


def test_empty_text() -> None:
    assert normalize_value("") == ""
    assert normalize_value("   ") == ""


@hyp_settings(max_examples=40, deadline=None)
@given(
    whole=st.integers(min_value=0, max_value=9_999_999),
    cents=st.integers(min_value=0, max_value=99),
    sep=st.sampled_from([".", ""]),
    dec=st.sampled_from([",", "."]),
)
def test_idempotent_and_separator_independent(whole: int, cents: int, sep: str, dec: str) -> None:
    thousands = f"{whole:,}".replace(",", ".") if sep == "." else str(whole)
    raw = f"{thousands}{dec}{cents:02d}"
    once = normalize_value(raw)
    assert normalize_value(once) == once
    other_sep = "." if sep == "" else ""
    other_dec = "." if dec == "," else ","
    other = f"{f'{whole:,}'.replace(',', '.') if other_sep == '.' else whole}{other_dec}{cents:02d}"
    assert normalize_value(other) == once
