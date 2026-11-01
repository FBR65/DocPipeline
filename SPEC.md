# SPEC — DocPipeline

Status: **Entwurf, nicht freigegeben.** Kein Code vor Freigabe.

Quelle der Anforderung: Towards-AI-Artikel „Extract Anything From Anywhere: Building
Document AI Pipeline with GLINER Beyond Zero Shot" (Dhanya Shanbhag, Okt. 2026):
Quelldatei → Extraktion → Annotation → Chunking/Sliding Window → Modell → Validierung.
Der Artikel nennt vier Stabilitätsprobleme: Kontextlimit, Duplikate aus dem Overlap,
fehlende Belege (Recall-Benchmark), Layoutabhängigkeit.

Auftrag (wörtlich): „Erstelle ein solches System. PaddleOCR ist unter
http://127.0.0.1:8080/v1 zu erreichen. Es soll OpenAI-kompatible Kommunikation genutzt
werden. Das System soll als CLI (lokal) und als FastAPI (als Plugin für andere Systeme)
gebaut werden. Frage nach bei Entscheidungen. Old-Coder-Prinzip."

## 1. Vorgefundene Umgebung (gemessen, nicht angenommen)

| Fakt | Wert | Nachweis |
|---|---|---|
| OCR-Endpunkt | `http://127.0.0.1:8080/v1` antwortet 200 | `GET /v1/models` |
| Backend | llama-swap (rootless podman, Port 8080) | `/v1/models` → `owned_by: llama-swap` |
| OCR-Modell | `paddleocr-vl`, geladen, Vision | `/v1/models` |
| OCR-Aufruf | `POST /v1/chat/completions`, `image_url` als data-URL (base64) | Testseite 1 des Artikels, Antwort = reiner Text ohne Layout-Boxen |
| OCR-Dauer | 1 Seite, 100 dpi: 25 s Prompt, 1,7 s Generierung | `timings` der Antwort |
| GPU | RTX 4060 Laptop, 8 GB, 3,3 GB belegt | `nvidia-smi` |
| RAM | 30 GB, 23 GB verfügbar | `free -g` |
| Repo | `~/Dokumente/dev/DocPipeline`, git, Python 3.12 (uv), keine Abhängigkeiten | `pyproject.toml` |
| Netz | PyPI 200, HuggingFace 200 | `curl` |
| GLiNER | PyPI 0.2.30, Apache-2.0; `urchade/gliner_multi-v2.1` Apache-2.0 (mehrsprachig, deutsch) | PyPI-JSON, HF-API |

Die OCR liefert **Text**, keine Koordinaten. Das System darf deshalb keine
Layout-Position als Merkmal nutzen (der Artikel nutzt ebenfalls keine).

## 2. Zielbild

```
Datei (PDF/Bild)
  → Seiten rendern (pymupdf)            [Preprocessor]
  → OCR je Seite (OpenAI-kompatibel)    [OcrClient]
  → Text normalisieren + Seitenmarken
  → Chunking mit Sliding Window         [Chunker]
  → Entity-Extraktion                   [Extractor]
  → Deduplizierung über Overlap         [Deduper]
  → Dokument-Record (JSON)
  → optional: Recall/Precision gegen Ground Truth
```

Zwei Zugänge auf denselben Kern: CLI und FastAPI. Der Kern kennt weder CLI noch HTTP.

## 3. Verhaltens-Spezifikation (Vertrag)

Jede Zeile wird zu genau einem Test. `B` = Behavior, `E` = Fehlerfall, `I` = Invariante.

### B1 Seitenaufbereitung
`render_pages(path)` liefert je Seite `(page_no, png_bytes, text_layer_or_none)`.
PDF: 200 dpi Standard, konfigurierbar. Bilder (png/jpg/tif): eine Seite, kein Textlayer.

### B2 OCR-Vertrag
`OcrClient.ocr_image(png) -> str` sendet `POST {base_url}/chat/completions` mit
`model`, `messages[0].content = [{image_url data-url}, {text: prompt}]`,
`temperature=0`. Der Prompt ist konfigurierbar, Standard: Text in Lesereihenfolge,
Markdown, keine Kommentare. Antworttext wird zurückgegeben, Code-Fences werden entfernt.

