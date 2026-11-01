"""Gemeinsame Fixtures: PDFs, Fake-OCR, Fake-Extraktor."""

from __future__ import annotations

import base64
from pathlib import Path

import pymupdf
import pytest

from docpipeline.config import Settings
from docpipeline.records import Entity


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        ocr_base_url="http://127.0.0.1:8080/v1",
        ocr_model="paddleocr-vl",
        ocr_retries=3,
        ocr_backoff_s=0.0,
        dpi=72,
        window_words=20,
        overlap_words=5,
        threshold=0.3,
        dedup_distance=10,
        base_dir=str(tmp_path),
    )


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "text.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Rechnung RE-1 von ACME", fontsize=12)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def blank_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path)
    doc.close()
    return path


class FakeOcr:
    """Ersetzt den HTTP-Client. Text ist absichtlich eindeutig je Seite."""

    model = "fake-ocr"

    def __init__(self, texts: dict[int, str] | None = None, ping_ok: bool = True) -> None:
        self.texts = texts or {}
        self.ping_ok = ping_ok
        self.calls: list[int] = []

    def ocr_page(self, image: bytes, page_no: int = 1) -> str:
        self.calls.append(page_no)
        return self.texts.get(page_no, f"Seitentext {page_no}")

    def ping(self) -> bool:
        return self.ping_ok

    @staticmethod
    def data_url(image: bytes) -> str:
        return "data:image/png;base64," + base64.b64encode(image).decode()


class FakeExtractor:
    """Sucht je Label einen festen Text im Chunk."""

    name = "fake-extractor"

    def __init__(self, needles: dict[str, str], score: float = 0.9) -> None:
        self.needles = needles
        self.score = score
        self.seen: list[str] = []

    def extract(self, text: str, labels: dict[str, str]) -> list[Entity]:
        self.seen.append(text)
        out: list[Entity] = []
        for label, needle in self.needles.items():
            if label not in labels:
                continue
            pos = text.find(needle)
            while pos != -1:
                out.append(
                    Entity(
                        label=label,
                        text=needle,
                        start=pos,
                        end=pos + len(needle),
                        score=self.score,
                    )
                )
                pos = text.find(needle, pos + len(needle))
        return out


@pytest.fixture
def fake_ocr() -> FakeOcr:
    return FakeOcr()


@pytest.fixture
def fake_extractor() -> FakeExtractor:
    return FakeExtractor({"buyer": "ACME"})
