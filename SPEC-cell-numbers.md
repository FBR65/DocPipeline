# SPEC — Zahlen besser lesen: Zellebene, dritter Leser, Mehrheit

Status: **Entwurf, nicht freigegeben.** Kein Code vor Freigabe.

Basis: `DocPipeline` mit Doppellauf (`docpipeline/dual`, Commit `57e66e7`).
Auftrag: Stufen 1–3 aus der Verbesserungsliste übernehmen.
Stufe 4 (Rechenprüfung) und Stufe 5 (Musterprüfung je Label) sind **nicht**
Teil dieses Auftrags; das ist die Entscheidung des Auftraggebers, keine Kürzung
durch den Bearbeiter.

> Alle Beträge, Namen, Anschriften und Datumsangaben in diesem Dokument sind
> anonymisiert: Zeichenform und Stellen bleiben erhalten, die Werte sind ersetzt.

## 1. Gemessene Grundlage

Eine Seite (Steuerbescheid, kein Textlayer), gleiche Datei, gleiche Maschine:

| Engine | ganze Seite 300 dpi | Tabellenausschnitt 300 dpi | Ausschnitt 600 dpi | Dauer (Seite / Ausschnitt) |
|---|---|---|---|---|
| paddleocr-vl | `-9.874,00` | **`-9.876,00`** | `-9.876,00` | 43 s / 35 s |
| dots.mocr | `-9.876,00` | – | – | 30 s / – |
| RapidOCR (PP-OCRv6, ONNX) | `-9.876,00` | `-9.876,00` | `-9.876,00` | **3,4 s / 3,2 s** |

Befunde:

- Der Seitenlauf ist bei Ziffern unzuverlässiger als der fokussierte Ausschnitt:
  paddle liest auf der Seite `-9.874,00`, im Ausschnitt `-9.876,00`.
- 600 dpi bringt gegenüber 300 dpi nichts. Auflösung ist hier kein Hebel; die
  Stufe wird nicht gebaut.
- Drei Leser stimmen im Ausschnitt überein; ein dritter Leser allein erzeugt
  also keine neue Wahrheit, er verschiebt die Mehrheit.
- Der größte Störer derzeit ist nicht die OCR, sondern die Spansuche über
  Fließtext: Treffer wie `87,00 101`, `EUR`, `01.2-24` entstehen an
  Zellgrenzen.
- RapidOCR läuft auf CPU in 3,4 s je Seite und liefert Text, Boxen und
  Konfidenz je Zeile. Damit wird eine Prüfung je Box bezahlbar.

## 2. Entscheidungen des Auftraggebers

| ID | Entscheidung | Folge |
|---|---|---|
| G1 | Stufen **1–3** werden gebaut | Zellebene, dritter Leser, Mehrheit je Wert |
| G2 | Stufe 4 (Rechenprüfung) nicht | keine Orakelprüfung; Widersprüche bleiben sichtbar |
| G3 | Stufe 5 (Musterprüfung je Label) nicht | Nicht-Zahlen bleiben im Record, wenn das Modell sie liefert |

## 3. Offene Entscheidungen (brauchen Antwort)

| ID | Frage | Optionen | Empfehlung |
|---|---|---|---|
| D1 | Zellebene ersetzt oder ergänzt die Text-NER? | (a) ergänzt, Union führt zusammen; (b) nur Zellebene | **(a)** — Tabellenlose Felder (Name, Datum im Fließtext) gingen sonst verloren |
| D2 | Was gilt als Mehrheit? | (a) 2 von 3 Lesern; (b) 2 von 2, dritter nur bei Gleichstand | **(a)** — drei Stimmen, Mehrheit ab zwei |
| D3 | RapidOCR fest oder als Extra? | (a) Extra `docpipeline[rapid]`, fehlt es, läuft der Doppellauf weiter; (b) feste Abhängigkeit | **(a)** — Basisinstallation bleibt schlank, 3,4 s sind ein Zusatznutzen, kein Muss |
| D4 | Läuft RapidOCR über die ganze Seite? | (a) ja, als dritte Stimme je Seite; (b) nur je Ausschnitt beim Nachlesen | **(a)** — 3,4 s je Seite sind zu billig, um sie zu sparen |
| D5 | Gleichstand (1 zu 1) | (a) beide Werte behalten, `conflict`; (b) den mit höherer Konfidenz | **(a)** — Auswahl nach Konfidenz verdeckt den Streit |

