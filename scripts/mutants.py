#!/usr/bin/env python3
"""Mutationsprobe: jeder Mutant muss von genau dem genannten Test erkannt werden.

Aufruf: uv run python scripts/mutants.py
Exitcode 0 = alle Mutanten getötet. Nichts bleibt verändert.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "docpipeline"

MUTANTS = [
    (
        "Satzgrenze wird nicht mehr bevorzugt",
        "chunker.py",
        "floor = first + max(1, window_words // 2)",
        "floor = limit - 1",
        "tests/test_chunker.py::test_cut_prefers_sentence_end",
    ),
    (
        "Überlappung fällt auf 0 Wörter",
        "chunker.py",
        "overlap = max(overlap_words, 1)",
        "overlap = overlap_words",
        "tests/test_chunker.py::test_zero_overlap_still_touches",
    ),
    (
        "Dedup behält den schlechtesten Score",
        "dedup.py",
        "return max(items, key=lambda e: (e.score, -e.start))",
        "return min(items, key=lambda e: (e.score, -e.start))",
        "tests/test_dedup.py::test_duplicate_in_overlap_zone_is_merged_keeping_best_score",
    ),
    (
        "OCR versucht es nur einmal",
        "ocr.py",
        "retries = max(self._settings.ocr_retries, 1)",
        "retries = 1",
        "tests/test_ocr.py::test_retry_on_500_then_success",
    ),
    (
        "Seitenzuordnung liefert immer Seite 1",
        "pipeline.py",
        "index = bisect_right(offsets, offset) - 1",
        "index = 0",
        "tests/test_pipeline.py::test_entities_are_mapped_to_document_offsets_and_pages",
    ),
    (
        "Größenschranke beim Upload entfällt",
        "api.py",
        "if len(data) > settings.max_upload_bytes:",
        "if False:",
        "tests/test_api.py::test_too_large_upload_gives_413",
    ),
    (
        "Recall rechnet gegen Vorhersagen",
        "bench.py",
        "total = self.tp + self.fn",
        "total = self.tp + self.fp",
        "tests/test_bench.py::test_compare_counts_matches_case_insensitive",
    ),
]


def run(test: str) -> int:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", test],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).returncode


def main() -> int:
    survivors: list[str] = []
    for index, (name, filename, old, new, test) in enumerate(MUTANTS, start=1):
        path = SRC / filename
        original = path.read_text(encoding="utf-8")
        if original.count(old) != 1:
            print(f"[{index}] FEHLER: Suchtext nicht eindeutig in {filename}: {name}")
            return 2
        path.write_text(original.replace(old, new), encoding="utf-8")
        try:
            code = run(test)
        finally:
            path.write_text(original, encoding="utf-8")
        killed = code != 0
        print(f"[{index}] {'getötet ' if killed else 'ÜBERLEBT'} {name} -> {test}")
        if not killed:
            survivors.append(name)
    if survivors:
        print("Überlebende Mutanten:", ", ".join(survivors))
        return 1
    print(f"Alle {len(MUTANTS)} Mutanten getötet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
