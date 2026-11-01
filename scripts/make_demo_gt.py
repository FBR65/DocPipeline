"""Erzeugt die Ground-Truth-Datei für das Artikel-PDF (Demo, keine Benchmark-Aussage)."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
pdf = next(root.glob("Extract Anything From Anywhere*.pdf"))
target = root / "data" / "gt" / f"{pdf.stem}.json"
target.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "note": "Demo-Ground-Truth, von Hand aus dem PDF gelesen.",
    "entities": [
        {
            "label": "title",
            "text": "Extract Anything From Anywhere: Building Document AI Pipeline with"
            " GLINER Beyond Zero Shot",
        },
        {"label": "author", "text": "Dhanya Shanbhag"},
        {"label": "publication", "text": "Towards AI"},
    ],
}
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(target)
