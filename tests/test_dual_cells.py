"""S1 — Ziffern aus Tabellenzellen statt aus Fließtext-Spans (B1, B2, E1)."""

from __future__ import annotations

import pytest

from docpipeline.dual.cells import Cell, cells_from_variant, extract_cells, has_digit
from docpipeline.dual.engines import Variant
from docpipeline.dual.formats import Table
from docpipeline.records import Entity
from docpipeline.schema import ExtractionSchema


class EchoExtractor:
    """Gibt je Zelle einen Treffer für jede Ziffer zurück (Doppelgänger)."""

    name = "echo"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def extract(self, text: str, labels: dict[str, str]) -> list[Entity]:
        """Verhält sich wie ein Modell: liefert den Wert, nicht den Kontext."""
        self.seen.append(text)
        value = text.rsplit(": ", 1)[-1]
        start = text.rindex(value)
        return [Entity(label="amount", text=value, start=start, end=start + len(value), score=0.9)]

    def extract_many(self, texts: list[str], labels: dict[str, str]) -> list[list[Entity]]:
        self.seen.append(f"batch:{len(texts)}")
        return [self.extract(text, labels) for text in texts]


def _variant(tables: tuple[tuple[Table, ...], ...]) -> Variant:
    pages = len(tables)
    return Variant(
        name="dots-mocr",
        page_texts=tuple("Text" for _ in range(pages)),
        text="\n\n".join("Text" for _ in range(pages)),
        boxes=tuple(() for _ in range(pages)),
        tables=tables,
        dpi=200,
        pages_ocr=pages,
    )


HTML_TABLE = Table(
    format="html",
    raw="<table><tr><td>Festgesetzt</td><td>12.345,00</td></tr>"
    "<tr><td>Abzug</td><td>-9.876,00</td></tr></table>",
    grid=(("Festgesetzt", "12.345,00"), ("Abzug", "-9.876,00")),
)


def test_cells_carry_page_table_row_column() -> None:
    cells = cells_from_variant(_variant(((HTML_TABLE,),)))
    assert cells == [
        Cell(page=1, table=0, row=0, col=0, text="Festgesetzt"),
        Cell(page=1, table=0, row=0, col=1, text="12.345,00"),
        Cell(page=1, table=0, row=1, col=0, text="Abzug"),
        Cell(page=1, table=0, row=1, col=1, text="-9.876,00"),
    ]


def test_cells_from_several_tables_and_pages() -> None:
    cells = cells_from_variant(_variant(((HTML_TABLE, HTML_TABLE), (HTML_TABLE,))))
    assert len(cells) == 12
    assert {(cell.page, cell.table) for cell in cells} == {(1, 0), (1, 1), (2, 0)}


def test_empty_variant_has_no_cells() -> None:
    assert cells_from_variant(_variant(((),))) == []


def test_has_digit() -> None:
    assert has_digit("12.345,00")
    assert has_digit("Zi.Nr.: A 211")
    assert not has_digit("Festgesetzt")
    assert not has_digit("")


def test_only_cells_with_digits_are_extracted() -> None:
    extractor = EchoExtractor()
    schema = ExtractionSchema(labels={"amount": "Geldbetrag"})
    results = extract_cells(_variant(((HTML_TABLE,),)), extractor, schema)
    texts = [cell.text for cell, _entity in results]
    assert texts == ["12.345,00", "-9.876,00"]
    assert "batch:2" in extractor.seen


def test_results_keep_their_cell() -> None:
    extractor = EchoExtractor()
    schema = ExtractionSchema(labels={"amount": "Geldbetrag"})
    results = extract_cells(_variant(((HTML_TABLE,),)), extractor, schema)
    cell, entity = results[1]
    assert (cell.row, cell.col) == (1, 1)
    assert entity.text == "-9.876,00"


def test_extract_cells_without_tables() -> None:
    extractor = EchoExtractor()
    schema = ExtractionSchema(labels={"amount": "Geldbetrag"})
    assert extract_cells(_variant(((),)), extractor, schema) == []


def test_cells_use_the_pts_grid_not_the_raw_text() -> None:
    table = Table(
        format="ots",
        raw="<fcel>Abzug<fcel>-9.876,00<nl>",
        grid=(("Abzug", "-9.876,00"),),
    )
    cells = cells_from_variant(_variant(((table,),)))
    assert [cell.text for cell in cells] == ["Abzug", "-9.876,00"]


@pytest.mark.parametrize("text", ["", "  ", "Festgesetzt"])
def test_no_digit_cells_are_skipped_quietly(text: str) -> None:
    table = Table(format="html", raw="", grid=((text,),))
    extractor = EchoExtractor()
    schema = ExtractionSchema(labels={"amount": "Geldbetrag"})
    assert extract_cells(_variant(((table,),)), extractor, schema) == []
    assert extractor.seen == []
