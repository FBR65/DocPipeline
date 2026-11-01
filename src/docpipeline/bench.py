"""Recall/Precision gegen Ground Truth (I3)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from docpipeline.dedup import normalize
from docpipeline.records import DocumentRecord


@dataclass
class LabelScore:
    label: str
    tp: int = 0
    fn: int = 0
    fp: int = 0
    missed_docs: int = 0

    @property
    def recall(self) -> float:
        total = self.tp + self.fn
        return 1.0 if total == 0 else self.tp / total

    @property
    def precision(self) -> float:
        total = self.tp + self.fp
        return 1.0 if total == 0 else self.tp / total


@dataclass
class Report:
    labels: dict[str, LabelScore] = field(default_factory=dict)

    def worst_recall(self) -> float:
        if not self.labels:
            return 1.0
        return min(score.recall for score in self.labels.values())


def load_ground_truth(path: str | Path) -> dict[str, list[tuple[str, str]]]:
    """Liest je Dokument ``{stem}.json`` mit ``entities: [{label, text}]``."""
    folder = Path(path)
    truth: dict[str, list[tuple[str, str]]] = {}
    for file in sorted(folder.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = data.get("entities") if isinstance(data, dict) else None
        if not isinstance(items, list):
            continue
        truth[file.stem] = [
            (str(item["label"]), str(item["text"]))
            for item in items
            if isinstance(item, dict) and "label" in item and "text" in item
        ]
    return truth


def compare(
    records: dict[str, DocumentRecord], truth: dict[str, list[tuple[str, str]]]
) -> dict[str, LabelScore]:
    scores: dict[str, LabelScore] = {}

    def score_for(label: str) -> LabelScore:
        return scores.setdefault(label, LabelScore(label=label))

    for name, items in truth.items():
        record = records.get(name)
        predictions = list(record.entities) if record is not None else []
        if record is None:
            for label, _text in items:
                score_for(label).missed_docs += 1
        used: set[int] = set()
        for label, text in items:
            target = normalize(text)
            hit = next(
                (
                    index
                    for index, entity in enumerate(predictions)
                    if index not in used
                    and entity.label == label
                    and normalize(entity.text) == target
                ),
                None,
            )
            if hit is None:
                score_for(label).fn += 1
            else:
                used.add(hit)
                score_for(label).tp += 1
        for index, entity in enumerate(predictions):
            if index not in used:
                score_for(entity.label).fp += 1

    for name, record in records.items():
        if name in truth:
            continue
        for entity in record.entities:
            score_for(entity.label).fp += 1

    return dict(sorted(scores.items()))


def format_table(report: dict[str, LabelScore]) -> str:
    header = (
        f"{'label':<20} {'recall':>8} {'precision':>10} "
        f"{'tp':>4} {'fp':>4} {'fn':>4} {'docs':>5}"
    )
    lines = [header, "-" * len(header)]
    for label, score in report.items():
        lines.append(
            f"{label:<20} {score.recall * 100:>7.1f}% {score.precision * 100:>9.1f}% "
            f"{score.tp:>4} {score.fp:>4} {score.fn:>4} {score.missed_docs:>5}"
        )
    return "\n".join(lines)
