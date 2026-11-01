"""Deduplizierung von Treffern aus überlappenden Chunks (B6)."""

from __future__ import annotations

import re

from docpipeline.records import Entity

_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Vergleichsform: Whitespace kollabiert, Groß-/Kleinschreibung egal."""
    return _SPACE.sub(" ", text).strip().casefold()


def _pick_best(items: list[Entity]) -> Entity:
    return max(items, key=lambda e: (e.score, -e.start))


def dedupe(entities: list[Entity], distance_max: int = 80) -> list[Entity]:
    """Fasst gleiche Treffer zusammen, die sich überlappen oder nah liegen.

    Gleiches Label und gleicher normalisierter Text sind die Vorbedingung.
    Aus einer Gruppe bleibt der Treffer mit dem höchsten Score.
    """
    groups: dict[tuple[str, str], list[Entity]] = {}
    for entity in entities:
        groups.setdefault((entity.label, normalize(entity.text)), []).append(entity)

    kept: list[Entity] = []
    for items in groups.values():
        ordered = sorted(items, key=lambda e: (e.start, -e.score))
        cluster: list[Entity] = [ordered[0]]
        for entity in ordered[1:]:
            if entity.start <= cluster[-1].end + distance_max:
                cluster.append(entity)
                continue
            kept.append(_pick_best(cluster))
            cluster = [entity]
        kept.append(_pick_best(cluster))

    return sorted(kept, key=lambda e: (e.start, e.label))
