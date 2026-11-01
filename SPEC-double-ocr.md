# SPEC — Doppel-OCR-System (DocPipeline Dual)

Status: **Entwurf, nicht freigegeben.** Kein Code vor Freigabe.

Basis: `DocPipeline` (Repo `FBR65/DocPipeline`). Dieses Dokument beschreibt ein
neues System auf demselben Kern: zwei OCR-Engines je Seite, Abgleich der
Treffer, Marker für Übereinstimmung, optional Nachlesen von Zahlenregionen.

> Alle Beträge, Namen, Anschriften und Datumsangaben in diesem Dokument sind
> anonymisiert: Zeichenform und Stellen bleiben erhalten, die Werte sind ersetzt.

## 1. Gemessene Grundlage (nicht angenommen)

Gleicher Endpunkt `http://127.0.0.1:8080/v1`. Zwei Messungen: eine Artikelseite
(100 dpi, gemischt digital) und eine echte Scanseite aus dem Steuerbescheid im
Projektordner (kein Textlayer, gewählte Auflösungen 300 / 200 dpi).

| Größe | paddleocr-vl | dots-mocr |
|---|---|---|
| Ausgabe | reiner Text | Layout-JSON: `bbox`, `category`, `text`; Tabellen als HTML |
| Artikelseite, 100 dpi | 1356 Zeichen, 187 Wörter | 1497 Zeichen, 204 Wörter, 59 Elemente |
| **Scanseite, 300 / 200 dpi** | 1448 Zeichen, 58 Zahlen-Token, **43,2 s** | 2064 Zeichen, 41 Zahlen-Token, 24 Elemente, **29,8 s** |
| Prompt-Token | 1306 | 5172 |
| Zahlen der Scanseite | 19 gemeinsam, 39 nur paddle, 22 nur dots | |
| Tabellen-Ausgabe | mit `Table Recognition:` **OTS-Markup** (`<fcel>`, `<lcel>`, `<ecel>`, `<nl>`); **kein** HTML, kein Markdown, auch auf ausdrückliche Aufforderung | Tabellen als HTML im `text`-Feld |
| Stärke | Formeln als LaTeX, dichte Zahlenkolonnen, Ziffern der Beträge richtig | korrekte Namen („Steuernummer", „Beispiel & Partner GmbH"), Layout-Boxen je Element |
| Schwäche | „Stauernnummer", „Stouerberatungsges.", erfundene Formel `\( p_1, p_2 \)` | Ziffernfehler bei Beträgen (siehe unten) |

Gegenprobe am Bild (Region der Betragstabelle, 300 dpi, von Hand gelesen):
`-9.874,00`, `2.343,00`, `98.765,00`, `432,00`. Damit liegt **paddle richtig**
und **dots falsch** (`-9.876,00`, `2.345,00`). Die Annahme „dots liest Zahlen
besser" ist für dieses Dokument widerlegt.

Wiederholte Aufrufe auf dasselbe Seitenbild sind billig: erster Aufruf 42,2 s,
gleiche Seite mit anderem Prompt 6,3 s (Prompt-Cache des Servers). Für B6 gilt
das **nicht**, weil dort ein neuer Bildausschnitt gesendet wird.

Kosten je Seite im Doppellauf: **73 s** (43,2 + 29,8) auf einer einzelnen Scanseite.

Folgen für den Entwurf:

- dots.mocr liefert Text **nur** mit dem offiziellen Layout-Prompt der
  Modellkarte (`rednote-hilab/dots.mocr`). Mit einem generischen OCR-Prompt
  kommen nur `bbox` und `category`. Der Prompt ist Teil der Konfiguration.
- Keine Engine ist allein „optimal": jede hat Felder, die die andere verliert,
  und jede erzeugt Fehler. Übereinstimmung ist ein brauchbares Signal,
  Nicht-Übereinstimmung ein Prüfauftrag.
