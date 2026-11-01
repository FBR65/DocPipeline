"""B9/E1 — die restlichen API-Pfade: Export, Fehlerabbildung, Hauptprogramm."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import docpipeline
from conftest import FakeExtractor, FakeOcr
from docpipeline import cli
from docpipeline.api import create_app
from docpipeline.config import Settings
from docpipeline.errors import OcrError
from docpipeline.schema import ExtractionSchema


def _app(settings: Settings, ocr: FakeOcr | None = None) -> TestClient:
    return TestClient(
        create_app(
            settings,
            schema=ExtractionSchema(model="fake", labels={"buyer": "Käufer"}),
            ocr=ocr or FakeOcr({1: "ACME kauft"}),
            extractor=FakeExtractor({"buyer": "ACME"}),
        )
    )


def test_export_by_path(settings: Settings, blank_pdf: Path) -> None:
    resp = _app(settings).post("/v1/export", json={"path": str(blank_pdf)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["annotations"][0]["result"][0]["value"]["labels"] == ["buyer"]
    assert body["data"]["text"] == "ACME kauft"


def test_export_by_upload(settings: Settings, blank_pdf: Path) -> None:
    with blank_pdf.open("rb") as fh:
        resp = _app(settings).post(
            "/v1/export", files={"file": ("scan.pdf", fh, "application/pdf")}
        )
    assert resp.status_code == 200
    assert resp.json()["meta"]["source"] == "scan.pdf"


def test_export_rejects_other_content_type(settings: Settings) -> None:
    resp = _app(settings).post("/v1/export", content=b"x", headers={"content-type": "text/plain"})
    assert resp.status_code == 415


def test_extract_rejects_other_content_type(settings: Settings) -> None:
    resp = _app(settings).post("/v1/extract", content=b"x", headers={"content-type": "text/plain"})
    assert resp.status_code == 415


def test_missing_path_field(settings: Settings) -> None:
    assert _app(settings).post("/v1/extract", json={}).status_code == 400


def test_missing_file_field(settings: Settings) -> None:
    files = {"other": ("x.pdf", b"%PDF", "application/pdf")}
    resp = _app(settings).post("/v1/extract", files=files)
    assert resp.status_code in {400, 422}


def test_ocr_failure_maps_to_502(settings: Settings, blank_pdf: Path) -> None:
    class BrokenOcr(FakeOcr):
        def ocr_page(self, image: bytes, page_no: int = 1) -> str:
            raise OcrError("OCR kaputt", page=page_no, status=500)

    resp = _app(settings, ocr=BrokenOcr()).post("/v1/extract", json={"path": str(blank_pdf)})
    assert resp.status_code == 502
    assert resp.json()["detail"] == "OCR kaputt"


def test_extract_without_schema_is_conflict() -> None:
    client = TestClient(create_app(Settings()))
    assert client.post("/v1/extract", json={"path": "/tmp/x.pdf"}).status_code == 409


def test_main_delegates_to_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(cli, "main", lambda: called.append("cli"))
    docpipeline.main()
    assert called == ["cli"]
