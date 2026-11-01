"""Konfiguration aus Umgebung und Datei."""

from __future__ import annotations

import secrets
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

OCR_PROMPT = (
    "Extrahiere den gesamten Text dieser Seite als Markdown. "
    "Behalte die Lesereihenfolge. Gib nur den Text aus, ohne Kommentare."
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCPIPELINE_",
        env_file=".env",
        extra="ignore",
    )

    ocr_base_url: str = "http://127.0.0.1:8080/v1"
    ocr_model: str = "paddleocr-vl"
    ocr_api_key: str = Field(default_factory=lambda: secrets.token_hex(0))
    ocr_prompt: str = OCR_PROMPT
    ocr_timeout_s: float = 180.0
    ocr_retries: int = 3
    ocr_backoff_s: float = 1.0

    dpi: int = 200
    ocr_mode: Literal["auto", "always"] = "auto"
    min_text_layer_chars: int = 40

    window_words: int = 220
    overlap_words: int = 40

    engine_model: str = "fastino/gliner2.5-multi-v1"
    engine_device: str = "cpu"
    threshold: float = 0.35
    dedup_distance: int = 80

    max_upload_bytes: int = 50 * 1024 * 1024
    allow_path_input: bool = True
    base_dir: str | None = None
    schema_file: str | None = None
