"""B2 — Strukturformate beider Engines: dots-JSON/HTML und paddle-OTS."""

from __future__ import annotations

import json

import pytest

from docpipeline.dual.formats import Element, OcrPage, Table, html_to_text, parse_dots, parse_ots
from docpipeline.errors import OcrError

# Ausschnitt einer echten dots.mocr-Antwort (Scanseite, 200 dpi).
DOTS_ANSWER = [
    {"bbox": [31, 19, 111, 34], "category": "Page-header", "text": "Finanzamt Musterstadt"},
    {"bbox": [63, 95, 86, 118], "category": "Picture"},
    {"bbox": [149, 19, 806, 35], "category": "Page-header", "text": "05.03.2024"},
    {
        "bbox": [90, 225, 750, 591],
        "category": "Table",
        "text": (
            "<table><tr><td>PO</td><td>4711</td></tr>"
            "<tr><td>erstellt</td><td>01.2-24</td></tr></table>"
        ),
    },
    {"bbox": [345, 601, 494, 617], "category": "Text", "text": "Bescheid für 1999"},
]

OTS_ANSWER = (
    "<fcel>Festgesetzt werden<fcel>54.322,00<fcel>-56,78<nl>"
    "<fcel>ab Steuerabzug von Lohn<fcel>12.345,00<fcel>-56,78<nl>"
    "<ecel><ecel><fcel>2.343,00<nl>"
)


def test_parse_dots_text_excludes_markup() -> None:
    page = parse_dots(DOTS_ANSWER, page_no=1)
    assert isinstance(page, OcrPage)
    assert "Finanzamt Musterstadt" in page.text
    assert "Bescheid für 1999" in page.text
    assert "PO 4711" in page.text
    assert "<table>" not in page.text
    assert "<td>" not in page.text


def test_parse_dots_boxes_keep_every_element() -> None:
    page = parse_dots(DOTS_ANSWER, page_no=3)
    assert len(page.boxes) == 5
    assert all(box.page_no == 3 for box in page.boxes)
    picture = next(box for box in page.boxes if box.category == "Picture")
    assert picture.text == ""
    assert picture.bbox == (63.0, 95.0, 86.0, 118.0)


def test_parse_dots_tables_keep_html_and_grid() -> None:
    page = parse_dots(DOTS_ANSWER)
    assert len(page.tables) == 1
    table = page.tables[0]
    assert isinstance(table, Table)
    assert table.format == "html"
    assert "<table>" in table.raw
    assert table.grid == (("PO", "4711"), ("erstellt", "01.2-24"))


def test_parse_dots_accepts_fenced_json_string() -> None:
    fenced = "```json\n" + json.dumps(DOTS_ANSWER) + "\n```"
    assert parse_dots(fenced).boxes == parse_dots(DOTS_ANSWER).boxes


def test_parse_dots_accepts_object_with_elements() -> None:
    page = parse_dots({"elements": DOTS_ANSWER})
    assert len(page.boxes) == 5


def test_parse_dots_rejects_broken_json() -> None:
    with pytest.raises(OcrError):
        parse_dots("das ist kein json")


def test_parse_ots_strips_markers() -> None:
    page = parse_ots(OTS_ANSWER, page_no=2)
    assert "<fcel>" not in page.text
    assert "<nl>" not in page.text
    assert page.text.splitlines()[0] == "Festgesetzt werden 54.322,00 -56,78"
    assert page.page_no == 2


def test_parse_ots_grid_has_rows_and_cells() -> None:
    page = parse_ots(OTS_ANSWER)
    table = page.tables[0]
    assert table.format == "ots"
    assert len(table.grid) == 3
    assert table.grid[0] == ("Festgesetzt werden", "54.322,00", "-56,78")
    assert table.grid[2] == ("", "", "2.343,00")


def test_parse_ots_without_markers_keeps_text() -> None:
    page = parse_ots("nur Text")
    assert page.text.strip() == "nur Text"
    assert page.tables == ()


def test_html_to_text_flattens_cells() -> None:
    assert html_to_text("<table><tr><td>A</td><td>1,00</td></tr><tr><td>B</td></tr></table>") == (
        "A 1,00 B"
    )


def test_element_is_hashable_dataclass() -> None:
    element = Element(page_no=1, bbox=(0.0, 1.0, 2.0, 3.0), category="Text", text="x")
    assert element in {element}