- Die Engines unterscheiden sich bei **Beträgen in der Ziffer**, nicht nur im
  Trennzeichen. Gegenprobe am Bild: paddle liefert `-9.874,00`, dots
  `-9.876,00`. Deshalb reicht eine Format-Normalisierung nicht; Regionen-
  Nachlesen (B6) ist die einzige Prüfung, die den richtigen Wert zeigt.
- Keine Engine ist durchgehend die bessere. Namen: dots. Betragsziffern: paddle.
  Die Fusion darf deshalb **keine** Engine bevorzugen; sie führt beide Werte und
  markiert den Widerspruch (E2).
- Tabellen kommen von dots.mocr als HTML. Für den Textabgleich werden die
  Zellen zu Klartext entpackt (B2); das HTML wird zusätzlich als `tables`
  behalten, damit nichts verloren geht.
- Ein Modellwechsel kostet einen Neuladevorgang (paddle 35 s statt 25 s warm).
  Deshalb laufen die Seiten je Engine gebündelt, nicht im Wechsel (D3).

## 2. Entscheidungen (vom Auftraggeber beantwortet)

| ID | Entscheidung | Folge |
|---|---|---|
| D1 | **A** als Standard: Union auf Entitäts-Ebene mit `agreement`-Marker; **C** als Schalter `--verify-numbers` | zwei Extraktionsläufe je Seite, danach Zusammenführung |
| D2 | Doppel-OCR ist **Pflicht bei jeder Seite**, auch bei Seiten mit Textlayer | Textlayer wird zur **dritten** Quelle, nicht zum Ersatz |
| D3 | Seiten **parallel, je Engine gebündelt**, 2 Worker | Phase 1: alle Seiten Engine A, Phase 2: alle Seiten Engine B |
| D4 | Diese SPEC, kein Code | dieser Text |
| D5 | **(a)** gleiches Repo, neues Modul `docpipeline/dual/` | gemeinsamer Kern, keine Kopie |
| D6 | **(b)** v1-Record um optionale Felder erweitern | kein neues Format, kein `schema_version`-Sprung |
| D7 | **(a)** alle Variantentexte mitspeichern | Datei wird etwa dreimal so groß, Offsets bleiben prüfbar |
| D8 | **(b)** Abbruch, wenn eine Engine ausfällt | kein Teilresultat; Fehler nennt Engine und Seite |
| D9 | **(b)** `--verify-numbers` prüft **alle** Labels | Regionenprüfung ist Standard, nicht Ausnahme; Genauigkeit vor Geschwindigkeit |
| D10 | kein Abnahmekriterium, kein gesonderter Bericht | die Fusion wird nicht gegen die Einzelengines gemessen; der Nutzen bleibt unbelegt (siehe Risiken) |
| D11 | Renderauflösung je Engine: **paddleOCR 300 dpi**, **dots.mocr 200 dpi** | je Seite zwei Renders; Renderschlüssel `(seite, dpi)` |

## 3. Auslegung von D10 (sichtbar gemacht, nicht stillschweigend)

„Kein Kriterium, kein Bericht" wird so umgesetzt:

- Kein Gate: der Lauf bricht nicht ab, wenn die Fusion schlechter ist.
- Kein eigener Fusions-Benchmark und kein Vergleichsbericht je Engine in Stufe 4.
- Das Kommando `bench` aus dem Basissystem bleibt verfügbar, weil es schon
  existiert; es ist aber **kein** Abnahmekriterium dieses Auftrags.
- Die EVIDENCE des Auftrags (Regel 4: SPEC → RED → GREEN → GAUNTLET → EVIDENCE)
  bleibt bestehen. Sie belegt, **dass** die Verhaltensweisen B1–B8 und E1–E3
  gelten, nicht **dass** die Fusion bessere Ergebnisse liefert.

Wer den Nutzen belegt haben will, braucht eine Ground-Truth-Menge mit
Zahlenfeldern. Die gibt es derzeit nicht.

## 4. Offene Entscheidungen (brauchen Antwort)

