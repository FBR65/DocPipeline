"""Vereinigung mit Stimmenzahl: consensus, majority, single, Konflikt (S3, B4/B5).

Zahlen werden ohne Label verglichen (D6): ``98.765``, ``98.765,00`` und
``98.765.00`` sind ein Befund, auch wenn ein Leser ihn ``amount`` und ein anderer
``tax_number`` nennt. Text ohne Zahl bleibt am Label gebunden.
"""

from __future__ import annotations

from collections.abc import Sequence

from docpipeline.dual.values import is_number, normalize_value, number_key
from docpipeline.records import Entity, SourceRef

TEXT_LAYER = "text_layer"
CONSENSUS = "consensus"
MAJORITY = "majority"
SINGLE = "single"
_MAJORITY_VOTES = 2

GroupKey = tuple[object, ...]
SlotKey = tuple[object, ...]


def unite(
    per_variant: Sequence[tuple[str, Sequence[Entity]]],
) -> tuple[list[Entity], list[str]]:
    """Fasst gleiche Werte zusammen und zählt Stimmen.

    Stimme ist eine Quelle (Engine oder Textlayer). Zahlen werden labelunabhängig
    gruppiert, Text labelgebunden. ``consensus`` heißt: alle vorhandenen Quellen
    nennen den Wert; ``majority``: mindestens zwei, aber nicht alle. Gleichstand
    an der Spitze bleibt Streitfall und wird gewarnt.
    """
    if not per_variant:
        return [], []

    total_sources = len(per_variant)
    groups: dict[GroupKey, list[Entity]] = {}
    for engine, entities in per_variant:
        for entity in entities:
            groups.setdefault(_group_key(entity), []).append(
                entity.model_copy(update={"engine": entity.engine or engine})
            )

    votes = {key: _distinct_engines(items) for key, items in groups.items()}
    top = _top_votes(votes)
    warnings = sorted(
        f"conflict:{_label_of(items)}:{_page_label(key)}"
        for key, items in groups.items()
        if len(top[_slot(key)]) > 1
    )

    unified: list[Entity] = []
    for key, items in groups.items():
        best = max(items, key=lambda item: (item.score, -item.start))
        sources = _sources(items)
        if sources:
            best = best.model_copy(update={"engine": sources[0].engine})
        labels = sorted({item.label for item in items})
        unified.append(
            best.model_copy(
                update={
                    "normalized": normalize_value(best.text),
                    "agreement": _agreement(votes[key], total_sources, len(top[_slot(key)])),
                    "sources": sources,
                    "verified": None,
                }
            )
        )
        if len(labels) > 1:
            warnings.append(f"label_conflict:{_page_label(key)}:{_value_of(key)}")

    unified.sort(key=lambda item: (item.page or 0, item.start, item.label))
    return unified, sorted(set(warnings))


def _group_key(entity: Entity) -> GroupKey:
    """Zahlen ohne Label, Text mit Label."""
    if is_number(entity.text):
        return ("num", entity.page, number_key(entity.text))
    return ("txt", entity.label, entity.page, number_key(entity.text))


def _slot(key: GroupKey) -> SlotKey:
    """Bezugsraum für Gleichstand: je Seite, bei Text zusätzlich je Label."""
    if key[0] == "num":
        return (key[0], key[1])
    return (key[0], key[1], key[2])


def _page_label(key: GroupKey) -> str:
    """Seite aus dem Gruppenschlüssel; bei Text steht sie hinter ``label``."""
    page = key[1] if key[0] == "num" else key[2]
    return str(page) if page is not None else "-"


def _value_of(key: GroupKey) -> str:
    return str(key[-1])


def _label_of(items: list[Entity]) -> str:
    best = max(items, key=lambda item: (item.score, -item.start))
    return best.label


def _distinct_engines(items: list[Entity]) -> int:
    return len({item.engine for item in items if item.engine})


def _top_votes(votes: dict[GroupKey, int]) -> dict[SlotKey, set[str]]:
    """Je Bezugsraum die Werte mit den meisten Stimmen."""
    best: dict[SlotKey, set[str]] = {}
    for key, count in votes.items():
        slot = _slot(key)
        value = _value_of(key)
        current = best.setdefault(slot, set())
        if not current:
            current.add(value)
            continue
        highest = max(votes[candidate] for candidate in votes if _slot(candidate) == slot)
        if count > highest:
            best[slot] = {value}
        elif count == highest:
            current.add(value)
    return best


def _agreement(count: int, total_sources: int, top_count: int) -> str:
    """consensus, majority oder single; Gleichstand bleibt single."""
    if count < _MAJORITY_VOTES or top_count > 1:
        return SINGLE
    return CONSENSUS if count == total_sources else MAJORITY


def _sources(items: list[Entity]) -> list[SourceRef]:
    """Quellen je Wert; Zellherkunft und Nennung des Labels bleiben erhalten."""
    sources: list[SourceRef] = []
    for item in sorted(items, key=lambda entry: (str(entry.engine), entry.start)):
        if item.sources:
            sources.extend(
                source.model_copy(update={"label": source.label or item.label})
                for source in item.sources
            )
            continue
        sources.append(
            SourceRef(
                engine=str(item.engine),
                start=item.start,
                end=item.end,
                score=item.score,
                label=item.label,
            )
        )
    return sources
