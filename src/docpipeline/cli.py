"""Kommandozeile (B8): extract, ocr, serve, bench, export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from docpipeline.bench import compare, format_table, load_ground_truth
from docpipeline.config import Settings
from docpipeline.errors import DocPipelineError, SchemaError
from docpipeline.export import to_label_studio
from docpipeline.extractor import Gliner2Extractor
from docpipeline.ocr import OcrClient
from docpipeline.pipeline import DocumentPipeline
from docpipeline.schema import ExtractionSchema, load_schema

app = typer.Typer(
    help="DocPipeline: Dokumente lesen und Entitäten extrahieren.",
    no_args_is_help=True,
    add_completion=False,
)

SCHEMA_OPTION = typer.Option(None, "--schema", "-s", help="Schema-Datei (TOML oder JSON)")


def build_runtime(
    settings: Settings, schema_path: Path | None, **kwargs: Any
) -> tuple[DocumentPipeline, ExtractionSchema]:
    """Baut Pipeline und Schema. In Tests ersetzbar."""
    if schema_path is None:
        raise SchemaError("--schema fehlt")
    schema = load_schema(schema_path)
    settings.engine_model = schema.model
    settings.threshold = schema.threshold
    settings.schema_file = str(schema_path)
    ocr = kwargs.get("ocr") or OcrClient(settings)
    extractor = kwargs.get("extractor") or Gliner2Extractor(
        model=schema.model,
        device=settings.engine_device,
        threshold=schema.threshold,
    )
    pipeline = DocumentPipeline(settings, schema, ocr, extractor)
    return pipeline, schema


@app.command()
def extract(
    paths: list[Path] = typer.Argument(..., help="PDF- oder Bilddateien"),
    schema: Path | None = SCHEMA_OPTION,
    out: Path | None = typer.Option(None, "--out", "-o", help="Zielordner"),
    ocr_mode: str | None = typer.Option(None, "--ocr-mode", help="auto oder always"),
) -> None:
    """Verarbeitet Dateien und schreibt je Datei eine JSON-Datei."""
    settings = Settings()
    if ocr_mode:
        settings.ocr_mode = "always" if ocr_mode == "always" else "auto"
    try:
        pipeline, _schema = build_runtime(settings, schema)
    except SchemaError as error:
        typer.echo(f"Schemafehler: {error}", err=True)
        raise typer.Exit(2) from error
    target_dir = out or Path()
    target_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for path in paths:
        try:
            record = pipeline.run(path)
        except DocPipelineError as error:
            typer.echo(f"{path.name}: {error}", err=True)
            failures += 1
            continue
        target = target_dir / f"{path.stem}.json"
        target.write_text(record.to_json(), encoding="utf-8")
        typer.echo(
            f"{path.stem}  {len(record.entities)}  {record.timings_ms.get('extract', 0):.0f} ms"
        )
    if failures:
        raise typer.Exit(1)


@app.command()
def ocr(
    path: Path = typer.Argument(..., help="PDF- oder Bilddatei"),
    schema: Path | None = SCHEMA_OPTION,
) -> None:
    """Gibt den erkannten Text einer Datei aus (Debug)."""
    settings = Settings()
    try:
        pipeline, _schema = build_runtime(settings, schema)
        record = pipeline.run(path)
    except SchemaError as error:
        typer.echo(f"Schemafehler: {error}", err=True)
        raise typer.Exit(2) from error
    except DocPipelineError as error:
        typer.echo(f"{path.name}: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(record.text or "")


@app.command()
def bench(
    docs: list[Path] = typer.Option(..., "--docs", help="Dokumente für den Lauf"),
    gt: Path = typer.Option(..., "--gt", help="Ordner mit Ground Truth (JSON)"),
    schema: Path | None = SCHEMA_OPTION,
    min_recall: float | None = typer.Option(None, "--min-recall", help="Mindest-Recall je Label"),
) -> None:
    """Vergleicht Treffer mit Ground Truth und zeigt Recall und Precision."""
    settings = Settings()
    try:
        pipeline, _schema = build_runtime(settings, schema)
    except SchemaError as error:
        typer.echo(f"Schemafehler: {error}", err=True)
        raise typer.Exit(2) from error
    records = {}
    for path in docs:
        try:
            records[path.stem] = pipeline.run(path)
        except DocPipelineError as error:
            typer.echo(f"{path.name}: {error}", err=True)
            raise typer.Exit(1) from error
    report = compare(records, load_ground_truth(gt))
    typer.echo(format_table(report))
    if min_recall is not None and any(
        score.recall < min_recall for score in report.values()
    ):
        raise typer.Exit(1)


@app.command()
def export(
    path: Path = typer.Argument(..., help="PDF- oder Bilddatei"),
    out: Path = typer.Option(..., "--out", "-o", help="Ziel-Datei (JSON)"),
    schema: Path | None = SCHEMA_OPTION,
) -> None:
    """Schreibt eine Label-Studio-Aufgabe mit Vorannotation."""
    settings = Settings()
    try:
        pipeline, _schema = build_runtime(settings, schema)
        record = pipeline.run(path)
    except SchemaError as error:
        typer.echo(f"Schemafehler: {error}", err=True)
        raise typer.Exit(2) from error
    except DocPipelineError as error:
        typer.echo(f"{path.name}: {error}", err=True)
        raise typer.Exit(1) from error
    out.write_text(
        json.dumps(to_label_studio(record), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    typer.echo(f"{out}  {len(record.entities)} Treffer")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Startet die FastAPI-Anwendung."""
    import uvicorn

    uvicorn.run("docpipeline.api:app", host=host, port=port, reload=reload)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