| ID | Frage | Optionen | Empfehlung |
|---|---|---|---|
| D12 | Was steht im Feld `text` des Records, wenn alle Varianten gespeichert sind? | (a) Textlayer, sonst Engine A; (b) immer Engine A | **(a)** — der Textlayer ist exakt, wenn vorhanden |
| D13 | Fehlertext bei Abbruch nach D8 | (a) `OcrError` mit Engine und Seite; (b) eigene Fehlerklasse `EngineFailure` | **(a)** — bestehender Fehlertyp, bestehende API-Abbildung (502) |
| D14 | Wo der Schalter `--verify-numbers` standardmäßig steht | (a) aus (Opt-in), (b) an (Opt-out) | **(b)** — D9 sagt Genauigkeit vor Geschwindigkeit |

## 5. Zielbild

```
Datei ─► Seiten ─┬─► Textlayer-Text (falls vorhanden)              ─┐
                 ├─► OCR Engine A (paddleocr-vl), 300 dpi, alle Seiten ├─► Varianten je Seite
                 └─► OCR Engine B (dots-mocr),    200 dpi, alle Seiten ┘
   ─► Chunking je Variante ─► GLiNER2 je Variante ─► Union + Numerik-Normalisierung
   ─► agreement (both | single | text_layer) ─► Regionen nachlesen (D9b) ─► Record
```

## 6. Verhaltens-Spezifikation

`B` = Behavior, `E` = Fehlerfall, `I` = Invariante.

### B1 Zwei Engines, jede Seite
`dual_ocr(page) -> Variants`. Für jede Seite laufen beide Engines, auch wenn ein
Textlayer existiert. Gerendert wird je Engine mit eigener Auflösung (D11):
Engine A 300 dpi, Engine B 200 dpi. Aufrufreihenfolge: Phase A alle Seiten, dann
Phase B alle Seiten, je Phase zwei Seiten gleichzeitig (D3). Ein Textlayer-Text
wird als Variante `text_layer` geführt, nie verworfen. Fehlt ein Textlayer,
existiert diese Variante nicht.

### B2 Strukturquellen beider Engines
**Engine B (dots.mocr):** `DotsOcrClient.ocr_page(image, page_no) -> PageLayout` sendet den
offiziellen Layout-Prompt, `temperature=0`, `max_tokens=8000`. Antwort ist ein JSON-Objekt
oder eine Liste. Je Element: `bbox`, `category`, `text` (bei `Picture` darf
`text` fehlen). Daraus entstehen:
- `text`: Elementtexte in Lesereihenfolge, getrennt durch Zeilenumbruch.
  Tabellen-Elemente enthalten HTML (`<table>…`); für `text` werden Tags
  entfernt und Zellen mit einem Leerzeichen verbunden, damit der Extraktor
  keine Markup-Reste sieht.
- `boxes`: Liste aus `bbox`, `category`, `text` (unverändert, für B6).
- `tables`: das HTML je Tabellen-Element, unverändert, damit beim Entpacken
  nichts verloren geht.

**Engine A (paddleocr-vl) liefert kein HTML.** Gemessen mit drei Prompts
(offizielles `Table Recognition:`, ausdrücklicher HTML-Auftrag, Markdown-Tabelle):
null `<table>`, null `|`. Mit dem offiziellen Prompt kommt stattdessen **OTS**:
Zellen als `<fcel>` (gefüllt), `<lcel>` (Fortsetzung links), `<ecel>` (leer),
`<nl>` (Zeilenende). `PaddleOcrClient` muss beide Formen liefern:
- `text`: OTS-Marker entfernt, Zellen in Lesereihenfolge, Zeilenumbrüche an `<nl>`.
- `tables`: Zellraster aus `<fcel>`/`<lcel>`/`<ecel>`/`<nl>` als `list[list[str]]`.

Ist die Antwort kein gültiges JSON (Engine B) oder `finish_reason != "stop"` →
`OcrError(page)`.

### B3 Chunking und Extraktion je Variante
Jede Variante wird mit dem bestehenden Chunker und Extraktor verarbeitet.
Offsets einer Entität gelten immer im Text **ihrer** Variante und werden mit
`engine` gespeichert.

