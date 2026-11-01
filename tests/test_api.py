"""B9/E2 — FastAPI-Plugin."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import FakeExtractor, FakeOcr
from docpipeline.api import create_app
from docpipeline.config import Settings
from docpipeline.schema import ExtractionSchema


def _app(settings: Settings, ocr: FakeOcr | None = None, labels: dict[str, str] | None = None):
    schema = ExtractionSchema(model="fake", labels=labels or {"buyer": "Käufer"})
    return create_app(
        settings,
        schema=schema,
        ocr=ocr or FakeOcr({1: "ACME kauft"}),
        extractor=FakeExtractor({"buyer": "ACME"}),
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(_app(settings))


def test_health_ok(client: TestClient) -> None:
    body = client.get("/v1/health").json()
    assert body["status"] == "ok"
    assert body["ocr_reachable"] is True
    assert body["ocr_model"] == "fake-ocr"
    assert body["engine"] == "fake"


def test_health_when_ocr_down(settings: Settings) -> None:
    client = TestClient(_app(settings, ocr=FakeOcr(ping_ok=False)))
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["ocr_reachable"] is False


def test_extract_upload(client: TestClient, blank_pdf: Path) -> None:
    with blank_pdf.open("rb") as fh:
        resp = client.post("/v1/extract", files={"file": ("scan.pdf", fh, "application/pdf")})
    assert resp.status_code == 200
    record = resp.json()
    assert record["pages"] == 1
    assert record["entities"][0]["label"] == "buyer"


def test_extract_by_path(client: TestClient, blank_pdf: Path) -> None:
    resp = client.post("/v1/extract", json={"path": str(blank_pdf)})
    assert resp.status_code == 200
    assert resp.json()["source"] == "scan.pdf"


def test_path_outside_base_rejected(settings: Settings, tmp_path_factory) -> None:
    other = tmp_path_factory.mktemp("fremd")
    pdf = other / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    client = TestClient(_app(settings))
    resp = client.post("/v1/extract", json={"path": str(pdf)})
    assert resp.status_code == 400
    assert "Pfad" in resp.json()["detail"]


def test_path_input_can_be_disabled(settings: Settings, blank_pdf: Path) -> None:
    settings.allow_path_input = False
    client = TestClient(_app(settings))
    resp = client.post("/v1/extract", json={"path": str(blank_pdf)})
    assert resp.status_code == 400


def test_unsupported_upload_gives_415(client: TestClient, tmp_path: Path) -> None:
    bad = tmp_path / "notiz.txt"
    bad.write_text("hallo", encoding="utf-8")
    with bad.open("rb") as fh:
        resp = client.post("/v1/extract", files={"file": ("notiz.txt", fh, "text/plain")})
    assert resp.status_code == 415


def test_empty_upload_gives_400(client: TestClient) -> None:
    resp = client.post("/v1/extract", files={"file": ("leer.pdf", b"", "application/pdf")})
    assert resp.status_code == 400


def test_too_large_upload_gives_413(settings: Settings, blank_pdf: Path) -> None:
    settings.max_upload_bytes = 10
    client = TestClient(_app(settings))
    with blank_pdf.open("rb") as fh:
        resp = client.post("/v1/extract", files={"file": ("scan.pdf", fh, "application/pdf")})
    assert resp.status_code == 413


def test_schema_endpoint(settings: Settings) -> None:
    client = TestClient(_app(settings, labels={"buyer": "Käufer", "amount": ""}))
    assert client.get("/v1/schema").json()["labels"] == {
        "buyer": "Käufer",
        "amount": "",
    }


def test_schema_endpoint_without_schema(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    assert client.get("/v1/schema").status_code == 409


def test_openapi_available(client: TestClient) -> None:
    assert client.get("/v1/openapi.json").status_code == 200


def test_router_can_be_mounted_on_foreign_app(settings: Settings, blank_pdf: Path) -> None:
    from fastapi import FastAPI

    from docpipeline.api import create_router
    from docpipeline.schema import ExtractionSchema

    api = FastAPI()
    api.include_router(
        create_router(
            settings,
            schema=ExtractionSchema(model="fake", labels={"buyer": "Käufer"}),
            ocr=FakeOcr({1: "ACME kauft"}),
            extractor=FakeExtractor({"buyer": "ACME"}),
        ),
        prefix="/docs-ai",
    )
    foreign = TestClient(api)
    with blank_pdf.open("rb") as fh:
        resp = foreign.post(
            "/docs-ai/v1/extract", files={"file": ("scan.pdf", fh, "application/pdf")}
        )
    assert resp.status_code == 200


def test_api_import_does_not_pull_cli_library() -> None:
    code = "import sys, docpipeline.api; print('typer' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
