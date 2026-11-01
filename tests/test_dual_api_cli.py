"""B8 — API und CLI des Doppellaufs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import docpipeline.dual.cli as dual_cli
from conftest import FakeExtractor
from docpipeline.dual.api import create_app
from docpipeline.dual.engines import DualSettings, Variant
from docpipeline.dual.formats import Element, OcrPage
from docpipeline.errors import OcrError, SchemaError
from docpipeline.schema import ExtractionSchema

runner = CliRunner()


class FakeDual:
    def __init__(self, pages: list[str] | None = None, fail: bool = False) -> None:
        self.pages = pages or ["ACME kauft"]
        self.fail = fail
        self.calls = 0
        self.engines = [
            _FakeEngine("paddleocr-vl", "paddleocr-vl", 300),
            _FakeEngine("dots-mocr", "dots-mocr", 200),
        ]

    def variants(self, path: str | Path) -> list[Variant]:
        self.calls += 1
        if self.fail:
            raise OcrError("dots-mocr tot", page=1, status=500)
        return [
            Variant(
                name="paddleocr-vl",
                page_texts=tuple(self.pages),
                text="\n\n".join(self.pages),
                boxes=tuple(
                    (Element(index + 1, (0, 0, 9, 9), "Text", page),)
                    for index, page in enumerate(self.pages)
                ),
                tables=tuple(() for _ in self.pages),
                dpi=300,
                pages_ocr=len(self.pages),
            ),
            Variant(
                name="dots-mocr",
                page_texts=tuple(self.pages),
                text="\n\n".join(self.pages),
                boxes=tuple(() for _ in self.pages),
                tables=tuple(() for _ in self.pages),
                dpi=200,
                pages_ocr=len(self.pages),
            ),
        ]


class _FakeEngine:
    """Nur für /v1/health: Name, Modell, Auflösung, Erreichbarkeit."""

    def __init__(self, name: str, model: str, dpi: int) -> None:
        self.name = name
        self.model = model
        self.dpi = dpi

    def ping(self) -> bool:
        return True

    def describe_page(self, image: bytes, page_no: int = 1) -> OcrPage:
        raise OcrError("nicht benutzt", page=page_no)


def _settings(tmp_path: Path) -> DualSettings:
    return DualSettings(base_dir=str(tmp_path), dual_verify=False)


def _app(settings: DualSettings, dual: FakeDual | None = None) -> TestClient:
    return TestClient(
        create_app(
            settings,
            schema=ExtractionSchema(model="fake", labels={"buyer": "Käufer"}),
            dual=dual or FakeDual(),
            extractor=FakeExtractor({"buyer": "ACME"}),
        )
    )


@pytest.fixture
def scan(tmp_path: Path) -> Path:
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake")
    return path


def test_health_names_both_engines(tmp_path: Path) -> None:
    body = _app(_settings(tmp_path)).get("/v1/health").json()
    assert body["status"] == "ok"
    assert {engine["name"] for engine in body["engines"]} == {"paddleocr-vl", "dots-mocr"}
    assert all("reachable" in engine for engine in body["engines"])


def test_extract_by_path_returns_dual_record(tmp_path: Path, scan: Path) -> None:
    response = _app(_settings(tmp_path)).post("/v1/extract", json={"path": str(scan)})
    assert response.status_code == 200
    body = response.json()
    assert set(body["variants"]) == {"paddleocr-vl", "dots-mocr"}
    assert body["entities"][0]["agreement"] == "both"
    assert len(body["entities"][0]["sources"]) == 2


def test_extract_upload(tmp_path: Path, scan: Path) -> None:
    with scan.open("rb") as fh:
        response = _app(_settings(tmp_path)).post(
            "/v1/extract", files={"file": ("scan.pdf", fh, "application/pdf")}
        )
    assert response.status_code == 200
    assert response.json()["source"] == "scan.pdf"


def test_verify_flag_is_accepted(tmp_path: Path, scan: Path) -> None:
    response = _app(_settings(tmp_path)).post(
        "/v1/extract", json={"path": str(scan), "verify": False}
    )
    assert response.status_code == 200
    assert response.json()["entities"][0]["verified"] is None


def test_engine_failure_is_502(tmp_path: Path, scan: Path) -> None:
    response = _app(_settings(tmp_path), FakeDual(fail=True)).post(
        "/v1/extract", json={"path": str(scan)}
    )
    assert response.status_code == 502
    assert "dots-mocr" in response.json()["detail"]


def test_schema_and_missing_schema(tmp_path: Path) -> None:
    assert _app(_settings(tmp_path)).get("/v1/schema").json()["labels"] == {"buyer": "Käufer"}
    assert (
        TestClient(create_app(_settings(tmp_path)))
        .post("/v1/extract", json={"path": "/tmp/x.pdf"})
        .status_code
        == 409
    )


def test_unsupported_upload(tmp_path: Path) -> None:
    response = _app(_settings(tmp_path)).post(
        "/v1/extract", files={"file": ("notiz.txt", b"hallo", "text/plain")}
    )
    assert response.status_code == 415


def test_cli_extract_writes_record(
    tmp_path: Path, scan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dual = FakeDual()

    def build(_settings, _schema_path, **_kwargs):
        return (
            __import__("docpipeline.dual.pipeline", fromlist=["DualPipeline"]).DualPipeline(
                _settings,
                ExtractionSchema(model="fake", labels={"buyer": "Käufer"}),
                dual,
                FakeExtractor({"buyer": "ACME"}),
                verify=False,
            ),
            ExtractionSchema(model="fake", labels={"buyer": "Käufer"}),
        )

    monkeypatch.setattr(dual_cli, "build_runtime", build)
    target = tmp_path / "out"
    result = runner.invoke(
        dual_cli.app,
        ["extract", str(scan), "--schema", "s.toml", "--out", str(target)],
    )
    assert result.exit_code == 0, result.output
    data = json.loads((target / "scan.json").read_text(encoding="utf-8"))
    assert data["entities"][0]["agreement"] == "both"
    assert "scan" in result.stdout


def test_cli_bad_schema_exits_2(
    tmp_path: Path, scan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def build(*_args, **_kwargs):
        raise SchemaError("threshold außerhalb [0,1]")

    monkeypatch.setattr(dual_cli, "build_runtime", build)
    result = runner.invoke(dual_cli.app, ["extract", str(scan), "--schema", "s"])
    assert result.exit_code == 2
    assert "threshold" in result.stdout + result.stderr


def test_cli_engine_failure_exits_1(
    tmp_path: Path, scan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def build(_settings, _schema_path, **_kwargs):
        return (
            __import__("docpipeline.dual.pipeline", fromlist=["DualPipeline"]).DualPipeline(
                _settings,
                ExtractionSchema(model="fake", labels={"buyer": "Käufer"}),
                FakeDual(fail=True),
                FakeExtractor({}),
                verify=False,
            ),
            ExtractionSchema(model="fake", labels={"buyer": "Käufer"}),
        )

    monkeypatch.setattr(dual_cli, "build_runtime", build)
    result = runner.invoke(dual_cli.app, ["extract", str(scan), "--schema", "s"])
    assert result.exit_code == 1
    assert "dots-mocr" in result.stdout + result.stderr


def test_cli_no_verify_flag(tmp_path: Path, scan: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def build(_settings, _schema_path, **kwargs):
        seen.update(kwargs)
        return (
            __import__("docpipeline.dual.pipeline", fromlist=["DualPipeline"]).DualPipeline(
                _settings,
                ExtractionSchema(model="fake", labels={"buyer": "Käufer"}),
                FakeDual(),
                FakeExtractor({"buyer": "ACME"}),
                verify=False,
            ),
            ExtractionSchema(model="fake", labels={"buyer": "Käufer"}),
        )

    monkeypatch.setattr(dual_cli, "build_runtime", build)
    result = runner.invoke(
        dual_cli.app,
        ["extract", str(scan), "--schema", "s", "--out", str(tmp_path / "o"), "--no-verify"],
    )
    assert result.exit_code == 0, result.output
    assert seen.get("verify") is False