### B4 Numerik-Normalisierung
`normalize_value(text) -> str` bildet für den Abgleich eine Zahlform:
Tausenderpunkte und Dezimalkomma nach deutscher Schreibweise werden erkannt,
`1.428,50 EUR` → `1428.50`; `€ 1,428.50` → `1428.50`. Ohne erkannte Zahl gilt
`normalize()` der Basis (casefold, Whitespace kollabiert). Property-Test:
`normalize_value` ist idempotent, und `1.428,50` = `1.428.50` = `1428,50`.

### B5 Union
Vereinigungsschlüssel: `(label, page, normalize_value(text))`. Kein
Zeichenabstand über Varianten hinweg — Offsets aus verschiedenen Texten sind
nicht vergleichbar. Ergebnis je Eintrag:
`{label, value, normalized, page, sources: [{engine, start, end, score}], agreement}`.
`agreement = "both"` bei mindestens zwei Engines, `"text_layer"` wenn zusätzlich
der Textlayer zustimmt, `"single"` bei genau einer Quelle. Score = Maximum der
Quellen. Sortierung `(page, start der ersten Quelle, label)`.

### B6 Regionen-Nachlesen (Standard, D9b/D14)
Für **jede** Entität: die `bbox` der dots.mocr-Variante suchen, die den Treffer
enthält (Textvergleich normalisiert; bei mehreren die erste in Lesereihenfolge),
Region mit `pymupdf` in 300 dpi rendern, an Engine A schicken, Antwort mit
`normalize_value` vergleichen. Ergebnis `verified: true|false|unavailable` je
Entität. `unavailable` ohne passende `bbox` oder ohne brauchbare Antwort.
Abschaltbar mit `--no-verify`, CLI und API (`verify=false`).

### B7 Record (v1, additive Felder nach D6b)
```json
{"source": "…", "sha256": "…", "pages": 6, "text": "…",
 "variants": {"text_layer": "…", "paddleocr-vl": "…", "dots-mocr": "…"},
 "ocr": {"model": "paddleocr-vl + dots-mocr", "pages_ocr": 12,
         "engines": [{"name": "paddleocr-vl", "model": "paddleocr-vl", "dpi": 300, "pages": 6},
                     {"name": "dots-mocr", "model": "dots-mocr", "dpi": 200, "pages": 6}]},
 "entities": [{"label": "amount", "text": "1.428,50 EUR", "normalized": "1428.50",
               "start": 174, "end": 186, "page": 3, "score": 0.99,
               "engine": "paddleocr-vl", "agreement": "both", "verified": true,
               "sources": [{"engine": "paddleocr-vl", "start": 174, "end": 186, "score": 0.99},
                           {"engine": "dots-mocr", "start": 181, "end": 193, "score": 0.93}]}],
 "warnings": [], "timings_ms": {"render": 0, "ocr_a": 0, "ocr_b": 0, "extract": 0, "verify": 0}}
```
`text` ist nach D12a der Textlayer, sonst die Variante von Engine A. `start`,
`end` und `engine` auf oberster Ebene wiederholen die erste Quelle, damit Leser
der alten Form weiter funktionieren. Alle Felder außer `sources`, `variants`,
`agreement`, `verified`, `normalized` und den `engines`-Details sind wie bisher.

### B8 CLI und API
`docpipeline-dual extract PATH... --schema S [--out DIR] [--no-verify]`
und `docpipeline-dual serve`. Exitcodes wie Basis: 0 / 1 / 2.
API: `POST /v1/extract` mit Feld `verify` (Standard `true`), `GET /v1/health`
nennt je Engine `reachable`, `GET /v1/schema` wie Basis. Das neue System nutzt
dieselben Pfade, weil der Record nach D6b v1 bleibt; ein zweiter API-Prefix
würde zwei Formate behaupten, die es nicht gibt.

