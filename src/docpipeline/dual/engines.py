"""Zwei OCR-Engines, Phasenlauf je Engine (B1, E1, D2, D3, D11)."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pymupdf

from docpipeline.config import Settings
from docpipeline.dual.formats import Element, OcrPage, Table, parse_dots, parse_ots
from docpipeline.errors import OcrError
from docpipeline.ocr import ChatClient


def open_pdf(source: Path) -> Any:
    """Öffnet ein PDF; pymupdf ist nicht typisiert."""
    return pymupdf.open(source)  # type: ignore[no-untyped-call]


PAGE_SEP = "\n\n"

DOTS_PROMPT = """Please output the layout information from the PDF image, including each layout element's bbox, its category, and the corresponding text content within the bbox.

1. Bbox format: [x1, y1, x2, y2]

2. Layout Categories: The possible categories are ['Caption', 'Footnote', 'Formula', 'List-item', 'Page-footer', 'Page-header', 'Picture', 'Section-header', 'Table', 'Text', 'Title'].

3. Text Extraction & Formatting Rules:
    - Picture: For the 'Picture' category, the text field should be omitted.
    - Formula: Format its text as LaTeX.
    - Table: Format its text as HTML.
    - All Others (Text, Title, etc.): Format their text as Markdown.

4. Constraints:
    - The output text must be the original text from the image, with no translation.
    - All layout elements must be sorted according to human reading order.

