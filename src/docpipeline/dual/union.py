"""Vereinigung der Treffer über Varianten (B5, E2, I3)."""

from __future__ import annotations

from collections.abc import Sequence

from docpipeline.dual.values import normalize_value
from docpipeline.records import Entity, SourceRef

TEXT_LAYER = "text_layer"


def unite(
    per_variant: Sequence[tuple[str, Sequence[Entity]]],
) -> tuple[list[Entity], list[str]]:
    """Fasst gleiche Werte zusammen und markiert Übereinstimmung oder Konflikt.

    Schlüssel ist ``(label, page, normalize_value(text))``. Kein Zeichenabstand
    über Varianten hinweg: Offsets aus verschiedenen Texten sind nicht
    vergleichbar.
    """
    if not per_variant:
        return [], []

    groups: dict[tuple[str, int | None, str], list[Entity]] = {}
    for engine, entities in per_variant:
        for entity in entities:
            key = (entity.label, entity.page, normalize_value(entity.text))
            groups.setdefault(key, []).append(
                entity.model_copy(update={"engine": entity.engine or engine})
            )

    by_label_page: dict[tuple[str, int | None], set[str]] = {}
    for label, page, normalized in groups:
        by_label_page.setdefault((label, page), set()).add(normalized)
    warnings = [
        f"conflict:{label}:{page if page is not None else '-'}"
        for (label, page), values in by_label_page.items()
        if len(values) > 1
    ]

    unified: list[Entity] = []
    for (label, page, normalized), items in groups.items():
        best = max(items, key=lambda item: (item.score, -item.start))
        engines = {item.engine for item in items if item.engine}
        sources = [
            SourceRef(
                engine=str(item.engine),
                start=item.start,
                end=item.end,
                score=item.score,
            )
            for item in sorted(items, key=lambda item: (str(item.engine), item.start))
        ]
        unified.append(
            best.model_copy(
                update={
                    "label": label,
                    "page": page,
                    "normalized": normalized,
                    "agreement": _agreement(engines),
                    "sources": sources,
                    "verified": None,
                }
            )
        )

    unified.sort(key=lambda item: (item.page or 0, item.start, item.label))
    return unified, sorted(warnings)


def _agreement(engines: set[str]) -> str:
    names = {name for name in engines if name}
    if TEXT_LAYER in names and len(names) > 1:
        return TEXT_LAYER
    return "both" if len(names) > 1 else "single"
