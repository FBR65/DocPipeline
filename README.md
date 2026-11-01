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
| Dual OCR mode (`docpipeline-dual`): cells, three readers, majority | implemented, tested; **not** benchmarked against single-engine results |
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
uv run docpipeline extract invoice.pdf --schema schema.toml -o out/

# the same document through the HTTP API
DOCPIPELINE_SCHEMA_FILE=schema.toml uv run docpipeline serve
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
description is allowed. The schema file is yours to keep; it is not part of this package.

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
$ uv run docpipeline extract article.pdf --schema schema.toml -o out/
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
    create_router(Settings(), schema=load_schema("schema.toml")),
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

## Dual OCR mode (two engines, three readers)

`docpipeline-dual` runs **both** OCR engines over every page and merges the
results. It exists because the two engines fail differently: on a scanned tax
notice, `paddleocr-vl` read the amounts correctly (`-9.874,00`) while
`dots-mocr` got them wrong (`-9.876,00`), and `dots-mocr` read the names
correctly ("Steuernummer", "Beispiel & Partner GmbH") where paddle produced
"Stauernnummer". Neither engine is reliably better, so the system keeps both
values and marks whether they agree.

| Stage | Behaviour |
|---|---|
| Render | paddle at 300 dpi, dots.mocr at 200 dpi (each engine renders its own image) |
| Phase A | all pages through `paddleocr-vl`, two pages in parallel |
| Phase B | all pages through `dots-mocr`, two pages in parallel |
| Text layer | kept as a third source when the PDF has one; it does not replace OCR |
| Cells | numbers are also read per table cell (dots HTML grid, paddle OTS grid); each cell is read with its row and column header; a hit carries `sources[].zelle` |
| Third reader | `rapidocr` (PP-OCR, ONNX, CPU) reads the page in ~3 s and votes as a third source |
| Union | numeric values are keyed by `(page, number)` — the label is not part of the key; agreement `consensus`, `majority` or `single` |
| Conflicts | different values on the same page stay as two entities plus the warning `conflict:<label>:<page>` |
| Verify | every entity is re-read from its bounding box at 300 dpi by `rapidocr`, falling back to `paddleocr-vl`; `verified` is `true`, `false` or `null` |

```bash
uv run docpipeline-dual extract scan.pdf --schema schema.toml -o out/
uv run docpipeline-dual extract scan.pdf --schema schema.toml --no-verify
DOCPIPELINE_SCHEMA_FILE=schema.toml uv run docpipeline-dual serve
```

| Variable | Default | Meaning |
|---|---|---|
| `DOCPIPELINE_ENGINE_A_MODEL` | `paddleocr-vl` | text engine |
| `DOCPIPELINE_ENGINE_A_DPI` | `300` | render resolution for the text engine |
| `DOCPIPELINE_ENGINE_B_BASE_URL` | same as `OCR_BASE_URL` | endpoint for the layout engine |
| `DOCPIPELINE_ENGINE_B_MODEL` | `dots-mocr` | layout engine |
| `DOCPIPELINE_ENGINE_B_DPI` | `200` | render resolution for the layout engine |
| `DOCPIPELINE_ENGINE_B_PROMPT` | official layout prompt | without it `dots.mocr` returns boxes but no text |
| `DOCPIPELINE_ENGINE_B_MAX_TOKENS` | `8000` | a truncated answer is an error, not a shorter document |
| `DOCPIPELINE_DUAL_WORKERS` | `2` | parallel pages per engine phase |
| `DOCPIPELINE_ENGINE_C_DPI` | `300` | render resolution for the third reader |
| `DOCPIPELINE_DUAL_ENGINE_C` | `true` | run RapidOCR as third reader when installed (D3a) |
| `DOCPIPELINE_DUAL_VERIFY` | `true` | region re-read, RapidOCR first, paddle as fallback (`--no-verify` turns it off) |

Agreement classes: `consensus` (every present source names the value), `majority`
(at least two of three, but not all), `single` (one source). A tie at the top
stays `single` for both values and is reported as `conflict:<label>:<page>` —
the record never picks a winner by confidence.

Numbers are compared by value, not by string: `98.765`, `98.765,00` and
`98.765.00` are the same vote, and the label does not take part in the key — one
reader calling a value `amount` and another `tax_number` still counts as two
votes. The winning label comes from the best-scoring source, every label is kept
in `sources[].label`, and a disagreement is reported as
`label_conflict:<page>:<value>`. Text without a number stays bound to its label.

Install the third reader with `uv sync --extra rapid`; without it the run uses
two engines and warns `engine_c_unavailable`.

The record is the same shape as the single-engine record, extended additively:

