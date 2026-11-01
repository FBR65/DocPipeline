"""Fehlertypen der Pipeline."""

from __future__ import annotations


class DocPipelineError(Exception):
    """Basisfehler des Systems."""


class OcrError(DocPipelineError):
    """OCR-Aufruf endgültig fehlgeschlagen."""

    def __init__(self, message: str, page: int, status: int | None = None) -> None:
        super().__init__(message)
        self.page = page
        self.status = status


class UnsupportedFormatError(DocPipelineError):
    """Dateiendung wird nicht verarbeitet."""


class EmptyFileError(DocPipelineError):
    """Datei fehlt oder ist leer."""


class PathError(DocPipelineError):
    """Pfad liegt außerhalb der erlaubten Basis."""


class SchemaError(DocPipelineError):
    """Schema-Datei ist ungültig."""
