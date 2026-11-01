"""CLI des Doppellaufs (B8): extract, serve."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from docpipeline.dual.api import build_dual
from docpipeline.dual.engines import DualSettings
from docpipeline.dual.pipeline import DualPipeline
from docpipeline.errors import DocPipelineError, SchemaError
from docpipeline.extractor import Gliner2Extractor
from docpipeline.schema import ExtractionSchema, load_schema

app = typer.Typer(
    help="DocPipeline Dual: zwei OCR-Engines, ein Record.",
    no_args_is_help=True,
    add_completion=False,
)

SCHEMA_OPTION = typer.Option(None, "--schema", "-s", help="Schema-Datei (TOML oder JSON)")
VERIFY_OPTION = typer.Option(True, "--verify/--no-verify", help="Regionen nachlesen")


def build_runtime(
    settings: DualSettings, schema_path: Path | None, **kwargs: Any
) -> tuple[DualPipeline, ExtractionSchema]:
    """Baut Pipeline und Schema. In Tests ersetzbar."""
    if schema_path is None:
        raise SchemaError("--schema fehlt")
    schema = load_schema(schema_path)
    settings.engine_model = schema.model
    settings.threshold = schema.threshold
    settings.schema_file = str(schema_path)
    dual = kwargs.get("dual") or build_dual(settings)
    extractor = kwargs.get("extractor") or Gliner2Extractor(
        model=schema.model, device=settings.engine_device, threshold=schema.threshold
    )
    pipeline = DualPipeline(
        settings,
        schema,
        dual,
        extractor,
        verify=kwargs.get("verify"),
        verify_engine=(dual.engines[0] if getattr(dual, "engines", None) else None),
    )
    return pipeline, schema


@app.command()
def extract(
    paths: list[Path] = typer.Argument(..., help="PDF- oder Bilddateien"),
    schema: Path | None = SCHEMA_OPTION,
    out: Path | None = typer.Option(None, "--out", "-o", help="Zielordner"),
    verify: bool = VERIFY_OPTION,
) -> None:
    """Verarbeitet Dateien mit beiden Engines und schreibt je Datei JSON."""
    settings = DualSettings()
    try:
        pipeline, _schema = build_runtime(settings, schema, verify=verify)
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
        typer.echo(f"{path.stem}  {len(record.entities)}  {record.timings_ms.get('ocr', 0):.0f} ms")
    if failures:
        raise typer.Exit(1)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Startet die FastAPI-Anwendung des Doppellaufs."""
    import uvicorn

    uvicorn.run("docpipeline.dual.api:app", host=host, port=port, reload=reload)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
