"""Strukturformate der beiden Engines (B2).

Engine B (dots.mocr) liefert Layout-JSON mit HTML für Tabellen.
Engine A (paddleocr-vl) liefert Fließtext oder, mit dem offiziellen
``Table Recognition:``-Prompt, OTS-Markup (``<fcel>``, ``<lcel>``, ``<ecel>``,
``<nl>``). Beide Formen werden auf ``text`` und ein Zellraster abgebildet.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Literal

from docpipeline.errors import OcrError
from docpipeline.ocr import strip_fences

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
_OTS = re.compile(r"<(fcel|lcel|ecel|nl)>([^<]*)")
_CATEGORY_TEXT = "text"
_CATEGORY_TABLE = "table"
_BBOX_PARTS = 4


@dataclass(frozen=True)
class Table:
    """Tabelle aus einer Engine. ``grid`` ist immer gefüllt, ``raw`` bleibt erhalten."""

    format: Literal["html", "ots"]
    raw: str
    grid: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class Element:
    page_no: int
    bbox: tuple[float, float, float, float]
    category: str
    text: str = ""
    score: float = 0.0


@dataclass(frozen=True)
class OcrPage:
    page_no: int
    text: str
    boxes: tuple[Element, ...] = ()
    tables: tuple[Table, ...] = field(default=())


def html_to_text(html: str) -> str:
    """Entfernt Markup; Zellen werden mit einem Leerzeichen verbunden."""
    return _SPACES.sub(" ", _TAGS.sub(" ", html)).strip()


class _GridParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(_SPACES.sub(" ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def html_grid(html: str) -> tuple[tuple[str, ...], ...]:
    parser = _GridParser()
    parser.feed(html)
    parser.close()
    return tuple(tuple(cells) for cells in parser.rows)


def parse_dots(payload: str | dict[str, Any] | list[Any], page_no: int = 1) -> OcrPage:
    """Wandelt eine dots.mocr-Antwort in ``OcrPage`` um."""
    data: Any = payload
    if isinstance(payload, str):
        try:
            data = json.loads(strip_fences(payload))
        except ValueError as exc:
            raise OcrError("Layout-Antwort ist kein gültiges JSON", page=page_no) from exc
    elements = (
        (data.get("elements") or data.get("layout") or []) if isinstance(data, dict) else data
    )
    if not isinstance(elements, list):
        raise OcrError("Layout-Antwort enthält keine Elementliste", page=page_no)
    return _page_from_elements(elements, page_no)


def _page_from_elements(elements: list[Any], page_no: int) -> OcrPage:

    boxes: list[Element] = []
    texts: list[str] = []
    tables: list[Table] = []
    for raw_element in elements:
        if not isinstance(raw_element, dict):
            continue
        bbox = _bbox(raw_element.get("bbox"))
        category = str(raw_element.get("category") or "")
        body = raw_element.get("text")
        text = body if isinstance(body, str) else ""
        boxes.append(Element(page_no=page_no, bbox=bbox, category=category, text=text))
        if category.lower() == _CATEGORY_TABLE and text:
            tables.append(Table(format="html", raw=text, grid=html_grid(text)))
            flattened = html_to_text(text)
        else:
            flattened = html_to_text(text) if "<" in text else text.strip()
        if flattened:
            texts.append(flattened)
    return OcrPage(page_no=page_no, text="\n".join(texts), boxes=tuple(boxes), tables=tuple(tables))


def parse_ots(raw: str, page_no: int = 1) -> OcrPage:
    """Wandelt OTS-Markup (oder Klartext) in ``OcrPage`` um."""
    if "<fcel>" not in raw and "<nl>" not in raw:
        return OcrPage(page_no=page_no, text=raw.strip())
    rows: list[list[str]] = []
    row: list[str] = []
    for kind, content in _OTS.findall(raw):
        if kind == "nl":
            if row:
                rows.append(row)
            row = []
            continue
        row.append(_SPACES.sub(" ", content).strip())
    if row:
        rows.append(row)
    grid = tuple(tuple(cells) for cells in rows)
    lines = [" ".join(cell for cell in cells if cell) for cells in grid]
    table = Table(format="ots", raw=raw, grid=grid)
    return OcrPage(
        page_no=page_no,
        text="\n".join(line for line in lines if line),
        tables=(table,),
    )


def _bbox(value: Any) -> tuple[float, float, float, float]:
    parts = value if isinstance(value, (list, tuple)) else ()
    if len(parts) < _BBOX_PARTS:
        return (0.0, 0.0, 0.0, 0.0)
    try:
        x0, y0, x1, y1 = (float(part) for part in parts[:_BBOX_PARTS])
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0, 0.0)
    return (x0, y0, x1, y1)
