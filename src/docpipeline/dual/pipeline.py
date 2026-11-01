"""Doppellauf bis zum Record (B7)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter
from typing import Protocol, cast

import pymupdf

from docpipeline.chunker import chunk
from docpipeline.config import Settings
from docpipeline.dual.cells import extract_cells
from docpipeline.dual.engines import DualOcr, DualSettings, OcrEngine, Variant, open_pdf
from docpipeline.dual.formats import Element
from docpipeline.dual.union import TEXT_LAYER, unite
from docpipeline.dual.verify import Crop, verify_entities
from docpipeline.errors import EmptyFileError, UnsupportedFormatError
from docpipeline.extractor import EntityExtractor
from docpipeline.ingest import IMAGE_SUFFIXES, PDF_SUFFIXES
from docpipeline.records import (
    CellInfo,
    DocumentRecord,
    EngineInfo,
    Entity,
    OcrInfo,
    SourceRef,
)
from docpipeline.schema import ExtractionSchema

VERIFY_DPI = 300
FAST_READER = "rapidocr"


class VariantSource(Protocol):
    def variants(self, path: str | Path) -> list[Variant]: ...


class DualPipeline:
    """Zwei Engines, Vereinigung, optional Regionen-Nachlesen."""

    def __init__(  # noqa: PLR0913, PLR0917 (Injektionspunkte für Tests)
        self,
        settings: DualSettings | Settings,
        schema: ExtractionSchema,
        dual: VariantSource | DualOcr,
        extractor: EntityExtractor,
        verify: bool | None = None,
        verify_engine: OcrEngine | None = None,
        crop: Crop | None = None,
        source_name: str | None = None,
    ) -> None:
        self._settings = settings
        self._schema = schema
        self._dual = dual
        self._extractor = extractor
        self._verify = getattr(settings, "dual_verify", True) if verify is None else verify
        self._verify_engine = verify_engine
        self._crop = crop
        self._source_name = source_name

    def run(self, path: str | Path) -> DocumentRecord:
        source = Path(path)
        _check_source(source)
        timings: dict[str, float] = {}

        started = perf_counter()
        variants = self._dual.variants(source)
        timings["ocr"] = _ms(started)

        started = perf_counter()
        labels = self._schema.for_model()
        per_variant: list[tuple[str, list[Entity]]] = []
        for variant in variants:
            per_variant.append((variant.name, self._extract_variant(variant, labels)))
        entities, warnings = unite(per_variant)
        timings["extract"] = _ms(started)

        if getattr(self._settings, "dual_engine_c", False) and not self._has_fast_reader():
            warnings = sorted({*warnings, "engine_c_unavailable"})

        if self._verify and entities:
            started = perf_counter()
            engine = self._verify_engine or self._default_verify_engine()
            if engine is None:
                warnings = sorted({*warnings, "verify_available:false"})
            else:
                entities, verify_warnings = verify_entities(
                    entities,
                    self._boxes_by_page(variants),
                    self._crop or self._crop_from(source),
                    engine,
                )
                warnings = sorted({*warnings, *verify_warnings})
            timings["verify"] = _ms(started)

        page_count = max((len(variant.page_texts) for variant in variants), default=0)
        return DocumentRecord(
            source=source.name if self._source_name is None else self._source_name,
            sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            pages=page_count,
            ocr=OcrInfo(
                model=" + ".join(engine.name for engine in self._engines(variants)),
                pages_ocr=sum(variant.pages_ocr for variant in variants),
                engines=[
                    EngineInfo(
                        name=variant.name,
                        model=variant.name,
                        dpi=variant.dpi,
                        pages=len(variant.page_texts),
                    )
                    for variant in variants
                    if variant.name != TEXT_LAYER
                ],
            ),
            text=self._canonical_text(variants),
            variants={variant.name: variant.text for variant in variants},
            entities=entities,
            cells=self._cell_summary(variants),
            warnings=warnings,
            timings_ms=timings,
        )

    # ------------------------------------------------------------------ intern

    def _extract_variant(self, variant: Variant, labels: dict[str, str]) -> list[Entity]:
        found: list[Entity] = []
        for piece in chunk(
            variant.text,
            window_words=self._settings.window_words,
            overlap_words=self._settings.overlap_words,
        ):
            for entity in self._extractor.extract(piece.text, labels):
                start = entity.start + piece.start
                found.append(
                    entity.model_copy(
                        update={
                            "start": start,
                            "end": start + len(entity.text),
                            "page": variant.page_for(start),
                            "engine": variant.name,
                        }
                    )
                )
        for cell, entity in extract_cells(variant, self._extractor, self._schema):
            start = entity.start
            found.append(
                entity.model_copy(
                    update={
                        "start": start,
                        "end": start + len(entity.text),
                        "page": cell.page,
                        "engine": variant.name,
                        "sources": [
                            SourceRef(
                                engine=variant.name,
                                start=start,
                                end=start + len(entity.text),
                                score=entity.score,
                                zelle=(cell.table, cell.row, cell.col),
                            )
                        ],
                    }
                )
            )
        return found

    @staticmethod
    def _canonical_text(variants: list[Variant]) -> str | None:
        for variant in variants:
            if variant.name == TEXT_LAYER and variant.text.strip():
                return variant.text
        for variant in variants:
            if variant.text.strip():
                return variant.text
        return variants[0].text if variants else None

    @staticmethod
    def _engines(variants: list[Variant]) -> list[Variant]:
        engines = [variant for variant in variants if variant.name != TEXT_LAYER]
        return engines or variants

    @staticmethod
    def _boxes_by_page(variants: list[Variant]) -> dict[int, tuple[Element, ...]]:
        """Boxen aus der Layout-Engine, von Bildpixeln in PDF-Punkte umgerechnet.

        dots.mocr liefert ``bbox`` in Pixeln des gerenderten Bildes. Für das
        Ausschneiden mit pymupdf müssen sie in Punkte (1/72 Zoll) umgerechnet
        werden, sonst entstehen ungültige Ausschnitte.
        """
        best: dict[int, tuple[Element, ...]] = {}
        for variant in variants:
            if variant.name == TEXT_LAYER:
                continue
            scale = 72.0 / float(variant.dpi or 72)
            for index, boxes in enumerate(variant.boxes, start=1):
                if not boxes or index in best:
                    continue
                best[index] = tuple(
                    Element(
                        page_no=box.page_no,
                        bbox=_scale_box(box.bbox, scale),
                        category=box.category,
                        text=box.text,
                    )
                    for box in boxes
                    if box.bbox[2] > box.bbox[0] and box.bbox[3] > box.bbox[1]
                )
        return {page: boxes for page, boxes in best.items() if boxes}

    def _default_verify_engine(self) -> OcrEngine | None:
        engines = list(getattr(self._dual, "engines", []) or [])
        for engine in engines:
            if getattr(engine, "name", "") == FAST_READER:
                return cast("OcrEngine", engine)
        return cast("OcrEngine", engines[0]) if engines else None

    def _has_fast_reader(self) -> bool:
        return any(
            getattr(engine, "name", "") == FAST_READER
            for engine in getattr(self._dual, "engines", []) or []
        )

    @staticmethod
    def _cell_summary(variants: list[Variant]) -> list[CellInfo]:
        """Je Seite und Tabelle die Maße und die Engines, die ein Raster liefern."""
        found: dict[tuple[int, int], tuple[int, int, set[str]]] = {}
        for variant in variants:
            for page_no, tables in enumerate(variant.tables, start=1):
                for table_no, table in enumerate(tables):
                    rows = len(table.grid)
                    cols = max((len(row) for row in table.grid), default=0)
                    key = (page_no, table_no)
                    if key in found:
                        _rows, _cols, engines = found[key]
                        engines.add(variant.name)
                        continue
                    found[key] = (rows, cols, {variant.name})
        return [
            CellInfo(
                page=page_no,
                table=table_no,
                rows=rows,
                cols=cols,
                engines=sorted(engines),
            )
            for (page_no, table_no), (rows, cols, engines) in sorted(found.items())
        ]

    @staticmethod
    def _crop_from(source: Path) -> Crop:
        def crop(page_no: int, bbox: tuple[float, float, float, float]) -> bytes:
            x0, y0, x1, y1 = bbox
            clip = pymupdf.Rect(x0, y0, x1, y1)  # type: ignore[no-untyped-call]
            document = open_pdf(source)
            try:
                pixmap = document[page_no - 1].get_pixmap(dpi=VERIFY_DPI, clip=clip)
                return cast("bytes", pixmap.tobytes("png"))
            finally:
                document.close()

        return crop


def _scale_box(
    bbox: tuple[float, float, float, float], scale: float
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    return (x0 * scale, y0 * scale, x1 * scale, y1 * scale)


def _ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


def _check_source(source: Path) -> None:
    """Endung und Größe prüfen, bevor eine Engine startet (E2)."""
    suffix = source.suffix.lower()
    if suffix not in PDF_SUFFIXES and suffix not in IMAGE_SUFFIXES:
        raise UnsupportedFormatError(f"Endung {suffix or '(ohne)'} wird nicht verarbeitet")
    if not source.is_file() or source.stat().st_size == 0:
        raise EmptyFileError(f"Datei fehlt oder ist leer: {source}")
