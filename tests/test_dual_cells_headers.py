"""S1 — Zellen bekommen Zeilen- und Spaltenkopf als Kontext (Label-Qualität)."""

from __future__ import annotations

from docpipeline.dual.cells import Cell, cells_from_variant, extract_cells
from docpipeline.dual.engines import Variant
from docpipeline.dual.formats import Table
from docpipeline.records import Entity
from docpipeline.schema import ExtractionSchema

GRID = (
    ("Art der Steuer", "Einkommensteuer", "Solidaritätszuschlag"),
    ("Festgesetzt", "12.345,00", "-56,78"),
    ("Abzug", "2.343,00", "-56,78"),
)


class Recorder:
    """Merkt sich den Text, den der Extraktor sieht, und gibt ihn als Treffer zurück."""

    name = "recorder"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def extract(self, text: str, labels: dict[str, str]) -> list[Entity]:
        self.seen.append(text)
        return [Entity(label="amount", text=text, start=0, end=len(text), score=0.9)]

    def extract_many(self, texts: list[str], labels: dict[str, str]) -> list[list[Entity]]:
        return [self.extract(text, labels) for text in texts]


class HeaderAware:
    """Gibt den Wert der Zelle zurück, nicht den Kontext."""

    name = "header-aware"

    def extract(self, text: str, labels: dict[str, str]) -> list[Entity]:
        value = text.rsplit(": ", 1)[-1]
        start = text.rindex(value)
        return [Entity(label="amount", text=value, start=start, end=start + len(value), score=0.9)]

    def extract_many(self, texts: list[str], labels: dict[str, str]) -> list[list[Entity]]:
        return [self.extract(text, labels) for text in texts]


def _variant(grid: tuple[tuple[str, ...], ...] = GRID) -> Variant:
    table = Table(format="html", raw="", grid=grid)
    return Variant(
        name="dots-mocr",
        page_texts=("Text",),
        text="Text",
        boxes=((),),
        tables=((table,),),
        dpi=200,
        pages_ocr=1,
    )


def test_context_carries_row_and_column_header() -> None:
    recorder = Recorder()
    extract_cells(_variant(), recorder, ExtractionSchema(labels={"amount": "Betrag"}))
    assert "Festgesetzt" in recorder.seen[0]
    assert "Einkommensteuer" in recorder.seen[0]
    assert "12.345,00" in recorder.seen[0]


def test_value_is_the_last_part_of_the_context() -> None:
    recorder = Recorder()
    extract_cells(_variant(), recorder, ExtractionSchema(labels={"amount": "Betrag"}))
    for text in recorder.seen:
        assert text.rsplit(": ", 1)[-1][0].isdigit() or text.rsplit(": ", 1)[-1][0] == "-"


def test_header_cells_themselves_are_not_extracted() -> None:
    recorder = Recorder()
    extract_cells(_variant(), recorder, ExtractionSchema(labels={"amount": "Betrag"}))
    assert len(recorder.seen) == 4, recorder.seen


def test_entities_are_mapped_back_into_the_cell() -> None:
    results = extract_cells(
        _variant(), HeaderAware(), ExtractionSchema(labels={"amount": "Betrag"})
    )
    cell, entity = results[0]
    assert entity.text == "12.345,00"
    assert cell.text[entity.start :: 1].startswith("12.345,00")
    assert entity.start == 0
    assert entity.end == len("12.345,00")


def test_cells_without_headers_still_work() -> None:
    grid = (("12.345,00",),)
    results = extract_cells(_variant(grid), HeaderAware(), ExtractionSchema(labels={"a": "x"}))
    assert len(results) == 1
    assert results[0][1].text == "12.345,00"


def test_cells_without_digits_have_no_context() -> None:
    cells = cells_from_variant(_variant())
    assert [cell for cell in cells if cell.text == "Art der Steuer"]
    recorder = Recorder()
    extract_cells(_variant(), recorder, ExtractionSchema(labels={"amount": "Betrag"}))
    assert all("Art der Steuer" not in text.split(": ")[0] for text in recorder.seen)


def test_entity_outside_the_value_is_dropped() -> None:
    class Hallucinating:
        name = "hallucinating"

        def extract(self, text: str, labels: dict[str, str]) -> list[Entity]:
            return [Entity(label="amount", text="9.999", start=0, end=5, score=0.9)]

        def extract_many(self, texts: list[str], labels: dict[str, str]) -> list[list[Entity]]:
            return [self.extract(t, labels) for t in texts]

    results = extract_cells(
        _variant(), Hallucinating(), ExtractionSchema(labels={"amount": "Betrag"})
    )
    assert results == []


def test_cell_number_kept_when_written_differently() -> None:
    class German:
        name = "german"

        def extract(self, text: str, labels: dict[str, str]) -> list[Entity]:
            return [Entity(label="amount", text="12345", start=0, end=5, score=0.9)]

        def extract_many(self, texts: list[str], labels: dict[str, str]) -> list[list[Entity]]:
            return [self.extract(t, labels) for t in texts]

    results = extract_cells(_variant(), German(), ExtractionSchema(labels={"amount": "Betrag"}))
    # Nur Zellen mit demselben Zahlenwert überleben die Abbildung.
    assert [entity.text for _cell, entity in results] == ["12.345,00"]


def test_cell_dataclass_unchanged() -> None:
    cell = Cell(page=1, table=0, row=1, col=1, text="12.345,00")
    assert cell == Cell(1, 0, 1, 1, "12.345,00")
