"""Dokument-Record: das Ergebnis einer Verarbeitung (B7)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Entity(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    text: str
    start: int
    end: int
    page: int | None = None
    score: float = 0.0


class OcrInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    pages_ocr: int


class DocumentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    sha256: str
    pages: int
    ocr: OcrInfo
    text: str | None = None
    entities: list[Entity] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)