```json
{
  "text": "…text of the text layer, else of engine A…",
  "variants": {"paddleocr-vl": "…", "dots-mocr": "…", "text_layer": "…"},
  "ocr": {"model": "paddleocr-vl + dots-mocr", "pages_ocr": 2,
          "engines": [{"name": "paddleocr-vl", "dpi": 300, "pages": 1},
                      {"name": "dots-mocr", "dpi": 200, "pages": 1}]},
  "cells": [{"page": 1, "table": 0, "rows": 4, "cols": 3,
             "engines": ["dots-mocr", "paddleocr-vl"]}],
  "entities": [{"label": "amount", "text": "1.428,50", "normalized": "1428.50",
                "start": 174, "end": 182, "page": 1, "score": 0.99,
                "engine": "paddleocr-vl", "agreement": "majority", "verified": true,
                "sources": [{"engine": "paddleocr-vl", "start": 174, "end": 182, "score": 0.99,
                             "label": "amount"},
                            {"engine": "dots-mocr", "start": 181, "end": 189, "score": 0.93,
                             "label": "tax_number", "zelle": [0, 2, 1]},
                            {"engine": "rapidocr", "start": 190, "end": 198, "score": 0.88,
                             "label": "amount"}]}]
}
```

### Measured behaviour on a 27-page tax notice

Both changes above were checked against a real document, not only against
tests. The result is sobering and is therefore part of the documentation:

| Value (page 1) | dots.mocr | paddleocr-vl | rapidocr |
|---|---|---|---|
| income tax | 54.321 | 54.322,00 | 54.326,00 |
| solidarity surcharge | -56,78 | – | – |
| tax number | 12/345/67890 | B421 | 0123 456-789 |
| date | 01.02.2024 | 03.04.2025 | 02.03.2024 |
| recognised numbers (all pages) | 30 | 6 | 5 |

All amounts, names and dates in this section are anonymised: the shape of the
values is kept, the values themselves are replaced. The intersection of numeric
values is **empty for every pair of readers**:
paddle ∩ dots = 0, paddle ∩ rapid = 0, dots ∩ rapid = 0. On this document the
readers do not merely write the same number differently — they read different
digits. No voting rule can produce a majority from that, and none is claimed to.
What the run does produce: two `label_conflict` reports (the same number labelled
`amount` by one reader and `tax_number` by another), 47 entities, 4 conflicts,
and, with verification enabled, a per-entity second reading.

Cells are the reason `dots.mocr` finds five times as many numbers as the text
readers: it returns real table grids, while `paddleocr-vl` returns a page-wide
grid only with the prompt `Table Recognition:` and `rapidocr` returns no grid at
all. Grids from the two engines are not comparable cell by cell (a 4x2 table
against a 22x5 page grid), so cell-level votes rarely form either.

Measured cost per page: 43 s (paddle, 300 dpi) + 30 s (dots.mocr, 200 dpi) + 3 s
(rapidocr, 300 dpi). Each
region re-read costs roughly another 20–30 s, once per distinct bounding box, so
a one-page document with twenty boxes needs about ten minutes with verification
enabled; `--no-verify` skips only that stage. A repeated call on the *same* page
image is much cheaper because the server caches the image part of the prompt; a
cropped region is a new image and is not cached.

Limits of this mode:

- There is **no benchmark** comparing the merged result with a single engine.
  The union preserves both readings and exposes disagreement; it does not prove
  that the merged output is better. Treat `agreement` and `verified` as review
  signals, not as guarantees.
- Both engines always run, even for born-digital PDFs, so the mode is slower by
  design.
- Bounding boxes are pixels of the engine's own raster; they are converted to
  PDF points before cropping.
- Numbers are compared by value and without the label, so a page that contains
  the same number twice with different meanings (`212` as a tax number and
  `432,00` as an amount) is reported as one finding with a `label_conflict`.
- Grids of different engines are not aligned; a cell hit is evidence from one
  reader, not a vote.

## Benchmark and validation

Ground truth is one JSON file per document, named after the document stem:

```json
{"entities": [{"label": "supplier", "text": "Musterwerke GmbH"}]}
```

`bench` matches case-insensitively after whitespace normalisation and reports
per label: recall, precision, true positives, false positives, false negatives,
and documents present in the ground truth but missing from the run.

A run on a single document with three labels looks like this (percentages are
the share of ground-truth values that were found and of the predictions that
were correct):

```
$ uv run docpipeline bench --docs invoice.pdf --gt gt/ --schema schema.toml
label                  recall  precision   tp   fp   fn  docs
author                 100.0%      12.5%    1    7    0     0
publication            100.0%      50.0%    1    1    0     0
title                  100.0%      10.0%    1    9    0     0
```

Those numbers come from one document and three generic labels over running
text, which produces many false positives by construction. They show that the
measurement path works, not that the pipeline is accurate. Recall and precision become meaningful with a
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
| Tests | `uv run pytest` | 251 unit tests, integration tests deselected |
| Integration tests | `uv run pytest -m integration` | real OCR endpoints and real model |
| Types | `uv run mypy` | strict, `src` only |
| Lint | `uv run ruff check src tests` | E, F, I, UP, B, SIM, PL, RUF |
| Coverage | `uv run pytest --cov=docpipeline --cov-branch` | branch coverage |
| Mutation | `uv run python scripts/mutants.py` | twenty-one hand-written mutants, each killed by a named test |
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