### B3 Seitenauswahl
Seite mit nutzbarem Textlayer (>= 40 Zeichen) wird ohne OCR übernommen, wenn
`ocr_mode="auto"`. `ocr_mode="always"` erzwingt OCR. Standard aus D3.

### B4 Chunking
`chunk(text, window_words=220, overlap_words=40) -> list[Chunk]`.
Jeder Chunk hat `start`, `end` (Zeichenoffsets im Dokumenttext). Bei
`overlap_words >= window_words` → `ValueError`. Grenzen werden nach Möglichkeit
auf Satzenden (`.\n!?`) gelegt. Überlappung ist garantiert: `chunks[i+1].start < chunks[i].end`.
Property-Test: jedes Wort des Textes liegt in mindestens einem Chunk.

### B5 Extraktion
`Extractor.extract(chunk_text, labels) -> list[Entity]`. Entity = `(label, text, start, end, score)`.
`labels` kommt aus der Schema-Datei: Name + optionale Beschreibung.
GLiNER-`threshold` aus Schema (Standard 0.35). Offsets sind relativ zum Chunk und werden
auf Dokumentoffsets umgerechnet.

### B6 Deduplizierung
Gleiches Label und gleicher normalisierter Text (casefold, Whitespace kollabiert) gelten
als ein Treffer, wenn die Vorkommen sich überlappen oder im gemeinsamen Overlap-Bereich
liegen (`distance_max`, Standard 80 Zeichen). Ergebnis behält den höchsten Score.
Verschiedene Vorkommen desselben Textes außerhalb dieser Distanz bleiben getrennt.
Property-Test: Dedup ist idempotent.

### B7 Dokument-Record
```json
{"source": "…", "sha256": "…", "pages": 6, "ocr": {"model": "paddleocr-vl", "pages_ocr": 6},
 "entities": [{"label": "buyer", "text": "ACME", "start": 120, "end": 124, "page": 1, "score": 0.82}],
 "warnings": [], "timings_ms": {"render": 0, "ocr": 0, "extract": 0}}
```
`entities` ist nach `(start, label)` sortiert — Ausgabe ist deterministisch.
`page` wird aus den Seitenmarken abgeleitet.

### B8 CLI
`docpipeline extract PFAD... --schema S [--out DIR] [--ocr-mode auto|always] [--json]`
schreibt je Datei `DIR/<stem>.json` und gibt eine Zeile je Datei aus (`stem  n_entities  dauer`).
Exitcode 0 bei Erfolg, 1 bei Fehler in mindestens einer Datei, 2 bei Konfigurationsfehler.
`docpipeline serve`, `docpipeline bench`, `docpipeline ocr PFAD` (nur Text ausgeben, Debug).

### B9 API
`create_router(settings) -> APIRouter` (Präfix `/v1`), zusätzlich `docpipeline.api:app`:
- `POST /v1/extract` — multipart `file` **oder** JSON `{"path": "…"}`; Antwort = Dokument-Record.
- `GET /v1/health` — `{"status", "ocr_reachable", "ocr_model", "engine", "version"}`; 200, auch wenn OCR nicht erreichbar (`ocr_reachable=false`).
- `GET /v1/schema` — aktive Labels.
- `GET /v1/openapi.json` vorhanden (FastAPI-Standard).
Das Modul importiert keine CLI-Bibliothek. Ein Fremdsystem kann den Router ohne
Dateisystem-Erweiterung einbinden.

### E1 OCR-Fehler
5xx oder Timeout (Standard 180 s): 3 Versuche, Backoff 1/2/4 s. Danach `OcrError`
mit `page` und letztem HTTP-Status. Teilresultate werden verworfen, nicht geschrieben.

### E2 Ungültige Eingabe
Unbekannte Endung → `UnsupportedFormatError`; API: 415. Leere Datei → 400.
`path` außerhalb der erlaubten Basis → 400 (`PathError`), keine freie Pfadausführung.
Seite ohne erkannten Text → Warnung `empty_page:<n>`, kein Abbruch.

### E3 Schemafehler
Unbekannter Schlüssel, leerer Labelname oder `threshold` außerhalb `[0,1]` → `SchemaError`
mit Feldnamen; CLI-Exitcode 2; API 422 beim Start, nicht mitten im Lauf.

