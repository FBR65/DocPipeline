"""Regionen-Nachlesen: jede Entität gegen einen Bildausschnitt prüfen (B6, E3)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence

from docpipeline.dedup import normalize
from docpipeline.dual.engines import OcrEngine
from docpipeline.dual.formats import Element, OcrPage, html_to_text
from docpipeline.dual.values import normalize_value
from docpipeline.errors import OcrError
from docpipeline.records import Entity

Crop = Callable[[int, tuple[float, float, float, float]], bytes]

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)*")


def verify_entities(
    entities: Sequence[Entity],
    boxes_by_page: Mapping[int, Sequence[Element]],
    crop: Crop,
    engine: OcrEngine,
) -> tuple[list[Entity], list[str]]:
    """Setzt ``verified`` je Entität: True, False oder None (nicht prüfbar)."""
    verified: list[Entity] = []
    warnings: list[str] = []
    answers: dict[tuple[int, tuple[float, float, float, float]], OcrPage | None] = {}
    for entity in entities:
        if entity.page is None:
            verified.append(entity.model_copy(update={"verified": None}))
            continue
        box = _find_box(boxes_by_page.get(entity.page, ()), entity)
        if box is None:
            warnings.append(f"verify_skipped:{entity.label}:{entity.page}:{entity.text}")
            verified.append(entity.model_copy(update={"verified": None}))
            continue
        key = (entity.page, box.bbox)
        if key not in answers:
            try:
                answers[key] = engine.describe_page(
                    crop(entity.page, box.bbox), page_no=entity.page
                )
            except OcrError:
                answers[key] = None
        answer = answers[key]
        if answer is None:
            warnings.append(f"verify_skipped:{entity.label}:{entity.page}:{entity.text}")
            verified.append(entity.model_copy(update={"verified": None}))
            continue
        target = entity.normalized or normalize_value(entity.text)
        observed = {normalize_value(number) for number in _NUMBER.findall(answer.text)}
        if target and target in observed:
            verified.append(entity.model_copy(update={"verified": True}))
            continue
        if not observed and target and target in normalize(answer.text):
            verified.append(entity.model_copy(update={"verified": True}))
            continue
        if not observed and not normalize(answer.text):
            warnings.append(f"verify_skipped:{entity.label}:{entity.page}:{entity.text}")
            verified.append(entity.model_copy(update={"verified": None}))
            continue
        verified.append(entity.model_copy(update={"verified": False}))
    return verified, warnings


def _find_box(boxes: Sequence[Element], entity: Entity) -> Element | None:
    """Box, deren Text oder Zellen den Wert der Entität enthalten.

    Die Layout-Engine legt ganze Tabellen in ein Element mit HTML. Deshalb wird
    jede Zahl im Element geprüft, nicht nur die erste.
    """
    target = entity.normalized or normalize_value(entity.text)
    for box in boxes:
        if box.text and _contains_value(box.text, target):
            return box
    needle = normalize_value(entity.text)
    for box in boxes:
        if box.text and needle and needle in normalize_value(html_to_text(box.text)):
            return box
    return None


def _contains_value(text: str, target: str) -> bool:
    if not target:
        return False
    return any(normalize_value(number) == target for number in _NUMBER.findall(text))
