"""B6 — Deduplizierung über Overlap-Grenzen."""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from docpipeline.dedup import dedupe, normalize
from docpipeline.records import Entity


def e(label: str, text: str, start: int, score: float = 0.5) -> Entity:
    return Entity(label=label, text=text, start=start, end=start + len(text), score=score)


def test_normalize_collapses_case_and_space() -> None:
    assert normalize("  ACME   GmbH ") == normalize("acme gmbh")


def test_duplicate_in_overlap_zone_is_merged_keeping_best_score() -> None:
    left = e("buyer", "ACME", 100, score=0.6)
    right = e("buyer", "acme", 110, score=0.9)
    out = dedupe([left, right], distance_max=20)
    assert len(out) == 1
    assert out[0].score == 0.9
    assert out[0].start == 110


def test_far_apart_occurrences_stay_separate() -> None:
    out = dedupe([e("buyer", "ACME", 0), e("buyer", "ACME", 500)], distance_max=20)
    assert len(out) == 2


def test_different_labels_are_never_merged() -> None:
    out = dedupe([e("buyer", "ACME", 10), e("customer", "ACME", 12)], distance_max=50)
    assert len(out) == 2


def test_result_is_sorted_by_offset_then_label() -> None:
    out = dedupe([e("b", "z", 50), e("a", "y", 10), e("c", "x", 10)], distance_max=1)
    assert [(o.start, o.label) for o in out] == [(10, "a"), (10, "c"), (50, "b")]


def test_partial_text_overlap_is_not_merged() -> None:
    out = dedupe([e("buyer", "ACME GmbH", 0), e("buyer", "ACME AG", 4)], distance_max=50)
    assert len(out) == 2


@hyp_settings(max_examples=60, deadline=None)
@given(
    label=st.sampled_from(["a", "b"]),
    text=st.from_regex(r"[A-Za-z]{2,6}", fullmatch=True),
    start=st.integers(min_value=0, max_value=200),
    gap=st.integers(min_value=0, max_value=40),
    distance=st.integers(min_value=0, max_value=40),
)
def test_property_idempotent(
    label: str, text: str, start: int, gap: int, distance: int
) -> None:
    ents = [e(label, text, start, 0.4), e(label, text, start + gap, 0.7)]
    once = dedupe(ents, distance_max=distance)
    assert dedupe(once, distance_max=distance) == once