### I1 Netz
Nur `base_url` des OCR-Clients und (einmalig, bei Bedarf) HuggingFace für Modellgewichte.
Kein Telemetrie-Aufruf, keine Cloud.

### I2 Geheimnisse
`api_key` nur aus Umgebung/Config, nie in Ausgabe, Log oder Fehlertext.

### I3 Belege
Der Bench-Befehl `docpipeline bench --gt DIR --docs DIR` berechnet je Label
Recall und Precision gegen JSON-Ground-Truth (`{"entities":[{"label":…,"text":…}]}`),
Abgleich case-insensitiv, Whitespace normalisiert, ohne Offsets. Ausgabe als Tabelle,
`--min-recall` (Standard aus) setzt Exitcode 1 bei Unterschreitung. Ohne Benchmark
gibt es keine Genauigkeitsaussage.

## 4. Was das System nicht tut (jeweils als Entscheidung, nicht als stille Kürzung)

- Kein Web-UI (D7).
- Kein Training ohne Freigabe (D2).
- Keine Koordinaten-Ausgabe, weil die OCR keine liefert (Fakt aus §1).

## 5. Offene Entscheidungen

| ID | Frage | Optionen | Empfehlung |
|---|---|---|---|
| D1 | Extraktions-Engine | (a) GLiNER lokal (Artikel), (b) LLM über vorhandenen llama-swap-Endpunkt, (c) beide als Adapter, GLiNER Standard | **(a)** — Artikel, offline, kein Prompt-Basteln; Apache-2.0 geprüft |
| D2 | Feintuning im Umfang | (a) nein: Inferenz + Annotationsexport (Label-Studio-JSON) für später, (b) ja: Trainingsskript + Datenaufbereitung + Evaluierung | **(a)** — Feintuning braucht annotierte Daten, die es noch nicht gibt; Aufwand Tage statt Stunden (Schätzung) |
| D3 | PDF mit Textlayer | (a) Textlayer nutzen, OCR nur für Seiten ohne Text, (b) immer OCR | **(a)** — gemessen 25 s/Seite OCR; Textlayer ist exakt und sofort |
| D4 | Persistenz | (a) nur JSON-Dateien, (b) JSON + SQLite-Register (Status, Hashes, Dauer) | **(a)** — kleinster Kern; (b) nachrüstbar |
| D5 | API-Form | (a) `create_router()` + Standalone-App + Einstiegspunkt `docpipeline.api:app`, (b) nur Standalone-App | **(a)** — „Plugin für andere Systeme" heißt Router montierbar |
| D6 | CLI-Framework | (a) typer, (b) argparse (Standardbibliothek) | **(a)** — Hilfe/Typen gratis; eine Abhängigkeit mehr |
| D7 | Umfang Stufe 1 | (a) Kern + CLI + API + Bench in vier Stufen mit Stopp nach jeder Stufe, (b) alles in einem Lauf | **(a)** — du kannst nach jeder Stufe anhalten |
| D8 | Torch-Variante | (a) CPU-Wheel (GLiNER small/multi, ~300 MB Modell), (b) CUDA-Wheel (~2,5 GB) | **(a)** — llama-swap belegt die GPU; Extraktion ist nicht der Engpass (OCR ist es) |

Antworten ohne Widerspruch zu D4–D8 setze ich wie empfohlen um, sobald die SPEC
freigegeben ist. D1–D3 und D7 ändern Umfang oder Architektur und brauchen eine Antwort.

## 6. Setup-Plan (mit Freigabe der SPEC autorisiert)

Neue Abhängigkeiten, je mit Begründung:

| Paket | Zweck |
|---|---|
| `pymupdf` | PDF rendern, Textlayer lesen |
| `httpx` | OCR-Client (async, Timeouts, Retry) |
| `pydantic`, `pydantic-settings` | Schema, Record, Konfiguration aus Umgebung |
| `gliner` | NER-Modell (Apache-2.0) |
| `torch` (CPU-Wheel) | Laufzeit für gliner |
| `typer` | CLI (D6) |
| `fastapi`, `uvicorn`, `python-multipart` | API + Upload |
| dev: `pytest`, `pytest-cov`, `pytest-randomly`, `hypothesis`, `ruff`, `mypy`, `mutmut` | Gauntlet |

