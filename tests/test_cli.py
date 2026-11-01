"""B8 — CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import FakeExtractor, FakeOcr
from docpipeline import cli
from docpipeline.config import Settings
from docpipeline.errors import SchemaError
from docpipeline.pipeline import DocumentPipeline
from docpipeline.schema import ExtractionSchema

runner = CliRunner()


@pytest.fixture
def fake_runtime(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    def build(_settings: Settings, schema_path: Path | None, **_kw):
        schema = ExtractionSchema(model="fake", labels={"buyer": "Käufer"})
        pipe = DocumentPipeline(
            _settings, schema, FakeOcr({1: "ACME kauft"}), FakeExtractor({"buyer": "ACME"})
        )
        return pipe, schema

    monkeypatch.setattr(cli, "build_runtime", build)
    return build


def test_extract_writes_json(
    fake_runtime, settings: Settings, blank_pdf: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    result = runner.invoke(
        cli.app, ["extract", str(blank_pdf), "--out", str(out), "--schema", "s.toml"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads((out / "scan.json").read_text(encoding="utf-8"))
    assert data["entities"][0]["label"] == "buyer"
    assert "scan" in result.stdout
    assert "1" in result.stdout


def test_extract_error_gives_exit_1(fake_runtime, tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["extract", str(tmp_path / "fehlt.pdf"), "--schema", "s"])
    assert result.exit_code == 1


def test_bad_schema_gives_exit_2(settings: Settings, blank_pdf: Path, monkeypatch) -> None:
    def build(_settings, schema_path, **_kw):
        raise SchemaError("threshold außerhalb [0,1]")

    monkeypatch.setattr(cli, "build_runtime", build)
    result = runner.invoke(cli.app, ["extract", str(blank_pdf), "--schema", "kaputt.toml"])
    assert result.exit_code == 2
    assert "threshold" in result.stdout + result.stderr


def test_ocr_command_prints_text(fake_runtime, blank_pdf: Path) -> None:
    result = runner.invoke(cli.app, ["ocr", str(blank_pdf), "--schema", "s"])
    assert result.exit_code == 0
    assert "ACME" in result.stdout


def test_bench_below_threshold_gives_exit_1(
    fake_runtime, settings: Settings, blank_pdf: Path, tmp_path: Path
) -> None:
    gt = tmp_path / "gt"
    gt.mkdir()
    (gt / "scan.json").write_text(
        json.dumps({"entities": [{"label": "buyer", "text": "NICHT DA"}]}), encoding="utf-8"
    )
    result = runner.invoke(
        cli.app,
        [
            "bench",
            "--docs",
            str(blank_pdf),
            "--gt",
            str(gt),
            "--schema",
            "s",
            "--min-recall",
            "0.9",
        ],
    )
    assert result.exit_code == 1
    assert "buyer" in result.stdout


def test_commands_are_registered() -> None:
    names = {
        command.name or getattr(command.callback, "__name__", "")
        for command in cli.app.registered_commands
    }
    assert {"extract", "ocr", "serve", "bench", "export"} <= names


def test_extract_help_exits_zero() -> None:
    result = runner.invoke(cli.app, ["extract", "--help"])
    assert result.exit_code == 0
    assert "--schema" in result.stdout


def test_export_command_writes_label_studio(
    fake_runtime, blank_pdf: Path, tmp_path: Path
) -> None:
    target = tmp_path / "ls.json"
    result = runner.invoke(
        cli.app, ["export", str(blank_pdf), "--out", str(target), "--schema", "s"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["annotations"][0]["result"][0]["value"]["text"] == "ACME"


def test_bench_passes_with_full_recall(
    fake_runtime, blank_pdf: Path, tmp_path: Path
) -> None:
    gt = tmp_path / "gt"
    gt.mkdir()
    (gt / "scan.json").write_text(
        json.dumps({"entities": [{"label": "buyer", "text": "acme"}]}), encoding="utf-8"
    )
    result = runner.invoke(
        cli.app,
        ["bench", "--docs", str(blank_pdf), "--gt", str(gt), "--schema", "s",
         "--min-recall", "0.9"],
    )
    assert result.exit_code == 0, result.output
    assert "100.0%" in result.stdout


def test_build_runtime_uses_schema_file(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema_path = tmp_path / "schema.toml"
    schema_path.write_text(
        'model = "fastino/gliner2.5-multi-v1"\nthreshold = 0.4\n\n[labels]\nbuyer = ""\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "OcrClient", lambda _s: FakeOcr({1: "ACME"}))
    monkeypatch.setattr(
        cli, "Gliner2Extractor", lambda **kw: FakeExtractor({"buyer": "ACME"})
    )
    pipeline, schema = cli.build_runtime(settings, schema_path)
    assert schema.threshold == 0.4
    assert settings.schema_file == str(schema_path)
    assert pipeline.run.__self__ is pipeline


def test_build_runtime_requires_schema(settings: Settings) -> None:
    with pytest.raises(SchemaError):
        cli.build_runtime(settings, None)