### E1 Engine-Ausfall
Eine Engine liefert nach Wiederholungen keinen Text: **Abbruch** (D8b), `OcrError`
mit Engine-Name und Seite (D13a), kein Record, keine Teilausgabe. Die API
antwortet 502.

### E2 Widersprüchliche Zahlen
Zwei Engines liefern für dasselbe Label auf derselben Seite verschiedene
normalisierte Werte: beide Entitäten bleiben, `agreement = "single"`, Warnung
`conflict:<label>:<seite>`. Der Wert wird nicht stillschweigend gewählt.

### E3 Layout ohne brauchbare Boxen
Regionen-Nachlesen ohne `bbox` oder ohne lesbare Region → `verified=unavailable`,
kein Abbruch, Warnung `verify_skipped:<label>:<seite>`.

### I1 Keine Erfolgsaussage
Es gibt **kein** Abnahmekriterium und keinen Fusionsbericht (D10). Gemessen wird
nur, was für den Betrieb nötig ist: Dauer je Phase im Record. Ob die Fusion
bessere Ergebnisse liefert als eine Einzelengine, ist mit diesem Auftrag
**nicht belegt** und wird auch nicht behauptet.

### I2 Determinismus
Gleiche Eingabe, gleiche Modelle, `temperature=0` → gleiche Reihenfolge der
Einträge und gleiche Sortierschlüssel. Zwei Läufe auf demselben Rechner werden
verglichen; Abweichung ist ein Fehler.

### I3 Kein stiller Verlust
Jede Entität einer Quelle steht im Record, entweder als eigener Eintrag oder in
`conflict`-Paaren. Test: Summe der Quellen-Einträge = Summe der Einträge
(+ Paare bei Konflikt).

## 7. Setup-Plan

Keine neuen Abhängigkeiten. Genutzt werden `pymupdf` (Rendern, Cropping), `httpx`
(beide Clients), `pydantic` (Record). Neue Konfiguration:

| Variable | Standard | Bedeutung |
|---|---|---|
| `DOCPIPELINE_ENGINE_A_MODEL` | `paddleocr-vl` | Text-Engine |
| `DOCPIPELINE_ENGINE_A_DPI` | `300` | Render für Engine A (D11) |
| `DOCPIPELINE_ENGINE_B_BASE_URL` | wie Engine A | Endpunkt für Engine B |
| `DOCPIPELINE_ENGINE_B_MODEL` | `dots-mocr` | Layout-Engine |
| `DOCPIPELINE_ENGINE_B_DPI` | `200` | Render für Engine B (D11) |
| `DOCPIPELINE_ENGINE_B_PROMPT` | offizieller Layout-Prompt | ohne ihn liefert dots.mocr keinen Text |
| `DOCPIPELINE_ENGINE_B_MAX_TOKENS` | `8000` | Abschneiden wird als Fehler erkannt |
| `DOCPIPELINE_DUAL_WORKERS` | `2` | gleichzeitige Seiten je Engine-Phase |
| `DOCPIPELINE_DUAL_VERIFY` | `true` | Regionen-Nachlesen (D14) |

Gauntlet-Stufe: **Tier 3** (öffentliche API, zwei externe Systeme, Zahlen als
Geschäftsdaten): Property-Tests für Normalisierung und Union, Konfliktfälle,
Abbruch je Engine, Determinismus-Lauf, Mutationsprobe mit mindestens 7 Mutanten,
Echt-Lauf gegen beide Engines.

## 8. Stufen (Schätzung, keine Zusage)

| Stufe | Inhalt | Ende |
|---|---|---|
| S1 | Engine-B-Client mit Layout-Prompt, Parser, zwei Renders je Seite, Phasenlauf mit 2 Workern | Messung je Seite, Abgleich der Varianten |
| S2 | Union, Numerik-Normalisierung, Record mit Zusatzfeldern, CLI/API | lauffähiges System ohne Regionenprüfung |
| S3 | Regionen-Nachlesen (Standard, abschaltbar) | vollständiger Umfang |

Stufe 4 (Bench und Abnahmekriterium) entfällt nach D10.

