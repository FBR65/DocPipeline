#!/usr/bin/env bash
# Ein Einstiegspunkt für alle Gauntlet-Schichten. Aufruf: bash scripts/gauntlet.sh
set -u
cd "$(dirname "$0")/.." || exit 1

echo "== 1/6 Umgebung =="
uv sync --quiet || exit 1
uv run python -V

echo "== 2/6 Tests (ohne Integration) =="
uv run pytest -p no:randomly --cov=docpipeline --cov-branch --cov-report=term-missing || exit 1

echo "== 3/6 Tests in zufälliger Reihenfolge =="
uv run pytest -p randomly || exit 1

echo "== 4/6 Lint und Typen =="
uv run ruff check src tests || exit 1
uv run mypy || exit 1

echo "== 5/6 Mutationsprobe =="
uv run python scripts/mutants.py || exit 1

echo "== 6/6 Echt-Tests (OCR + Modell) =="
uv run pytest -m integration -p no:randomly || exit 1

echo "GAUNTLET OK"
