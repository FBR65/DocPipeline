"""Ablauf: Seiten → Text → Chunks → Entitäten → Dedup → Record (B7)."""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from pathlib import Path
from time import perf_counter

from docpipeline.chunker import chunk
from docpipeline.config import Settings
from docpipeline.dedup import dedupe
from docpipeline.extractor import EntityExtractor
from docpipeline.ingest import render_pages
from docpipeline.ocr import OcrClientProto
from docpipeline.records import DocumentRecord, Entity, OcrInfo
from docpipeline.schema import ExtractionSchema

PAGE_SEP = "\n\n"


class DocumentPipeline:
    def __init__(
        self,
        settings: Settings,
        schema: ExtractionSchema,
        ocr: OcrClientProto,
        extractor: EntityExtractor,
        source_name: str | None = None,
    ) -> None:
        self._settings = settings
        self._schema = schema
        self._ocr = ocr
        self._extractor = extractor
        self._source_name = source_name

    def run(self, path: str | Path) -> DocumentRecord:
        source = Path(path)
        timings: dict[str, float] = {}
        started = perf_counter()
        pages = render_pages(source, self._settings)
        timings["render"] = _ms(started)

        started = perf_counter()
        texts: list[str] = []
        warnings: list[str] = []
        ocr_pages = 0
        for page in pages:
            if page.text is not None:
                text = page.text
            else:
                if page.image is None:
                    raise ValueError(f"Seite {page.page_no} hat weder Text noch Bild")
                text = self._ocr.ocr_page(page.image, page_no=page.page_no)
                ocr_pages += 1
            if not text.strip():
                warnings.append(f"empty_page:{page.page_no}")
            texts.append(text)
        timings["ocr"] = _ms(started)

        document_text = PAGE_SEP.join(texts)
        page_numbers: list[int] = []
        page_offsets: list[int] = []
        offset = 0
        for page, text in zip(pages, texts, strict=True):
            page_numbers.append(page.page_no)
            page_offsets.append(offset)
            offset += len(text) + len(PAGE_SEP)

        started = perf_counter()
        labels = self._schema.for_model()
        found: list[Entity] = []
        for piece in chunk(
            document_text,
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
                            "page": _page_for(start, page_numbers, page_offsets),
                        }
                    )
                )
        entities = dedupe(found, distance_max=self._settings.dedup_distance)
        timings["extract"] = _ms(started)

        return DocumentRecord(
            source=self._source_name or source.name,
            sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            pages=len(pages),
            ocr=OcrInfo(model=self._ocr.model, pages_ocr=ocr_pages),
            text=document_text,
            entities=entities,
            warnings=warnings,
            timings_ms=timings,
        )


def _page_for(offset: int, numbers: list[int], offsets: list[int]) -> int | None:
    if not offsets:
        return None
    index = bisect_right(offsets, offset) - 1
    return numbers[max(index, 0)]


def _ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)
