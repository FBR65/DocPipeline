"""DocPipeline — Dokumenten-Extraktion: OCR (OpenAI-kompatibel) → Chunking → GLiNER2 → Dedup."""

from __future__ import annotations


def main() -> None:
    """Einstiegspunkt der CLI (Import bleibt schlank: kein typer beim Paketimport)."""
    from docpipeline.cli import main as _main

    _main()


__all__ = ["main"]
