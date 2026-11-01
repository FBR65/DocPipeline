"""B1/B3 — Seitenaufbereitung."""

from __future__ import annotations

from pathlib import Path

import pytest

from docpipeline.config import Settings
from docpipeline.errors import EmptyFileError, UnsupportedFormatError
from docpipeline.ingest import Page, render_pages


def test_text_layer_page_needs_no_image(settings: Settings, text_pdf: Path) -> None:
    settings.min_text_layer_chars = 5
    pages = render_pages(text_pdf, settings)
    assert len(pages) == 1
    page = pages[0]
    assert isinstance(page, Page)
    assert page.text is not None
    assert "ACME" in page.text
    assert page.image is None
    assert page.page_no == 1


def test_blank_page_gets_png_image(settings: Settings, blank_pdf: Path) -> None:
    pages = render_pages(blank_pdf, settings)
    assert pages[0].text is None
    assert pages[0].image is not None
    assert pages[0].image.startswith(b"\x89PNG")


def test_ocr_mode_always_ignores_text_layer(
    settings: Settings, text_pdf: Path
) -> None:
    settings.ocr_mode = "always"
    pages = render_pages(text_pdf, settings)
    assert pages[0].text is None
    assert pages[0].image is not None


def test_short_text_layer_counts_as_empty(settings: Settings, text_pdf: Path) -> None:
    settings.min_text_layer_chars = 1000
    pages = render_pages(text_pdf, settings)
    assert pages[0].text is None


def test_image_file_is_single_page(settings: Settings, tmp_path: Path) -> None:
    png = tmp_path / "scan.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    pages = render_pages(png, settings)
    assert len(pages) == 1
    assert pages[0].page_no == 1
    assert pages[0].text is None
    assert pages[0].image == png.read_bytes()


def test_unsupported_extension(settings: Settings, tmp_path: Path) -> None:
    txt = tmp_path / "notiz.txt"
    txt.write_text("hallo", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError, match="txt"):
        render_pages(txt, settings)


def test_empty_file(settings: Settings, tmp_path: Path) -> None:
    empty = tmp_path / "leer.pdf"
    empty.write_bytes(b"")
    with pytest.raises(EmptyFileError):
        render_pages(empty, settings)


def test_missing_file(settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(EmptyFileError):
        render_pages(tmp_path / "weg.pdf", settings)
