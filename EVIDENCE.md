# EVIDENCE — DocPipeline

Stand: alle Stufen in einem Lauf (D7). Quelle: Arbeitsbaum ohne Commit
(`git status`: neue Dateien, kein Commit ohne Freigabe). Ergebnisreproduktion:
`bash scripts/gauntlet.sh` (ein Einstiegspunkt, alle Schichten) und
`bash scripts/api_smoke.sh` (echter API-Lauf).

Gauntlet-Stufe: **Tier 2** mit Tier-3-Elementen (Property-Tests für Chunker und
Dedup, Fehlermodell für OCR-Ausfall, Pfad-Eingabe, Upload-Grenze), weil die
API öffentlich ist.

## 1. Vertrag → Test

| Behavior | Test | Ergebnis |
|---|---|---|
| B1 Seitenaufbereitung | `tests/test_ingest.py` (8) | grün |
| B2 OCR-Vertrag (OpenAI-kompatibel) | `tests/test_ocr.py::test_request_is_openai_compatible`, `::test_code_fences_are_stripped` | grün |
| B3 Seitenauswahl (Textlayer vs. OCR) | `tests/test_ingest.py::test_text_layer_page_needs_no_image`, `::test_ocr_mode_always_ignores_text_layer`, `tests/test_pipeline.py::test_text_layer_is_used_without_ocr` | grün |
| B4 Chunking inkl. Überlappung, Satzende, Property | `tests/test_chunker.py` (8) | grün |
| B5 Extraktion, Offsets, Schema-Weitergabe | `tests/test_extractor.py` (7) | grün |
| B6 Dedup inkl. Idempotenz-Property | `tests/test_dedup.py` (7) | grün |
| B7 Dokument-Record, Seitenzuordnung, Sortierung, sha256 | `tests/test_pipeline.py` (8) | grün |
| B8 CLI (extract/ocr/bench/export, Exitcodes 0/1/2) | `tests/test_cli.py` (11) | grün |
| B9 API (Router, App, health, schema, extract, export, openapi, Mount) | `tests/test_api.py` (14), `tests/test_api_extra.py` (9) | grün |
| E1 OCR-Fehler → Retry 3×, dann `OcrError` mit Seite/Status; API 502 | `tests/test_ocr.py` (7), `tests/test_api_extra.py::test_ocr_failure_maps_to_502` | grün |
| E2 Pfad/Endung/Größe/leer → 415/400/413 | `tests/test_api.py` (4 Fälle), `tests/test_ingest.py` (3 Fälle) | grün |
| E3 Schemafehler → `SchemaError`, CLI 2 | `tests/test_schema.py` (8) | grün |
| I1 nur OCR-`base_url` + HuggingFace | Prüfung: `grep -rn "http" src/` findet nur `http://127.0.0.1:8080/v1` in `config.py` | erfüllt |
| I2 kein Geheimnis in Fehlertext | `tests/test_ocr.py::test_api_key_not_leaked_in_error` | grün |
| I3 Recall/Precision, Exitcode bei `--min-recall` | `tests/test_bench.py` (5), `tests/test_cli.py` (2 Bench-Fälle) | grün |

## 2. Gauntlet, ein frischer Lauf (`bash scripts/gauntlet.sh`, Exitcode 0)

| Schicht | Kommando | Ergebnis |
|---|---|---|
| Tests | `uv run pytest -p no:randomly --cov=docpipeline --cov-branch` | **94 passed**, 4 deselektiert |
| Testreihenfolge | `uv run pytest -p randomly` | **94 passed**, keine Reihenfolgeabhängigkeit |
| Typen | `uv run mypy` (strict) | **keine Fehler, 15 Dateien** |
| Lint | `uv run ruff check src tests` | **All checks passed** |
| Mutation | `uv run python scripts/mutants.py` | **7 von 7 getötet** |
| Echt-Teile | `uv run pytest -m integration` | **4 passed** (echtes OCR, echtes Modell) |

Abdeckung (Zweigabdeckung, derselbe Lauf):

```
__init__.py 100%  api.py 89%  bench.py 88%  chunker.py 92%  cli.py 79%
config.py 100%    dedup.py 100%  errors.py 100%  export.py 100%
extractor.py 90%  ingest.py 100%  ocr.py 90%  pipeline.py 95%
records.py 100%   schema.py 91%  TOTAL 91% (748 Anweisungen, 62 nicht ausgeführt)
```

Nicht ausgeführte Zeilen und warum: `cli.py` 33–46 ist `serve` (startet uvicorn,
wird über `scripts/api_smoke.sh` real geprüft statt per Unit-Test), `api.py`
195–198 ist der Modul-Start mit `DOCPIPELINE_SCHEMA_FILE` (im Smoke-Lauf aktiv),
`extractor.py` 106–108 ist `_load()` (von den Integrationstests abgedeckt).

