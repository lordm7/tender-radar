"""Arabic text normalisation for matching.

The same Arabic word can be written several ways: with or without hamza (أ/ا),
with ة or ه at the end, with ى or ي, with or without diacritics, and with
Arabic-Indic digits (٢٠٢٦) or Latin ones (2026). Normalising both sides first
makes keyword matching ignore those spelling differences.
"""

from __future__ import annotations

import re
import unicodedata

_DIACRITICS = re.compile("[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")  # harakat, tanween, shadda, Quranic marks
_TATWEEL = "ـ"
_LETTER_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ٱ": "ا"})
_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "0123456789" * 2)
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase and unify Arabic spelling variants so comparisons are fair."""
    text = unicodedata.normalize("NFKC", text).lower()  # joins split letters, unfolds ligatures
    text = _DIACRITICS.sub("", text)
    text = text.replace(_TATWEEL, "")
    text = text.translate(_LETTER_MAP).translate(_DIGIT_MAP)
    return _SPACES.sub(" ", text).strip()
