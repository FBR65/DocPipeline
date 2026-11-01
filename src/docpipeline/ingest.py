"""Seiten aus PDF oder Bild gewinnen (B1, B3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from docpipeline.config import Settings
from docpipeline.errors import EmptyFileError, UnsupportedFormatError

PDF_SUFFIXES = frozenset({".pdf"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"})


@dataclass(frozen=True)
class Page:
    page_no: int
    text: str | None = None
    image: bytes | None = None


def render_pages(path: str | Path, settings: Settings) -> list[Page]:
    """Liefert je Seite Text (aus dem Textlayer) oder ein PNG für die OCR."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in PDF_SUFFIXES and suffix not in IMAGE_SUFFIXES:
        raise UnsupportedFormatError(f"Endung {suffix or '(ohne)'} wird nicht verarbeitet")
    if not source.is_file() or source.stat().st_size == 0:
        raise EmptyFileError(f"Datei fehlt oder ist leer: {source}")
    if suffix in IMAGE_SUFFIXES:
        return [Page(page_no=1, text=None, image=source.read_bytes())]
    return _render_pdf(source, settings)


def _render_pdf(source: Path, settings: Settings) -> list[Page]:
    pages: list[Page] = []
    document: Any = pymupdf.open(source)  # type: ignore[no-untyped-call]
    with document:
        for number in range(1, document.page_count + 1):
            page = document[number - 1]
            text: str | None = None
            if settings.ocr_mode == "auto":
                layer = page.get_text("text").strip()
                if len(layer) >= settings.min_text_layer_chars:
                    text = layer
            if text is not None:
                pages.append(Page(page_no=number, text=text, image=None))
                continue
            pixmap = page.get_pixmap(dpi=settings.dpi)
            pages.append(Page(page_no=number, text=None, image=pixmap.tobytes("png")))
    return pages
