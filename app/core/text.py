"""Text normalization shared by dedup, search and answer grading."""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Canonical form used for uniqueness and exact comparison."""
    text = unicodedata.normalize("NFC", text or "")
    return _WS.sub(" ", text).strip().casefold()


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "D")


def loose(text: str) -> str:
    """Accent- and punctuation-insensitive form for lenient matching."""
    text = strip_accents(normalize(text))
    return _WS.sub(" ", re.sub(r"[^\w\s]", "", text)).strip()


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]