Modellgewichte: `urchade/gliner_multi-v2.1` (Apache-2.0), einmaliger Download ~500 MB.
Gauntlet-Stufe: **Tier 2** mit Tier-3-Elementen (Property-Tests für Chunker/Dedup,
Fehlermodell für OCR-Ausfall und Pfad-Eingabe), weil die API öffentlich ist.
Checkpoint-Commits nach SPEC, je GREEN/REFACTOR und vor GAUNTLET — nur mit deiner
Freigabe (D9 im Text: „Commits erlaubt?").

## 7. Stufen (Schätzung, keine Zusage)

| Stufe | Inhalt | Behaviors | Schätzung |
|---|---|---|---|
| S1 | Kern: Ingest, OCR, Chunking, Extraktion, Dedup, Record, CLI `extract`/`ocr` | B1–B8, E1–E3, I1–I2 | ~1 Tag |
| S2 | FastAPI: Router-Factory, Standalone-App, Upload | B9 | ~2 h |
| S3 | Bench: Ground-Truth-Abgleich, Recall/Precision, Exitcode | I3 | ~3 h |
| S4 | Annotationsexport (Label Studio) — nur bei D2=(a) sinnvoll | — | ~2 h |

Nach jeder Stufe: Bericht, Stopp, neue Freigabe für die nächste.

## 8. Änderungen nach Freigabe (append-only)

**Ä1 (D1 geändert):** Extraktions-Engine ist jetzt **GLiNER2** lokal, nicht der
LLM-Endpunkt. Geprüft: PyPI `gliner2` 2.1.0, GitHub `fastino-ai/GLiNER2`,
Lizenz Apache-2.0 (Code und Gewichte), Python 3.10–3.12, zusätzliche Extras
`[local]` (torch, transformers) und `[train]`. Ladepfad: `AutoExtractor.from_pretrained(...)`,
API `model.extract_entities(text, labels|dict, ...)` → `{'entities': {label: [...]}}`.
Mehrsprachiges Checkpoint `fastino/gliner2.5-multi-v1` (287M, mDeBERTa) als Standard,
weil Dokumente deutsch sein können. `torch` als CPU-Wheel installiert (D8 bleibt):
Modell 287M läuft auf CPU; die GPU hält llama-swap.
Damit entfallen aus §6 `gliner` und `urchade/gliner_multi-v2.1`; dafür `gliner2[local]`.

**Ä2 (D2 entschieden):** Annotationsexport (Label Studio JSON) wird gebaut.
Ein feinjustiertes Checkpoint wird über `model=` in Schema/Config geladen —
kein Trainingsskript. Training bleibt im README dokumentiert (`gliner2[train]`,
LoRA).

**Ä3 (D7 entschieden):** Alle Stufen in einem Lauf, ohne Zwischenstopp.
Die Stufen bleiben als getrennte Testgruppen sichtbar.

**Ä4 (während der Umsetzung, sichtbar gemacht):**
- B7 erhält das Feld `text` (der erkannte Dokumenttext). Ohne ihn kann der
  Annotationsexport aus Ä2 die Zeichenoffsets nicht prüfen. Kosten: größere
  JSON-Dateien.
- B9 erhält `POST /v1/export` (Label-Studio-Aufgabe) und `GET /v1/schema`
  antwortet `409` ohne Schema; `POST /v1/extract` ebenso `409` statt `422`.
  Grund: fehlende Konfiguration ist ein Zustandskonflikt, kein Eingabefehler.
- B4: `overlap_words=0` wird auf ein Wort angehoben. Der Vertrag „Überlappung
  ist garantiert" gilt damit auch für 0; der Test
  `test_zero_overlap_still_touches` hält das fest (Mutationsprobe hatte die
  Lücke aufgedeckt).
- `ocr_base_url` wird mit dem Modellnamen `paddleocr-vl` genutzt; das Feld
  `ocr_api_key` wird als Bearer-Token gesendet, wenn gesetzt.
- Der Standardwert von `torch` ist das CUDA-Wheel, weil `uv 0.12.5` die
  CPU-Auswahl (`--torch-backend`) nicht kennt. Inferenz läuft trotzdem auf der
  CPU (`engine_device=cpu`). D8 bleibt damit in der Wirkung erfüllt, nicht im
  Wheel.