## 4. Zielbild

```
Seite ─┬─► paddle (300 dpi) ─► Text + OTS-Zellraster
       ├─► dots.mocr (200 dpi) ─► Text + HTML-Zellraster + Boxen
       └─► RapidOCR (300 dpi) ─► Zeilen mit Boxen und Konfidenz
   ─► Extraktion je Quelle: Fließtext (wie bisher) und je Tabellenzelle
   ─► Vereinigung mit Stimmenzahl: consensus | majority | single | conflict
   ─► Prüfleser je Box (RapidOCR, Rückfall paddle)
   ─► Record (additive Felder)
```

## 5. Verhaltens-Spezifikation

### B1 Zellebene
Aus jedem Zellraster einer Variante entstehen Zellen
`Zelle(seite, tabelle, zeile, spalte, text)`. Jede Zelle mit Ziffer wird an den
Extraktor gegeben, gebündelt je Seite (`batch_extract_entities`, damit die
Modellaufrufe nicht je Zelle einzeln laufen). Zellen ohne Ziffer werden nur
dann geprüft, wenn das Schema ein Label ohne Ziffern enthält.
Jeder so gefundene Treffer trägt seine Herkunft:
`Quelle(engine, seite, start, end, score, zelle=(tabelle, zeile, spalte))`.
Offsets gelten im Zelltext.

### B2 Zellraster beider Text-Engines
`Variant.tables` liefert je Seite eine Liste von Rastern. Engine B (dots) füllt
sie aus HTML, Engine A (paddle) aus OTS, sofern der Prompt
`Table Recognition:` ist. Ohne Raster liefert eine Variante keine Zellen; das
ist kein Fehler (siehe E1).

### B3 Dritter Leser (RapidOCR)
`RapidEngine` erfüllt das bestehende `OcrEngine`-Protokoll: `name`, `dpi`,
`describe_page(image, seite) -> OcrPage`, `ping()`, `close()`. Es liefert
`text` (Zeilen in Lesereihenfolge), `boxes` (je Zeile `bbox`, Kategorie `Text`,
Text) und `tables = ()`. Die Konfidenz je Zeile wird als `score` der Box
geführt. Läuft auf CPU, kein Netz außer dem einmaligen Modell-Download.

### B4 Mehrheit je Wert
Verglichen wird **ausschließlich der Zahlenwert**, nicht die Zeichenfolge:
`98.765`, `98.765,00` und `98.765.00` sind derselbe Wert. Schlüssel ist
`(seite, Zahlenwert)` mit `number_key()`; angehängte Nullen entfallen, die
Anzeigeform im Feld `normalized` bleibt wie gelesen. **Das Label ist nicht Teil
des Schlüssels (D6):** nennt ein Leser den Wert `amount` und ein anderer
`tax_number`, ist es derselbe Befund. Das Label des Treffers stammt von der
Quelle mit dem höheren Score; jedes Label steht zusätzlich in
`sources[].label`. Weichen die Labels ab, erscheint
`label_conflict:<seite>:<wert>`. Text ohne Zahl bleibt am Label gebunden. Neu ist die Stimmenzahl:
`votes = Anzahl der Quellen mit verschiedenem Engine-Namen`.
`agreement`:
- `consensus` — alle vorhandenen Engines (≥2) nennen den Wert,
- `majority` — mindestens zwei von drei, aber nicht alle,
- `single` — genau eine Quelle,
- `conflict` — kein Wert erreicht zwei Stimmen, während ein anderer Wert
  derselben Zelle zwei erreicht.

Bei Gleichstand (1 zu 1) bleiben beide Einträge mit `agreement = "single"` und
die Warnung `conflict:<label>:<seite>` (D5a).

