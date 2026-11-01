"""FastAPI-Schicht des Doppellaufs (B8)."""

from __future__ import annotations

import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, cast

from fastapi import APIRouter, FastAPI, HTTPException, Request

from docpipeline.api import VERSION, _check_path, _error
from docpipeline.config import Settings
from docpipeline.dual.engines import DotsEngine, DualOcr, DualSettings, PaddleEngine
from docpipeline.dual.pipeline import DualPipeline
from docpipeline.dual.rapid import RapidEngine
from docpipeline.errors import (
    DocPipelineError,
    EmptyFileError,
    PathError,
    SchemaError,
)
from docpipeline.extractor import Gliner2Extractor
from docpipeline.schema import ExtractionSchema, load_schema


def build_dual(settings: DualSettings, engines: list[Any] | None = None) -> DualOcr:
    """Zwei Pflicht-Engines, RapidOCR nur wenn freigegeben und installiert (D3a)."""
    if engines:
        return DualOcr(settings, engines=engines)
    built: list[Any] = [PaddleEngine(settings), DotsEngine(settings)]
    if getattr(settings, "dual_engine_c", False) and RapidEngine.available():
        built.append(RapidEngine(settings))
    return DualOcr(settings, engines=built)


def create_router(
    settings: DualSettings,
    schema: ExtractionSchema | None = None,
    dual: Any = None,
    extractor: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["docpipeline-dual"])
    state: dict[str, Any] = {"dual": dual, "extractor": extractor}

    def get_dual() -> Any:
        if state["dual"] is None:
            state["dual"] = build_dual(settings)
        return state["dual"]

    def get_extractor() -> Any:
        if state["extractor"] is None:
            state["extractor"] = Gliner2Extractor(
                model=schema.model if schema else settings.engine_model,
                device=settings.engine_device,
                threshold=schema.threshold if schema else settings.threshold,
            )
        return state["extractor"]

    def pipeline(source_name: str | None = None, verify: bool | None = None) -> DualPipeline:
        if schema is None:
            raise HTTPException(status_code=409, detail="Kein Schema konfiguriert")
        dual_ocr = get_dual()
        return DualPipeline(
            settings,
            schema,
            dual_ocr,
            get_extractor(),
            verify=verify,
            verify_engine=(dual_ocr.engines[0] if getattr(dual_ocr, "engines", None) else None),
            source_name=source_name,
        )

    @router.get("/health")
    def health() -> dict[str, Any]:
        dual_ocr = get_dual()
        engines = []
        for engine in getattr(dual_ocr, "engines", []):
            try:
                reachable = bool(engine.ping())
            except DocPipelineError:
                reachable = False
            engines.append(
                {
                    "name": getattr(engine, "name", "?"),
                    "model": getattr(engine, "model", getattr(engine, "name", "?")),
                    "dpi": getattr(engine, "dpi", None),
                    "reachable": reachable,
                }
            )
        return {
            "status": "ok",
            "ocr_reachable": all(item["reachable"] for item in engines) if engines else False,
            "engines": engines,
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
                form = await request.form()
                verify = _as_bool(form.get("verify"), None)
                record = await _run_upload(request, pipeline, settings, form, verify)
                return cast("dict[str, Any]", record.model_dump(mode="json"))
            if content_type.startswith("application/json"):
                body = await request.json() or {}
                raw = body.get("path")
                if not isinstance(raw, str) or not raw:
                    raise PathError("Feld 'path' fehlt")
                record = pipeline(verify=_as_bool(body.get("verify"), None)).run(
                    _check_path(raw, cast("Settings", settings))
                )
                return record.model_dump(mode="json")
        except DocPipelineError as error:
            raise _error(error) from error
        raise HTTPException(status_code=415, detail="Erwartet multipart/form-data oder JSON")

    return router


async def _run_upload(
    request: Request,
    pipeline: Any,
    settings: DualSettings,
    form: Any,
    verify: bool | None,
) -> Any:
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
            status_code=413, detail=f"Datei zu groß (max {settings.max_upload_bytes} Bytes)"
        )
    suffix = PurePosixPath(filename).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    try:
        return pipeline(source_name=filename or None, verify=verify).run(temporary)
    finally:
        temporary.unlink(missing_ok=True)


def _as_bool(value: Any, default: bool | None) -> bool | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "ja"}


def create_app(
    settings: DualSettings,
    schema: ExtractionSchema | None = None,
    dual: Any = None,
    extractor: Any = None,
) -> FastAPI:
    app = FastAPI(
        title="DocPipeline Dual",
        version=VERSION,
        description="Doppel-OCR (paddleocr-vl + dots.mocr) → Chunking → GLiNER2 → Union",
        openapi_url="/v1/openapi.json",
    )
    app.include_router(create_router(settings, schema=schema, dual=dual, extractor=extractor))
    return app


def _env_schema(settings: DualSettings) -> ExtractionSchema | None:
    if not settings.schema_file:
        return None
    try:
        return load_schema(settings.schema_file)
    except SchemaError:
        return None


_env_settings = DualSettings()
app = create_app(_env_settings, schema=_env_schema(_env_settings))
