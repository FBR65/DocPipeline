"""Dokument-Record: das Ergebnis einer Verarbeitung (B7)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SourceRef(BaseModel):
    """Eine Fundstelle einer Entität in genau einer Textvariante."""

    model_config = ConfigDict(frozen=True)

    engine: str
    start: int
    end: int
    score: float = 0.0
    zelle: tuple[int, int, int] | None = None
    label: str | None = None


class Entity(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    text: str
    start: int
    end: int
    page: int | None = None
    score: float = 0.0
    normalized: str | None = None
    engine: str | None = None
    agreement: str | None = None
    verified: bool | None = None
    sources: list[SourceRef] = Field(default_factory=list)


class CellInfo(BaseModel):
    """Zusammenfassung eines Zellrasters im Record."""

    model_config = ConfigDict(frozen=True)

    page: int
    table: int
    rows: int
    cols: int
    engines: list[str] = Field(default_factory=list)


class EngineInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    model: str
    dpi: int | None = None
    pages: int = 0


class OcrInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    pages_ocr: int
    engines: list[EngineInfo] = Field(default_factory=list)


class DocumentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    sha256: str
    pages: int
    ocr: OcrInfo
    text: str | None = None
    variants: dict[str, str] = Field(default_factory=dict)
    cells: list[CellInfo] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)
