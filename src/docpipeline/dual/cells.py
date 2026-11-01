"""Zellebene mit Kopfzeilen-Kontext (S1, B1/B2/E4).

Eine nackte Zahl in einer Zelle trägt keine Bedeutung; das Modell braucht den
Zeilen- und Spaltenkopf. Der Extraktor sieht deshalb
``<Zeilenkopf> — <Spaltenkopf>: <Wert>``. Treffer werden anschließend wieder auf
den reinen Zellwert abgebildet, damit Offsets im Zelltext gelten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from docpipeline.dual.engines import Variant
from docpipeline.dual.values import number_key
from docpipeline.records import Entity
from docpipeline.schema import ExtractionSchema

_DIGIT = re.compile(r"\d")
_SEP = " — "
_VALUE_SEP = ": "


@dataclass(frozen=True)
class Cell:
    page: int
    table: int
    row: int
    col: int
    text: str


@dataclass(frozen=True)
class _Candidate:
    cell: Cell
    context: str


def has_digit(text: str) -> bool:
    return bool(_DIGIT.search(text))


def cells_from_variant(variant: Variant) -> list[Cell]:
    """Alle Zellen eines Dokuments, in Lesereihenfolge je Seite und Tabelle."""
    cells: list[Cell] = []
    for page_index, tables in enumerate(variant.tables, start=1):
        for table_index, table in enumerate(tables):
            for row_index, row in enumerate(table.grid):
                for col_index, text in enumerate(row):
                    if not text.strip():
                        continue
                    cells.append(
                        Cell(
                            page=page_index,
                            table=table_index,
                            row=row_index,
                            col=col_index,
                            text=text.strip(),
                        )
                    )
    return cells


def cell_context(grid: tuple[tuple[str, ...], ...], row: int, col: int) -> str:
    """Zeilen- und Spaltenkopf vor den Wert stellen; leere Köpfe entfallen."""
    value = grid[row][col].strip()
    row_header = _row_header(grid, row, col)
    column_header = _column_header(grid, row, col)
    head = _SEP.join(part for part in (row_header, column_header) if part)
    if not head:
        return value
    return f"{head}{_VALUE_SEP}{value}"


def extract_cells(
    variant: Variant, extractor: Any, schema: ExtractionSchema
) -> list[tuple[Cell, Entity]]:
    """Extrahiert je Zelle mit Ziffer; Treffer gelten im reinen Zellwert (E4)."""
    candidates: list[_Candidate] = []
    for page_index, tables in enumerate(variant.tables, start=1):
        for table_index, table in enumerate(tables):
            for row_index, row in enumerate(table.grid):
                for col_index, text in enumerate(row):
                    value = text.strip()
                    if not value or not has_digit(value):
                        continue
                    cell = Cell(
                        page=page_index,
                        table=table_index,
                        row=row_index,
                        col=col_index,
                        text=value,
                    )
                    candidates.append(
                        _Candidate(
                            cell=cell,
                            context=cell_context(table.grid, row_index, col_index),
                        )
                    )
    if not candidates:
        return []
    labels = schema.for_model()
    texts = [candidate.context for candidate in candidates]
    batched = getattr(extractor, "extract_many", None)
    groups = (
        batched(texts, labels)
        if callable(batched)
        else [extractor.extract(text, labels) for text in texts]
    )
    results: list[tuple[Cell, Entity]] = []
    for candidate, entities in zip(candidates, groups, strict=False):
        for entity in entities:
            mapped = _map_back(entity, candidate.cell.text)
            if mapped is not None:
                results.append((candidate.cell, mapped))
    return results


def _map_back(entity: Entity, value: str) -> Entity | None:
    """Treffer auf den Zellwert abbilden; fremde Zahlen verwerfen."""
    position = value.find(entity.text)
    if position >= 0:
        return entity.model_copy(update={"start": position, "end": position + len(entity.text)})
    if number_key(entity.text) == number_key(value):
        return entity.model_copy(update={"text": value, "start": 0, "end": len(value)})
    return None


def _row_header(grid: tuple[tuple[str, ...], ...], row: int, col: int) -> str:
    for index, text in enumerate(grid[row]):
        if index == col:
            continue
        if text.strip() and not has_digit(text):
            return text.strip()
    return ""


def _column_header(grid: tuple[tuple[str, ...], ...], row: int, col: int) -> str:
    if row == 0 or not grid:
        return ""
    head_row = grid[0]
    if col >= len(head_row):
        return ""
    return head_row[col].strip()
