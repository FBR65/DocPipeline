"""RapidOCR als dritter Leser und als Prüfleser (S2, B3, E3).

CPU, ONNX, kein Sprachmodell: 3,4 s je Seite gemessen. Liefert Text, Boxen und
Konfidenz je Zeile. Fehlt die Abhängigkeit, meldet das Objekt sich als nicht
verfügbar statt zu werfen.
"""

from __future__ import annotations

import io
from typing import Any

from docpipeline.dual.engines import DualSettings
from docpipeline.dual.formats import Element, OcrPage
from docpipeline.errors import OcrError

_QUAD = 4


class RapidEngine:
    name = "rapidocr"
    model = "rapidocr (PP-OCR, ONNX)"

    def __init__(
        self,
        settings: DualSettings,
        engine: Any = None,
        dpi: int | None = None,
    ) -> None:
        self.dpi = dpi or settings.engine_c_dpi
        self._settings = settings
        self._engine = engine

    @staticmethod
    def available() -> bool:
        try:
            import rapidocr  # noqa: F401
        except Exception:
            return False
        return True

    def _get(self) -> Any:
        if self._engine is None:
            if not self.available():
                raise OcrError("RapidOCR ist nicht installiert (Extra 'rapid')", page=0)
            from rapidocr import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def describe_page(self, image: bytes, page_no: int = 1) -> OcrPage:
        try:
            result = self._get()(self._decode(image))
        except OcrError:
            raise
        except Exception as exc:
            raise OcrError(f"RapidOCR fehlgeschlagen ({type(exc).__name__})", page=page_no) from exc

        texts = _as_list(getattr(result, "txts", None))
        scores = _as_list(getattr(result, "scores", None))
        boxes = _as_list(getattr(result, "boxes", None))
        elements = [
            Element(
                page_no=page_no,
                bbox=_bbox(boxes[index]) if index < len(boxes) else (0.0, 0.0, 0.0, 0.0),
                category="Text",
                text=str(text),
                score=float(scores[index]) if index < len(scores) else 0.0,
            )
            for index, text in enumerate(texts)
        ]
        return OcrPage(
            page_no=page_no,
            text="\n".join(str(text) for text in texts),
            boxes=tuple(elements),
            tables=(),
        )

    def ping(self) -> bool:
        return self.available()

    def close(self) -> None:
        self._engine = None

    @staticmethod
    def _decode(image: bytes) -> Any:
        """PNG-Bytes als BGR-Array, wie es die ONNX-Pipeline erwartet.

        Fehlt Pillow oder numpy (Extra nicht installiert), gehen die Bytes
        unverändert weiter; das echte RapidOCR lehnt sie dann mit einem Fehler
        ab, ein Doppelgänger in Tests arbeitet weiter.
        """
        try:
            import numpy as np
            from PIL import Image
        except Exception:
            return image
        try:
            with Image.open(io.BytesIO(image)) as handle:
                rgb = np.array(handle.convert("RGB"))
        except Exception:
            return image
        return rgb[:, :, ::-1]


def _as_list(value: Any) -> list[Any]:
    """RapidOCR liefert numpy-Arrays; ``value or ()`` wäre dort ein Fehler."""
    if value is None:
        return []
    return [item for item in value]


def _bbox(box: Any) -> tuple[float, float, float, float]:
    points = list(box)[:_QUAD] if isinstance(box, (list, tuple)) else []
    if not points:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return (min(xs), min(ys), max(xs), max(ys))
