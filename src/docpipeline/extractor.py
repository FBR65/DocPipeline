"""GLiNER2 als Extraktor (B5).

Die Zuordnung von Rohtreffern zu Entitäten ist eine reine Funktion, damit sie
ohne Modell prüfbar ist. Das Modell wird erst beim ersten Aufruf geladen.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol, runtime_checkable

from docpipeline.records import Entity

DEFAULT_MODEL = "fastino/gliner2.5-multi-v1"


@runtime_checkable
class EntityExtractor(Protocol):
    name: str

    def extract(self, text: str, labels: dict[str, str]) -> list[Entity]: ...


def to_entities(raw: Any, text: str) -> list[Entity]:
    """Normalisiert die Modellantwort.

    Erwartet ``{"entities": {label: [{"text", "start", "end", "confidence"}]}}``.
    Reine Strings werden über ``str.find`` verortet; fehlt ein Span, entfällt
    der Treffer nicht, sondern wird an der ersten Fundstelle gesetzt.
    """
    entities: list[Entity] = []
    payload = raw.get("entities") if isinstance(raw, dict) else raw
    if not isinstance(payload, dict):
        return entities
    for label, items in payload.items():
        for item in _as_list(items):
            entity = _one_entity(label, item, text)
            if entity is not None:
                entities.append(entity)
    return entities


def _as_list(items: Any) -> Iterable[Any]:
    if isinstance(items, list):
        return items
    if items in (None, ""):
        return []
    return [items]


def _one_entity(label: str, item: Any, text: str) -> Entity | None:
    if isinstance(item, str):
        position = text.find(item)
        if position < 0:
            return None
        return Entity(label=label, text=item, start=position, end=position + len(item))
    if not isinstance(item, dict):
        return None
    value = str(item.get("text", ""))
    if not value:
        return None
    raw_start = item.get("start")
    raw_end = item.get("end")
    start: int
    end: int
    if isinstance(raw_start, int) and isinstance(raw_end, int):
        start, end = raw_start, raw_end
    else:
        found = text.find(value)
        if found < 0:
            return None
        start, end = found, found + len(value)
    return Entity(
        label=label,
        text=value,
        start=start,
        end=end,
        score=float(item.get("confidence", item.get("score", 0.0)) or 0.0),
    )


class Gliner2Extractor:
    """Dünner Adapter auf ``gliner2.AutoExtractor``."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        device: str = "cpu",
        threshold: float = 0.35,
        loader: Callable[[], Any] | None = None,
    ) -> None:
        self.name = model
        self._model_name = model
        self._device = device
        self._threshold = threshold
        self._loader = loader
        self._model: Any = None

    @property
    def model(self) -> Any:
        if self._model is None:
            self._model = self._loader() if self._loader is not None else self._load()
        return self._model

    def _load(self) -> Any:
        from gliner2 import AutoExtractor  # torch wird erst hier geladen

        return AutoExtractor.from_pretrained(self._model_name, map_location=self._device)

    def extract(self, text: str, labels: dict[str, str]) -> list[Entity]:
        if not text.strip() or not labels:
            return []
        raw = self.model.extract_entities(
            text,
            dict(labels),
            threshold=self._threshold,
            format_results=True,
            include_spans=True,
            include_confidence=True,
        )
        return to_entities(raw, text)