5. Final Output: The entire output must be a single JSON object.
"""


class DualSettings(Settings):
    """Konfiguration des Doppellaufs, erbt alle Felder der Basis."""

    engine_a_model: str = "paddleocr-vl"
    engine_a_dpi: int = 300
    engine_a_prompt: str = ""

    engine_b_base_url: str | None = None
    engine_b_model: str = "dots-mocr"
    engine_b_dpi: int = 200
    engine_b_prompt: str = DOTS_PROMPT
    engine_b_max_tokens: int = 8000

    engine_c_dpi: int = 300
    engine_c_min_confidence: float = 0.5

    dual_workers: int = 2
    dual_verify: bool = True
    dual_engine_c: bool = True


@runtime_checkable
class ChatLike(Protocol):
    """Was die Engines vom HTTP-Client brauchen (ersetzbar in Tests)."""

    model: str

    def complete(
        self, image: bytes, prompt: str, page_no: int = 1, max_tokens: int | None = None
    ) -> tuple[str, str | None]: ...

    def ping(self) -> bool: ...

    def close(self) -> None: ...


@runtime_checkable
class OcrEngine(Protocol):
    name: str
    dpi: int

    def describe_page(self, image: bytes, page_no: int = 1) -> OcrPage: ...

    def ping(self) -> bool: ...


class PaddleEngine:
    """Text-Engine: Fließtext, optional OTS-Markup bei ``Table Recognition:``."""

    def __init__(
        self,
        settings: DualSettings,
        chat: ChatLike | None = None,
        prompt: str | None = None,
        dpi: int | None = None,
    ) -> None:
        self.name = settings.engine_a_model
        self.model = settings.engine_a_model
        self.dpi = dpi or settings.engine_a_dpi
        self._prompt = prompt or settings.engine_a_prompt or settings.ocr_prompt
        self._chat = chat or ChatClient(settings, model=self.name)

    def describe_page(self, image: bytes, page_no: int = 1) -> OcrPage:
        text, finish = self._chat.complete(image, self._prompt, page_no=page_no)
        if finish not in (None, "stop"):
            raise OcrError(f"Antwort abgeschnitten (finish_reason={finish})", page=page_no)
        return parse_ots(text, page_no)

    def ping(self) -> bool:
        return self._chat.ping()

    def close(self) -> None:
        self._chat.close()


class DotsEngine:
    """Layout-Engine: JSON mit Boxen, Kategorien, HTML-Tabellen."""

    def __init__(
        self,
        settings: DualSettings,
        chat: ChatLike | None = None,
        prompt: str | None = None,
        dpi: int | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.name = settings.engine_b_model
        self.model = settings.engine_b_model
        self.dpi = dpi or settings.engine_b_dpi
        self._prompt = prompt if prompt is not None else settings.engine_b_prompt
        self._max_tokens = max_tokens or settings.engine_b_max_tokens
        self._chat = chat or ChatClient(
            settings,
            base_url=settings.engine_b_base_url,
            model=self.name,
        )

    def describe_page(self, image: bytes, page_no: int = 1) -> OcrPage:
        text, finish = self._chat.complete(
            image, self._prompt, page_no=page_no, max_tokens=self._max_tokens
        )
        if finish not in (None, "stop"):
            raise OcrError(f"Layout-Antwort abgeschnitten (finish_reason={finish})", page=page_no)
        return parse_dots(text, page_no)

    def ping(self) -> bool:
        return self._chat.ping()

    def close(self) -> None:
        self._chat.close()


@dataclass(frozen=True)
class Variant:
    """Text einer Quelle über das ganze Dokument, mit Offsets je Seite."""

    name: str
    page_texts: tuple[str, ...]
    text: str
    boxes: tuple[tuple[Element, ...], ...]
    tables: tuple[tuple[Table, ...], ...]
    dpi: int | None
    pages_ocr: int

    def page_offsets(self) -> list[int]:
        offsets: list[int] = []
        position = 0
        for page_text in self.page_texts:
            offsets.append(position)
            position += len(page_text) + len(PAGE_SEP)
        return offsets

    def page_for(self, offset: int) -> int | None:
        offsets = self.page_offsets()
        if not offsets:
            return None
        index = 0
        for position, start in enumerate(offsets):
            if offset >= start:
                index = position
        return index + 1


Renderer = Callable[[int, int], bytes]


class DualOcr:
    """Führt beide Engines über alle Seiten, je Engine eine Phase (D3)."""

    def __init__(
        self,
        settings: DualSettings,
        engines: list[OcrEngine],
        renderer: Renderer | None = None,
        workers: int | None = None,
    ) -> None:
        if not engines:
            raise ValueError("mindestens eine Engine nötig")
        self._settings = settings
        self.engines = engines
        self._renderer = renderer
        self._workers = max(workers or settings.dual_workers, 1)

    def variants(self, path: str | Path) -> list[Variant]:
        source = Path(path)
        document = open_pdf(source)
        try:
            pages = document.page_count
            text_layers = [document[index].get_text("text").strip() for index in range(pages)]
            renderer = self._renderer or (
                lambda page_no, dpi: document[page_no - 1].get_pixmap(dpi=dpi).tobytes("png")
            )
            variants = [self._run_engine(engine, pages, renderer) for engine in self.engines]
            if any(len(layer) >= self._settings.min_text_layer_chars for layer in text_layers):
                page_texts = tuple(
                    layer if len(layer) >= self._settings.min_text_layer_chars else ""
                    for layer in text_layers
                )
                variants.append(
                    Variant(
                        name="text_layer",
                        page_texts=page_texts,
                        text=PAGE_SEP.join(page_texts),
                        boxes=tuple(() for _ in range(pages)),
                        tables=tuple(() for _ in range(pages)),
                        dpi=None,
                        pages_ocr=0,
                    )
                )
            return variants
        finally:
            document.close()

    def close(self) -> None:
        """Schließt die HTTP-Clients beider Engines."""
        for engine in self.engines:
            closer = getattr(engine, "close", None)
            if callable(closer):
                closer()

    def __enter__(self) -> DualOcr:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _run_engine(self, engine: OcrEngine, pages: int, renderer: Renderer) -> Variant:
        numbers = list(range(1, pages + 1))
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            results = list(
                pool.map(
                    lambda page_no: engine.describe_page(
                        renderer(page_no, engine.dpi), page_no=page_no
                    ),
                    numbers,
                )
            )
        page_texts = tuple(result.text for result in results)
        return Variant(
            name=engine.name,
            page_texts=page_texts,
            text=PAGE_SEP.join(page_texts),
            boxes=tuple(result.boxes for result in results),
            tables=tuple(result.tables for result in results),
            dpi=engine.dpi,
            pages_ocr=len(results),
        )
