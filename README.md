# DocPipeline

Schema-driven extraction of named fields from PDFs and scanned images.

A document is rendered to pages, converted to text either from the PDF text
layer or through an OCR endpoint that speaks the OpenAI chat-completions API,
split into overlapping chunks, passed to a local [GLiNER2](https://github.com/fastino-ai/GLiNER2)
model, de-duplicated across chunk boundaries, and returned as one JSON record
per document. The same core is exposed as a local CLI and as a FastAPI router
that other services can mount.

```
document ─► pages (pymupdf) ─► text layer or OCR ─► document text
         ─► sliding-window chunks ─► GLiNER2 entities ─► dedup ─► JSON record
                                                              └─► recall/precision benchmark
```

## Status

| Area | State |
|---|---|
| Ingest, OCR, chunking, extraction, dedup, record | implemented, tested |
| CLI (`extract`, `ocr`, `bench`, `export`, `serve`) | implemented, tested |
| FastAPI (`create_app`, `create_router`) | implemented, tested |
| Recall/precision benchmark against ground truth | implemented, tested |
| Label Studio export (pre-annotation) | implemented, tested |
| Fine-tuning of the extraction model | **not implemented**, documented only (see [Fine-tuning](#fine-tuning)) |
| Web UI | not implemented, out of scope |

No accuracy claim is made for the base checkpoint. Accuracy is whatever
`docpipeline bench` measures on your own ground truth.

## How it works

| Stage | Module | Behaviour |
|---|---|---|
| Render | `docpipeline.ingest` | PDF pages at 200 dpi (configurable); image files become a single page |
| Text layer | `docpipeline.ingest` | A page whose extracted text is at least `min_text_layer_chars` long is used as-is and is never sent to OCR |
| OCR | `docpipeline.ocr` | `POST {base_url}/chat/completions` with a base64 `image_url` part and a text prompt, `temperature: 0`; retries on 5xx and 429 with exponential backoff |
| Chunking | `docpipeline.chunker` | Word windows with overlap; boundaries prefer sentence ends; character offsets are absolute in the document text |
| Extraction | `docpipeline.extractor` | GLiNER2 span extraction per chunk; chunk-relative offsets are shifted to document offsets |
| Dedup | `docpipeline.dedup` | Same label and same normalised text merge when the occurrences overlap or lie within `dedup_distance` characters; the highest score survives |
| Record | `docpipeline.pipeline` | Sorted entities, page numbers, warnings, timings, SHA-256 of the source file |
| Benchmark | `docpipeline.bench` | Case-insensitive, whitespace-normalised string match against a ground-truth directory |

The OCR stage deliberately uses no layout coordinates, because the OCR
endpoint returns plain text. Detection is therefore independent of where a
field sits on the page, which is the point of the design: no per-vendor
coordinate parsing.

## Requirements

| Item | Version / note |
|---|---|
| Python | 3.12 (pinned in `.python-version`) |
| Package manager | [uv](https://docs.astral.sh/uv/) |
| OCR endpoint | Any OpenAI-compatible `POST /v1/chat/completions` that accepts `image_url` data URLs. Measured against llama-swap serving `paddleocr-vl` at `http://127.0.0.1:8080/v1` |
| Extraction model | `fastino/gliner2.5-multi-v1` (Apache-2.0, multilingual, 287M parameters). Downloaded from Hugging Face on first use, about 330 MB |
| Hardware | CPU is sufficient. Measured: six-page article, 13.9 s extraction, 16.8 s total on a laptop CPU. Set `DOCPIPELINE_ENGINE_DEVICE=cuda` to use a GPU |

## Install

```bash
git clone <repo-url>
cd DocPipeline
uv sync
```

`uv sync` installs the runtime dependencies and the `dev` group (pytest,
hypothesis, ruff, mypy, pytest-cov, pytest-randomly).

## Quick start

```bash
# one document, invoice-style fields
uv run docpipeline extract invoice.pdf --schema data/schema.invoice.toml -o out/

# the same document through the HTTP API
DOCPIPELINE_SCHEMA_FILE=data/schema.invoice.toml uv run docpipeline serve
curl -s -X POST http://127.0.0.1:8000/v1/extract \
     -F "file=@invoice.pdf" | jq .entities
```

## Configuration

Settings come from environment variables prefixed `DOCPIPELINE_` or from a
`.env` file in the working directory.

| Variable | Default | Meaning |
|---|---|---|
| `DOCPIPELINE_OCR_BASE_URL` | `http://127.0.0.1:8080/v1` | OpenAI-compatible base URL |
| `DOCPIPELINE_OCR_MODEL` | `paddleocr-vl` | Model name sent in the request |
| `DOCPIPELINE_OCR_API_KEY` | random, unused unless set | Sent as `Authorization: Bearer …`; never written to output, logs or error text |
| `DOCPIPELINE_OCR_PROMPT` | Markdown transcription prompt | Prompt for the OCR call |
| `DOCPIPELINE_OCR_TIMEOUT_S` | `180` | Per-request timeout |
| `DOCPIPELINE_OCR_RETRIES` | `3` | Total attempts per page, not retries on top of a first attempt |
| `DOCPIPELINE_OCR_BACKOFF_S` | `1.0` | Base for exponential backoff: 1 s, 2 s, 4 s |
| `DOCPIPELINE_OCR_MODE` | `auto` | `auto` uses the text layer when present, `always` forces OCR |
| `DOCPIPELINE_DPI` | `200` | Raster resolution for pages without a text layer |
| `DOCPIPELINE_MIN_TEXT_LAYER_CHARS` | `40` | Shorter text layers count as empty |
| `DOCPIPELINE_WINDOW_WORDS` | `220` | Chunk size in words |
| `DOCPIPELINE_OVERLAP_WORDS` | `40` | Overlap in words; `0` is raised to 1, so consecutive chunks always overlap |
| `DOCPIPELINE_ENGINE_MODEL` | `fastino/gliner2.5-multi-v1` | GLiNER2 checkpoint, local path or Hugging Face id |
| `DOCPIPELINE_ENGINE_DEVICE` | `cpu` | `cpu` or `cuda` |
| `DOCPIPELINE_THRESHOLD` | `0.35` | Default score threshold; a schema file overrides it |
| `DOCPIPELINE_DEDUP_DISTANCE` | `80` | Maximum character distance for merging equal occurrences |
| `DOCPIPELINE_MAX_UPLOAD_BYTES` | `52428800` | Upload limit for the API |
| `DOCPIPELINE_ALLOW_PATH_INPUT` | `true` | Allow `{"path": …}` requests in the API |
| `DOCPIPELINE_BASE_DIR` | current directory | Root allowed for path input |
| `DOCPIPELINE_SCHEMA_FILE` | unset | Schema used by the API process |

## Schema files

A schema is TOML or JSON. Unknown keys are rejected.

```toml
model = "fastino/gliner2.5-multi-v1"
threshold = 0.35

[labels]
invoice_number = "Rechnungsnummer oder Belegnummer"
supplier = "Name des Lieferanten oder Verkäufers"
customer = "Name des Kunden oder Käufers"
date = "Ein Datum, zum Beispiel Bestell- oder Fälligkeitsdatum"
amount = "Geldbetrag mit Währung"
```

Rules enforced by `docpipeline.schema.load_schema`:

| Rule | Failure |
|---|---|
| File must exist and parse | `SchemaError` |
| `labels` must contain at least one entry | `SchemaError` |
| Label names must be non-empty | `SchemaError` |
| `threshold` must be within `[0, 1]` | `SchemaError` |
| Unknown top-level keys | `SchemaError` |

Label descriptions are passed to the model and raise precision; an empty
description is allowed. Two example schemas ship in `data/`.

## CLI

```
docpipeline extract PATH... --schema FILE [--out DIR] [--ocr-mode auto|always]
docpipeline ocr PATH --schema FILE
docpipeline bench --docs PATH... --gt DIR --schema FILE [--min-recall FLOAT]
docpipeline export PATH --out FILE --schema FILE
docpipeline serve [--host H] [--port P] [--reload]
```

| Command | Effect |
|---|---|
| `extract` | Writes `DIR/<stem>.json` per file and prints `stem  <entity count>  <extract ms>` |
| `ocr` | Prints the recognised document text, for debugging |
| `bench` | Compares predictions with ground truth and prints a table; `--min-recall` fails the run below the threshold |
| `export` | Writes a Label Studio task with pre-annotations |
| `serve` | Starts uvicorn with `docpipeline.api:app` |

Exit codes: `0` success, `1` processing error, `2` configuration or schema error.

Example run on a six-page article PDF using the text layer, CPU model:

```
$ uv run docpipeline extract article.pdf --schema data/schema.article.toml -o out/
article  20  13894 ms
```

## HTTP API

`create_app(settings, schema=None, ocr=None, extractor=None)` returns a FastAPI
application. `create_router(...)` returns only the `APIRouter` with prefix `/v1`.

| Method | Path | Body | Response |
|---|---|---|---|
| `POST` | `/v1/extract` | multipart `file`, or JSON `{"path": "…"}` | document record |
| `POST` | `/v1/export` | multipart `file`, or JSON `{"path": "…"}` | Label Studio task |
| `GET` | `/v1/health` | – | `{"status", "ocr_reachable", "ocr_model", "engine", "version"}` |
| `GET` | `/v1/schema` | – | `{"model", "threshold", "labels"}` |
| `GET` | `/v1/openapi.json` | – | OpenAPI document |

Error mapping:

| Condition | Status |
|---|---|
| Unsupported file extension | `415` |
| Empty file, missing form field, path outside `base_dir`, path input disabled | `400` |
| Upload larger than `max_upload_bytes` | `413` |
| No schema configured | `409` |
| OCR failed after all attempts | `502` |
| Invalid schema at load time | `422` |

`GET /v1/health` returns `200` even when the OCR endpoint is down, with
`ocr_reachable: false`. The model and the HTTP client are created on first use,
so mounting the router does not load torch.

### Mounting as a plugin

```python
from fastapi import FastAPI
from docpipeline.api import create_router
from docpipeline.config import Settings
from docpipeline.schema import load_schema

app = FastAPI()
app.include_router(
    create_router(Settings(), schema=load_schema("data/schema.invoice.toml")),
    prefix="/docpipeline",
)
```

All routes then live under `/docpipeline/v1/…`.

## Output record

```json
{
  "source": "invoice.pdf",
  "sha256": "5a6f0a25…",
  "pages": 2,
  "ocr": {"model": "paddleocr-vl", "pages_ocr": 1},
  "text": "Rechnung Nr. RE-2026-0042\n…",
  "entities": [
    {"label": "invoice_number", "text": "RE-2026-0042",
     "start": 13, "end": 25, "page": 1, "score": 0.996}
  ],
  "warnings": ["empty_page:2"],
  "timings_ms": {"render": 41.2, "ocr": 25103.0, "extract": 812.7}
}
```

| Field | Meaning |
|---|---|
| `text` | Document text; page texts joined with a blank line. Offsets refer to this string |
| `entities` | Sorted by `(start, label)`; `start` and `end` are character offsets, `page` is 1-based |
| `warnings` | `empty_page:<n>` for pages without recognised text; processing continues |
| `timings_ms` | Wall-clock milliseconds per stage |

## Benchmark and validation

Ground truth is one JSON file per document, named after the document stem:

```json
{"entities": [{"label": "supplier", "text": "Musterwerke GmbH"}]}
```

`bench` matches case-insensitively after whitespace normalisation and reports
per label: recall, precision, true positives, false positives, false negatives,
and documents present in the ground truth but missing from the run.

Demo run included in the repository: one document, three fields, ground truth
read from the PDF by hand.

```
$ uv run docpipeline bench --docs article.pdf --gt data/gt --schema data/schema.article.toml
label                  recall  precision   tp   fp   fn  docs
author                 100.0%      12.5%    1    7    0     0
publication            100.0%      50.0%    1    1    0     0
title                  100.0%      10.0%    1    9    0     0
```

This demonstrates that the measurement path works. It is not an accuracy
claim: one document and three generic labels over running text produce many
false positives by construction. Recall and precision become meaningful with a
labelled set of real documents per document type.

## Label Studio export

`docpipeline export` or `POST /v1/export` writes:

```json
{
  "data": {"text": "…document text…"},
  "meta": {"source": "invoice.pdf", "sha256": "…"},
  "annotations": [{"result": [{"value": {"start": 13, "end": 25,
                                          "text": "RE-2026-0042",
                                          "labels": ["invoice_number"]},
                                "score": 0.996}], "was_cancelled": false}]
}
```

The export exists to produce training data. Pre-annotations speed up manual
correction; they are not verified labels.

## Fine-tuning

Not part of this package. GLiNER2 supports local LoRA training through the
`train` extra:

```bash
uv add "gliner2[train]"
```

The JSONL data format and the training recipes are described in the GLiNER2
repository (`tutorial/8-train_data.md`, `tutorial/9-training.md`,
`tutorial/10-lora_adapters.md`). A fine-tuned checkpoint plugs in without code
changes:

```bash
DOCPIPELINE_ENGINE_MODEL=/path/to/checkpoint uv run docpipeline bench --docs … --gt …
```

or set `model = "/path/to/checkpoint"` in the schema file.

## Development

| Tool | Command | Purpose |
|---|---|---|
| Tests | `uv run pytest` | 94 unit tests, integration tests deselected |
| Integration tests | `uv run pytest -m integration` | real OCR endpoint and real model |
| Types | `uv run mypy` | strict, `src` only |
| Lint | `uv run ruff check src tests` | E, F, I, UP, B, SIM, PL, RUF |
| Coverage | `uv run pytest --cov=docpipeline --cov-branch` | branch coverage |
| Mutation | `uv run python scripts/mutants.py` | seven hand-written mutants, each killed by a named test |
| Everything | `bash scripts/gauntlet.sh` | all layers in one run |
| API smoke test | `bash scripts/api_smoke.sh` | starts uvicorn and calls every route against the real OCR endpoint |

Latest full run: 94 unit tests pass, 4 integration tests pass, mypy and ruff
clean, 7 of 7 mutants killed, 91 % branch coverage. The mapping from
specification to test is in [`EVIDENCE.md`](EVIDENCE.md); the contract is
[`SPEC.md`](SPEC.md).

Unit tests use `httpx.MockTransport` and injected fake extractors. The
integration tests exercise the real components; they need the OCR endpoint
from `DOCPIPELINE_OCR_BASE_URL` and download the model once.

## Design notes

| Decision | Reason |
|---|---|
| Text layer before OCR | OCR of one page took about 25 s on the measured setup; the text layer is exact and immediate |
| Chunking with overlap instead of long-context inference | The encoder has a fixed window; overlapping windows stop entities at chunk borders from being cut off |
| Dedup by label, normalised text, and distance | Overlap produces the same entity twice; a distance bound keeps genuinely repeated values apart |
| `overlap_words=0` is raised to 1 | The pipeline contract states consecutive chunks always overlap; silent disjoint chunks would lose entities |
| No layout features | The OCR endpoint returns plain text without coordinates; the design must not depend on positions |
| Model loaded lazily | Importing `docpipeline.api` must not import torch; the API starts in milliseconds |

## Limits

- The OCR endpoint must be reachable at `ocr_base_url`; there is no local OCR fallback.
- Pages are OCR'd sequentially. One page takes about 25 s on the measured OCR setup, so long scanned documents are slow.
- Requests are handled sequentially per process: one model instance and one shared HTTP client. There is no batching or queue.
- The record contains the full document text, so JSON files grow with document size.
- Only the base checkpoint ships; accuracy on unseen layouts is unknown until measured with `bench`.
- Path input is restricted to `base_dir`; set `DOCPIPELINE_ALLOW_PATH_INPUT=false` when the API is exposed.

## License

MIT. See [LICENSE](LICENSE).