### B5 Record (weiterhin additiv)
```json
{"entities": [{"label": "amount", "text": "-9.876,00", "normalized": "-9876.00",
               "page": 1, "start": 12, "end": 23, "score": 0.92,
               "engine": "dots-mocr", "agreement": "majority",
               "verified": true,
               "sources": [{"engine": "paddleocr-vl", "start": 174, "end": 185,
                            "score": 0.86, "zelle": [0, 2, 0]},
                           {"engine": "dots-mocr", "start": 181, "end": 192,
                            "score": 0.93, "zelle": [0, 2, 0]},
                           {"engine": "rapidocr", "start": 190, "end": 201,
                            "score": 0.0, "zelle": null}]}],
 "cells": [{"page": 1, "table": 0, "rows": 4, "cols": 3,
            "engines": ["dots-mocr", "paddleocr-vl"]}]}
```
`zelle` ist `null`, wenn der Treffer aus dem Fließtext stammt.

### B6 Prüfleser
Das Regionen-Nachlesen nutzt **RapidOCR** als Standard-Engine, paddle als
Rückfall, wenn RapidOCR fehlt (D3a). Aufrufe werden je Box zwischengespeichert
(Bestand). Ein Ausschnitt gilt als bestätigt, wenn der Zahlenschlüssel unter den
gelesenen Zahlen vorkommt.

### B7 Abhängigkeit
`rapidocr` und `onnxruntime` werden als Extra `rapid` geführt:
`uv add "docpipeline[rapid]"`. Ohne das Extra startet der Doppellauf mit zwei
Engines und meldet `engine_c_unavailable` (Warnung, kein Abbruch).

### E1 Kein Zellraster
Eine Variante ohne Tabellen liefert keine Zellen. Die Text-NER bleibt aktiv
(D1a). Keine Warnung, weil das bei Fließtextdokumenten der Normalfall ist.

### E2 Raster passen nicht zusammen
Zellraster verschiedener Engines haben unterschiedliche Zeilen- oder
Spaltenzahl: Zellen werden nicht verschmolzen, nur ihre Werte über B4
verglichen. Warnung `grid_mismatch:<engine>:<seite>`.

### E3 RapidOCR nicht verfügbar
Import oder Modell fehlt: `engine_c_unavailable` als Warnung, Lauf mit zwei
Engines, Nachlesen mit paddle. Kein Abbruch.

### E4 Zelle ohne Ziffer bei numerischem Label
Zelle enthält keine Ziffer, das Label ist numerisch geprägt: Zelle wird
übersprungen, kein Treffer, keine Warnung (Normalfall in Tabellenköpfen).

### I1 Kein stiller Verlust
Jeder Treffer einer Quelle steht im Record, entweder als eigener Eintrag oder
in einem Konfliktpaar. Test: Summe der Quellen = Summe der Einträge plus
Konfliktpaare.

### I2 Determinismus
Gleiche Eingabe, gleiche Modelle, gleiche Reihenfolge. RapidOCR ist
deterministisch; die Reihenfolge der Quellen ist fest (A, B, C, Textlayer).

### I3 Kein Erfolgsversprechen
Es gibt weiterhin kein Abnahmekriterium gegenüber einer Einzelengine (D10 der
vorigen SPEC). Neue Belege: Anzahl Treffer je `agreement`-Klasse und die
Zahl der Konflikte vor und nach der Änderung, gemessen auf demselben Dokument.

## 6. Setup-Plan

| Hinzukommend | Zweck | Lizenz (geprüft) |
|---|---|---|
| `rapidocr` 3.10.0 | dritter Leser, CPU, 3,4 s je Seite | Apache-2.0 (RapidAI/RapidOCR) |
| `onnxruntime` | Laufzeit für die ONNX-Modelle | MIT |

Modelle (PP-OCRv6 det/cls/rec, ~15 MB je Modell) kommen beim ersten Aufruf aus
dem Paket, kein HF-Zugriff. Python 3.12 wird unterstützt (Paketangabe
3.10–3.13). Kein GPU-Zwang, kein Konflikt mit llama-swap.

Gauntlet-Stufe: **Tier 3** (Zahlen als Geschäftsdaten, zwei externe Systeme,
öffentliche API). Property-Tests für die Mehrheitsregel, Konfliktfälle,
fehlende Tabellen, fehlendes Extra. Mutationsprobe mit mindestens 4 neuen
Mutanten.

