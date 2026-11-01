"""B4 — Chunking mit Sliding Window."""

from __future__ import annotations

import itertools
import re

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from docpipeline.chunker import Chunk, chunk


def _tokens(text: str) -> list[re.Match[str]]:
    return list(re.finditer(r"\S+", text))


def test_no_overlap_required_for_short_text() -> None:
    chunks = chunk("nur ein satz", window_words=20, overlap_words=5)
    assert len(chunks) == 1
    assert chunks[0].start == 0
    assert chunks[0].end == len("nur ein satz")


def test_window_and_overlap_numbers() -> None:
    text = " ".join(f"w{i}" for i in range(100))
    chunks = chunk(text, window_words=30, overlap_words=10)
    assert all(c.end - c.start > 0 for c in chunks)
    # Fenster sind 30 Wörter breit, Schrittweite 20.
    assert len(chunks) == 5
    for prev, nxt in itertools.pairwise(chunks):
        assert nxt.start < prev.end, "Überlappung muss garantiert sein"


def test_cut_prefers_sentence_end() -> None:
    words = [f"w{i}" for i in range(100)]
    words[69] = "ende."
    text = " ".join(words)
    chunks = chunk(text, window_words=80, overlap_words=10)
    first = chunks[0]
    assert first.text.rstrip().endswith("ende.")
    assert text[first.end :].lstrip().startswith("w70")


def test_every_token_is_covered() -> None:
    text = " ".join(f"t{i}" for i in range(250))
    chunks = chunk(text, window_words=40, overlap_words=8)
    covered: set[int] = set()
    for c in chunks:
        for m in _tokens(c.text):
            covered.add(int(re.search(r"\d+", m.group()).group()))  # type: ignore[union-attr]
    assert covered == set(range(250))


def test_zero_overlap_still_touches() -> None:
    """overlap_words=0 wird auf ein Wort angehoben (Vertrag: Überlappung garantiert)."""
    text = " ".join(f"z{i}" for i in range(60))
    chunks = chunk(text, window_words=20, overlap_words=0)
    assert len(chunks) > 1
    for prev, nxt in itertools.pairwise(chunks):
        assert nxt.start < prev.end


def test_overlap_must_be_smaller_than_window() -> None:
    with pytest.raises(ValueError):
        chunk("a b c", window_words=10, overlap_words=10)
    with pytest.raises(ValueError):
        chunk("a b c", window_words=0, overlap_words=0)


def test_chunk_offsets_point_into_source_text() -> None:
    text = " ".join(f"x{i}" for i in range(60))
    for c in chunk(text, window_words=15, overlap_words=4):
        assert text[c.start : c.end] == c.text


@hyp_settings(max_examples=50, deadline=None)
@given(
    words=st.lists(st.from_regex(r"[a-zäöü]{1,8}", fullmatch=True), min_size=1, max_size=120),
    window=st.integers(min_value=2, max_value=40),
    overlap=st.integers(min_value=0, max_value=39),
)
def test_property_cover_and_overlap(words: list[str], window: int, overlap: int) -> None:
    if overlap >= window:
        return
    text = " ".join(words)
    chunks = chunk(text, window_words=window, overlap_words=overlap)
    assert isinstance(chunks[0], Chunk)
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)
    for prev, nxt in itertools.pairwise(chunks):
        assert nxt.start < prev.end
        assert nxt.start > prev.start
