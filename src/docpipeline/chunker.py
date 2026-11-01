"""Chunking mit Sliding Window über Wortgrenzen (B4)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORD = re.compile(r"\S+")
_SENTENCE_END = (".", "!", "?", "…", ";", ":")


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int
    end: int
    text: str


def _ends_sentence(token: str) -> bool:
    stripped = token.rstrip("\"'»“”)]")
    return stripped.endswith(_SENTENCE_END)


def chunk(text: str, window_words: int = 220, overlap_words: int = 40) -> list[Chunk]:
    """Teilt `text` in überlappende Fenster.

    Grenzen liegen nach Möglichkeit auf einem Satzende in der zweiten Hälfte
    des Fensters. Die Überlappung beträgt mindestens ein Wort, damit
    aufeinanderfolgende Chunks sich immer berühren.
    """
    if window_words <= 0:
        raise ValueError("window_words muss größer als 0 sein")
    if overlap_words < 0:
        raise ValueError("overlap_words darf nicht negativ sein")
    if overlap_words >= window_words:
        raise ValueError("overlap_words muss kleiner als window_words sein")

    tokens = list(_WORD.finditer(text))
    if not tokens:
        return []

    overlap = max(overlap_words, 1)
    chunks: list[Chunk] = []
    first = 0
    while first < len(tokens):
        limit = min(first + window_words, len(tokens))
        cut = limit
        if limit < len(tokens):
            floor = first + max(1, window_words // 2)
            for idx in range(limit - 1, floor - 1, -1):
                if _ends_sentence(tokens[idx].group()):
                    cut = idx + 1
                    break
        start = tokens[first].start()
        end = tokens[cut - 1].end()
        chunks.append(Chunk(index=len(chunks), start=start, end=end, text=text[start:end]))
        if cut >= len(tokens):
            break
        first = max(cut - overlap, first + 1)
    return chunks