## 7. Stufen (Schätzung, keine Zusage)

| Stufe | Inhalt | Ende |
|---|---|---|
| S1 | Zellraster → Zellen, Extraktion je Zelle, Herkunft im Record | lauffähig mit zwei Engines |
| S2 | `RapidEngine` als dritter Leser und als Prüfleser | drei Stimmen, schnelles Nachlesen |
| S3 | Mehrheit, `consensus`/`majority`, Konfliktfälle | Record mit Stimmenzahl |

Nach jeder Stufe: Testlauf, Bericht, keine Fortsetzung ohne Freigabe.

## 8. Risiken

| Risiko | Wirkung | Umgang |
|---|---|---|
| Zwei Leser irren gleich | Mehrheit bestätigt einen falschen Wert | bleibt sichtbar als `majority`, nicht als Wahrheit; Stufe 4 wäre die Gegenprobe |
| Zellen statt Fließtext | Felder außerhalb von Tabellen fehlen, wenn Text-NER entfällt | D1a: Text-NER bleibt |
| Doppelte Treffer | derselbe Wert erscheint als Fließtext- und Zelltreffer | Union führt über den Zahlenschlüssel zusammen, Herkunft bleibt |
| Modellaufrufe je Zelle | Laufzeit steigt mit der Zellenzahl | Bündelung je Seite, nur Zellen mit Ziffern |
| RapidOCR-Genauigkeit | bei schlechten Scans schwächer als die großen Modelle | dritte Stimme, kein Ersatz; Konfidenz je Zeile wird geführt |

## 9. Umsetzungsnotizen (nach der Freigabe)

- **Zellen:** `dual/cells.py` liest die Raster aus `Variant.tables` (HTML und OTS),
  filtert Zellen ohne Ziffer (E4) und ruft den Extraktor gebündelt je Seite
  (`extract_many`, Rückfall auf Einzelaufrufe). Treffer tragen
  `sources[0].zelle = (tabelle, zeile, spalte)`.
- **Dritter Leser:** `dual/rapid.py`, `RapidEngine` erfüllt das `OcrEngine`-
  Protokoll, Konfidenz je Zeile als `Element.score`. Fehlt `rapidocr`, meldet
  `available()` False; der Doppellauf läuft mit zwei Engines und warnt
  `engine_c_unavailable`.
- **Mehrheit:** `unite()` zählt Stimmen je Wert. Klassen `consensus`,
  `majority`, `single`; Gleichstand an der Spitze bleibt `single` für beide
  Werte plus `conflict:<label>:<seite>`. Die alten Klassen `both` und
  `text_layer` entfallen; der Textlayer zählt als Stimme.
- **Prüfleser:** `DualPipeline._default_verify_engine` nimmt `rapidocr`, wenn
  vorhanden, sonst die erste Engine.
- **Record:** `DocumentRecord.cells` listet je Seite und Tabelle Maße und die
  Engines, die ein Raster liefern.
- **Abhängigkeit:** Extra `rapid` (`rapidocr`, `onnxruntime`); im dev-Block
  eingetragen, damit die Integrationstests den echten Leser prüfen.
- **Befund aus dem Echtlauf (drei Leser, Steuerbescheid):** Nach Zahlenvergleich
  ohne Label bleiben alle Treffer `single`, und der Grund ist jetzt gemessen:
  die Leser liefern **verschiedene Zahlen**, nicht nur verschiedene Zeichenfolgen.
  Überlappung der Zahlenwerte auf Seite 1: paddle ∩ dots = 0, paddle ∩ rapid = 0,
  dots ∩ rapid = 0. Beispiele: paddle `54.322,00` gegen dots `54.321`; paddle `211`
  gegen dots `212`; paddle `201,45` gegen dots `101`. Eine Mehrheit kann daraus
  nicht entstehen; genau dafür ist der Prüfleser (D9) da.
- **Wirksam geworden:** labelunabhängige Gruppierung (`label_conflict` trat auf)
  und Kopfzeilen-Kontext bei Zellen.
- **Offen geblieben:** Stufe 4 (Rechenprüfung) und Stufe 5 (Musterprüfung), wie
  beauftragt nicht gebaut.
