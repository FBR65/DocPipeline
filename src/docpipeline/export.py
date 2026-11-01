"""Export nach Label Studio für die Annotation (S4)."""

from __future__ import annotations

from typing import Any

from docpipeline.records import DocumentRecord


def to_label_studio(record: DocumentRecord) -> dict[str, Any]:
    """Erzeugt eine Label-Studio-Aufgabe (Pre-Annotation, Text im Datenfeld)."""
    results: list[dict[str, Any]] = [
        {
            "value": {
                "start": entity.start,
                "end": entity.end,
                "text": entity.text,
                "labels": [entity.label],
            },
            "score": entity.score,
        }
        for entity in record.entities
    ]
    return {
        "data": {"text": record.text or ""},
        "meta": {"source": record.source, "sha256": record.sha256},
        "annotations": [{"result": results, "was_cancelled": False}],
    }
