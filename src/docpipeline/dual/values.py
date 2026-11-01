"""Zahlen für den Abgleich normalisieren (B4).

Deutsch und englisch gemischt: `1.428,50`, `1.428.50`, `1428,50` und `1428.50`
werden zum selben Schlüssel. Ohne erkennbare Zahl gilt die Textnormalisierung
der Basis.
"""

from __future__ import annotations

import re

from docpipeline.dedup import normalize

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)*")
_SPACED = re.compile(r"-?\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?")
_CLEAN = str.maketrans({" ": "", "\u00a0": "", "\u202f": ""})
_MAX_DECIMAL_DIGITS = 2
_THOUSANDS_GROUP = 3
_TWO_GROUPS = 2
_NUMERIC_SHARE = 0.6
_UNITS = re.compile(r"\b(?:EUR|USD|CHF|Euro|euro)\b|[€$£]", re.IGNORECASE)


def normalize_value(text: str) -> str:
    """Kanonische Zahlform oder, wenn der Text keine Zahl ist, normalisierter Text.

    Enthält der Text viel mehr als die Zahl (etwa ein Satz mit einer Hausnummer),
    bleibt der Text der Schlüssel. Sonst würden zwei verschiedene Namen mit
    derselben Nummer zusammenfallen.
    """
    if not _is_numeric(text):
        return normalize(text)
    match = _first_number(text)
    if match is None:
        return normalize(text)
    raw = match.group().translate(_CLEAN)
    negative = raw.startswith("-")
    digits = raw.lstrip("+-")
    if not digits:
        return normalize(text)
    whole, decimals = _split(digits)
    canonical = whole if decimals is None else f"{whole}.{decimals}"
    if negative and canonical.strip("0."):
        return f"-{canonical}"
    return canonical


def _first_number(text: str) -> re.Match[str] | None:
    """Erste Zahl im Text; eine Zahl mit Leerzeichen-Tausendern zählt als Ganzes."""
    candidates = [match for match in (_SPACED.search(text), _NUMBER.search(text)) if match]
    if not candidates:
        return None
    return min(candidates, key=lambda match: (match.start(), -len(match.group())))


def _is_numeric(text: str) -> bool:
    """Zahlenschlüssel nur, wenn der Text überwiegend aus Ziffern besteht."""
    cleaned = _UNITS.sub(" ", text)
    symbols = [char for char in cleaned if char.isalnum()]
    if not symbols:
        return False
    digits = sum(1 for char in symbols if char.isdigit())
    return digits / len(symbols) >= _NUMERIC_SHARE


def _split(digits: str) -> tuple[str, str | None]:
    """Trennt Tausender- von Dezimaltrennzeichen."""
    if "," in digits and "." in digits:
        return _split_mixed(digits)
    if "," in digits:
        return _split_single(digits, ",")
    if "." in digits:
        return _split_single(digits, ".")
    return digits, None


def _split_mixed(digits: str) -> tuple[str, str | None]:
    """Beide Trennzeichen vorhanden: das letzte ist das Dezimalzeichen."""
    if digits.rfind(",") > digits.rfind("."):
        head, _, tail = digits.rpartition(",")
        return head.replace(".", ""), tail
    head, _, tail = digits.rpartition(".")
    return head.replace(",", ""), tail


def _split_single(digits: str, separator: str) -> tuple[str, str | None]:
    """Ein Trennzeichen: Dezimalzeichen nur bei kurzer letzter Gruppe."""
    parts = digits.split(separator)
    last = parts[-1]
    is_decimal = len(last) != _THOUSANDS_GROUP
    if is_decimal and len(last) <= _MAX_DECIMAL_DIGITS and len(parts) >= _TWO_GROUPS:
        return "".join(parts[:-1]), last
    return digits.replace(separator, ""), None