## 9. Risiken

| Risiko | Wirkung | Umgang |
|---|---|---|
| Nutzen unbelegt (D10) | die Fusion kann schlechter sein als eine Einzelengine, und niemand merkt es | bewusst akzeptiert; im README als Grenze genannt, nicht als Vorteil verkauft |
| Zwei Engines in 8 GB VRAM | Modellwechsel je Phase, Kosten je Wechsel gemessen (paddle 35 s statt 25 s) | je Engine bündeln (D3); Gruppe in llama-swap nur nach VRAM-Messung |
| Laufzeit bei 300 dpi | mehr Bild-Token je Seite, Prompt-Verarbeitung steigt überproportional | Messung in S1; D9 sagt Genauigkeit vor Geschwindigkeit |
| Nachlesen je Box | 20–30 s je eigener Box; zwanzig Boxen bedeuten ~10 min für eine Seite | Boxen werden zwischengespeichert (eine Box, ein Aufruf); `--no-verify` schaltet die Stufe ab |
| Halluzination einer Engine | falscher Wert gilt als bestätigt, wenn die andere ihn zufällig teilt | Regionen-Nachlesen (B6) prüft jede Entität; Konflikte werden sichtbar gemacht, nicht geglättet |
| Layout-JSON zu groß | Abschneiden bei `max_tokens` | `max_tokens=8000`, Abschneiden erkennen (`finish_reason != "stop"`) → `OcrError` |
| Boxen in Bildpixeln | Ausschnitte mit falschen Maßen (erster Echtlauf: `FzErrorArgument`) | Umrechnung Punkte = Pixel × 72 / dpi der Engine, entartete Boxen verworfen (B6) |

## 10. Umsetzungsnotizen (nach der Freigabe)

Alle Punkte sind umgesetzt und getestet; sie stehen hier, weil sie die SPEC
auslegen, nicht ändern.

- **Modul:** `src/docpipeline/dual/` mit `formats.py` (dots-JSON, HTML-Raster,
  OTS), `values.py` (Zahlenschlüssel), `engines.py` (beide Engine-Klassen,
  Phasenlauf, `Variant`), `union.py`, `verify.py`, `pipeline.py`, `api.py`,
  `cli.py`.
- **Gemeinsamer HTTP-Client:** `ChatClient` in `ocr.py` (Retry, Fences,
  `finish_reason`). `OcrClient` ist jetzt eine dünne Hülle darauf; alle
  bestehenden Tests der Basis bleiben unverändert grün.
- **Record:** `DocumentRecord` und `Entity` wurden additiv erweitert (`variants`,
  `sources`, `agreement`, `verified`, `normalized`, `engine`, `ocr.engines`).
  Basis-Records bleiben gültig (D6b).
- **API:** dieselben Pfade `/v1/extract`, `/v1/health`, `/v1/schema` wie die
  Basis; das Feld `verify` (JSON) bzw. Formularfeld `verify` schaltet B6.
  `/v1/health` listet je Engine `name`, `model`, `dpi`, `reachable`.
- **Engine A und Tabellen:** Der Standard-Prompt bleibt Markdown; damit liefert
  Engine A keine Tabellen. OTS entsteht nur mit dem Prompt `Table Recognition:`
  (`DOCPIPELINE_ENGINE_A_PROMPT`). Der Parser versteht beide Formen.
- **E1 (Abbruch):** `finish_reason != "stop"` und endgültige HTTP-Fehler führen
  zu `OcrError` mit Seite; kein Teilrecord.
- **B6:** Die Box stammt aus der Variante mit Boxen (Layout-Engine), wird in
  PDF-Punkte umgerechnet, die Region mit 300 dpi gerendert und erneut an Engine A
  gegeben. Ohne Box, ohne Text oder bei Fehler: `verified = null` plus
  `verify_skipped:<label>:<seite>`.
- **Aufwand:** 173 Unit-Tests (13 Mutanten, alle getötet), 6 Integrationstests.
  Zahlen stehen in `EVIDENCE.md`.

