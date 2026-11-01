"""FastAPI-Schicht: Router zum Einbinden in fremde Apps (B9, E2)."""

from __future__ import annotations

import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, cast

from fastapi import APIRouter, FastAPI, HTTPException, Request

from docpipeline.config import Settings
from docpipeline.errors import (
    DocPipelineError,
    EmptyFileError,
    OcrError,
    PathError,
    SchemaError,
    UnsupportedFormatError,
)
from docpipeline.export import to_label_studio
from docpipeline.extractor import Gliner2Extractor
from docpipeline.ocr import OcrClient
from docpipeline.pipeline import DocumentPipeline
from docpipeline.schema import ExtractionSchema, load_schema

VERSION = "0.1.0"

_STATUS = {
    UnsupportedFormatError: 415,
    EmptyFileError: 400,
    PathError: 400,
    OcrError: 502,
    SchemaError: 422,
}


def _error(error: DocPipelineError) -> HTTPException:
    for kind, status in _STATUS.items():
        if isinstance(error, kind):
            return HTTPException(status_code=status, detail=str(error))
    return HTTPException(status_code=500, detail=str(error))


def _check_path(raw: str, settings: Settings) -> Path:
    if not settings.allow_path_input:
        raise PathError("Pfad-Eingabe ist deaktiviert; nutze den Datei-Upload")
    base = Path(settings.base_dir or Path.cwd()).resolve()
    target = Path(raw).expanduser().resolve()
    if not target.is_relative_to(base):
        raise PathError(f"Pfad liegt außerhalb der Basis {base}: {target}")
    return target


def create_router(
    settings: Settings,
    schema: ExtractionSchema | None = None,
    ocr: Any = None,
    extractor: Any = None,
) -> APIRouter:
    """Baut den Router ohne Seiteneffekte.

    Modell und HTTP-Client entstehen erst beim ersten Aufruf.
    """
    router = APIRouter(prefix="/v1", tags=["docpipeline"])
    state: dict[str, Any] = {"ocr": ocr, "extractor": extractor}

    def get_ocr() -> Any:
        if state["ocr"] is None:
            state["ocr"] = OcrClient(settings)
        return state["ocr"]

    def get_extractor() -> Any:
        if state["extractor"] is None:
            state["extractor"] = Gliner2Extractor(
                model=schema.model if schema else settings.engine_model,
                device=settings.engine_device,
                threshold=schema.threshold if schema else settings.threshold,
            )
        return state["extractor"]

    def pipeline(source_name: str | None = None) -> DocumentPipeline:
        if schema is None:
            raise HTTPException(status_code=409, detail="Kein Schema konfiguriert")
        return DocumentPipeline(
            settings, schema, get_ocr(), get_extractor(), source_name=source_name
        )

    @router.get("/health")
    def health() -> dict[str, Any]:
        reachable = False
        try:
            reachable = bool(get_ocr().ping())
        except DocPipelineError:
            reachable = False
        return {
            "status": "ok",
            "ocr_reachable": reachable,
            "ocr_model": get_ocr().model,
            "engine": schema.model if schema else settings.engine_model,
            "version": VERSION,
        }

    @router.get("/schema")
    def read_schema() -> dict[str, Any]:
        if schema is None:
            raise HTTPException(status_code=409, detail="Kein Schema konfiguriert")
        return {"model": schema.model, "threshold": schema.threshold, "labels": schema.labels}

    @router.post("/extract")
    async def extract(request: Request) -> dict[str, Any]:
        content_type = request.headers.get("content-type", "")
        try:
            if content_type.startswith("multipart/form-data"):
                return await _from_upload(request, pipeline, settings)
            if content_type.startswith("application/json"):
                body = await request.json()
                raw = (body or {}).get("path")
                if not isinstance(raw, str) or not raw:
                    raise PathError("Feld 'path' fehlt")
                record = pipeline().run(_check_path(raw, settings))
                return record.model_dump(mode="json")
        except DocPipelineError as error:
            raise _error(error) from error
        raise HTTPException(status_code=415, detail="Erwartet multipart/form-data oder JSON")

    @router.post("/export")
    async def export(request: Request) -> dict[str, Any]:
        content_type = request.headers.get("content-type", "")
        try:
            if content_type.startswith("multipart/form-data"):
                record = await _run_upload(request, pipeline, settings)
                return to_label_studio(record)
            if content_type.startswith("application/json"):
                body = await request.json()
                raw = (body or {}).get("path")
                if not isinstance(raw, str) or not raw:
                    raise PathError("Feld 'path' fehlt")
                return to_label_studio(pipeline().run(_check_path(raw, settings)))
        except DocPipelineError as error:
            raise _error(error) from error
        raise HTTPException(status_code=415, detail="Erwartet multipart/form-data oder JSON")

    return router


async def _run_upload(request: Request, pipeline: Any, settings: Settings) -> Any:
    form = await request.form()
    try:
        upload = form.get("file")
        if upload is None or isinstance(upload, str) or not hasattr(upload, "read"):
            raise PathError("Feld 'file' fehlt")
        data = await upload.read()
        filename = getattr(upload, "filename", "") or ""
    finally:
        for value in form.values():
            if hasattr(value, "close"):
                await value.close()
    if not data:
        raise EmptyFileError("Datei ist leer")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Datei zu groß (max {settings.max_upload_bytes} Bytes)",
        )
    suffix = PurePosixPath(filename).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    try:
        return pipeline(source_name=filename or temporary.name).run(temporary)
    finally:
        temporary.unlink(missing_ok=True)


async def _from_upload(request: Request, pipeline: Any, settings: Settings) -> dict[str, Any]:
    record = await _run_upload(request, pipeline, settings)
    return cast("dict[str, Any]", record.model_dump(mode="json"))


def create_app(
    settings: Settings,
    schema: ExtractionSchema | None = None,
    ocr: Any = None,
    extractor: Any = None,
) -> FastAPI:
    app = FastAPI(
        title="DocPipeline",
        version=VERSION,
        description="OCR (OpenAI-kompatibel) → Chunking → GLiNER2 → Dedup",
        openapi_url="/v1/openapi.json",
    )
    app.include_router(create_router(settings, schema=schema, ocr=ocr, extractor=extractor))
    return app


def _env_schema(settings: Settings) -> ExtractionSchema | None:
    if not settings.schema_file:
        return None
    try:
        return load_schema(settings.schema_file)
    except SchemaError:
        return None


_env_settings = Settings()
app = create_app(_env_settings, schema=_env_schema(_env_settings))
