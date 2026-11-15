"""Arabic text normalisation for matching.

The same Arabic word can be written several ways: with or without hamza (أ/ا),
with ة or ه at the end, with ى or ي, with or without diacritics, and with
Arabic-Indic digits (٢٠٢٦) or Latin ones (2026). Normalising both sides first
makes keyword matching ignore those spelling differences.
"""

from __future__ import annotations

import re

_DIACRITICS = re.compile(r"[ً-ْٰ]")  # tanween, harakat, shadda, sukun, dagger alef
_TATWEEL = "ـ"
_LETTER_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})
_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase and unify Arabic spelling variants so comparisons are fair."""
    text = text.lower()
    text = _DIACRITICS.sub("", text)
    text = text.replace(_TATWEEL, "")
    text = text.translate(_LETTER_MAP).translate(_DIGIT_MAP)
    return _SPACES.sub(" ", text).strip()