Mutationsprobe: 7 handgeschriebene Mutanten, jeder von genau dem genannten Test
erkannt. Mutant 2 (Überlappung fällt auf 0) überlebte im ersten Durchgang; die
Ursache war eine echte Lücke im Property-Test (Zufall zog `overlap=0` nicht
zuverlässig). Behoben durch den Test `test_zero_overlap_still_touches`, danach
getötet. Das ist der einzige Fall, in dem ein Test nach der Umsetzung ergänzt
wurde; keine Zusicherung wurde abgeschwächt.

## 3. Mit Testdoppel geprüft vs. mit echter Komponente geprüft

| Kriterium | Doppel | Echt |
|---|---|---|
| OCR-Aufrufform (Modell, data-URL, temperature 0), Retry, Fence-Strip | ja (`httpx.MockTransport`) | ja: `test_ocr_reads_a_page` liest Seite 1 des Artikel-PDF über `http://127.0.0.1:8080/v1` (`paddleocr-vl`) |
| Extraktion, Offsets, JSON-Antwortform | ja (`FakeModel`, echte Antwortform als Fixture) | ja: `test_model_extracts_from_real_text` mit `fastino/gliner2.5-multi-v1` auf CPU |
| Ganze Pipeline, Seitenzuordnung, Dedup | ja (`FakeOcr`, `FakeExtractor`) | ja: `test_pipeline_on_article_uses_text_layer` (6 Seiten, 0 OCR-Seiten) |
| API-Endpunkte | ja (`TestClient`) | ja: `scripts/api_smoke.sh` gegen laufenden uvicorn |

## 4. Echte Läufe (Ausgabe, nicht Erwartung)

**CLI, Artikel-PDF (6 Seiten, Textlayer):**

```
$ uv run docpipeline extract "<Artikel>.pdf" --schema data/schema.article.toml -o /tmp/dp_out
Extract Anything From Anywhere_ ... _ by Dhanya Shanbhag _ Oct, 2026 _ Towards AI  20  13894 ms
real 0m16,750s
```

20 Entitäten, 13,9 s Extraktion, 16,8 s gesamte Laufzeit auf CPU. Das Modell
wurde in diesem Lauf von der Platte geladen (Kaltstart enthalten).

**Bench (Demo-Ground-Truth, 1 Dokument, 3 Felder, von Hand aus dem PDF gelesen):**

```
$ uv run docpipeline bench --docs "<Artikel>.pdf" --gt data/gt --schema data/schema.article.toml
label                  recall  precision   tp   fp   fn  docs
author                 100.0%      12.5%    1    7    0     0
publication            100.0%      50.0%    1    1    0     0
title                  100.0%      10.0%    1    9    0     0
```

Ein Dokument, drei Felder: **das ist keine Genauigkeitsaussage.** Es zeigt nur,
dass der Messweg läuft. Die niedrige Precision ist erwartbar, weil drei
allgemeine Labels über einen Fließtext laufen; der Artikel selbst nennt 93,2 %
Recall auf seinem eigenen feinjustierten Modell und Datensatz, nicht hier.

**API (`scripts/api_smoke.sh`, echter Server, echte OCR):**

```
== health
{"status":"ok","ocr_reachable":true,"ocr_model":"paddleocr-vl",
 "engine":"fastino/gliner2.5-multi-v1","version":"0.1.0"}
== openapi 200
== extract als Pfad  -> pages 1, ocr.pages_ocr 1, echter OCR-Text der Artikelseite
== extract als Upload -> source seite1.png, entities 8
== pfad ausserhalb der basis -> 400
== ungueltige endung -> 415
```

**Supply Chain:** `uv run --with pip-audit pip-audit` → „No known vulnerabilities found".
Neue Lizenzen: `gliner2` Apache-2.0, Checkpoints `fastino/gliner2*` Apache-2.0
(vor dem SPEC über PyPI- und HF-API geprüft).

## 5. Bekannte Grenzen

- Kein feinjustiertes Checkpoint (D2): die Genauigkeit ist die des
  Basis-Checkpoints; ein eigenes Checkpoint wird nur über `model=` geladen.
- Keine GPU-Messung: `torch` ist ein CUDA-Wheel, die Inferenz läuft auf CPU
  (`engine_device=cpu`). Die GPU hält llama-swap.
- `serve` ist nur über den Smoke-Lauf geprüft, nicht per Unit-Test.
- Kein Lasttest: die API verarbeitet Anfragen seriell je Prozess (ein
  Modell im Speicher, ein `httpx.Client`).
- Kein Commit: das Repo hat noch keinen Commit dieser Arbeit; Checkpoint-Commits
  waren nicht freigegeben.
