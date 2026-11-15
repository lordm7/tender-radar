"""Extract the text of each page of a PDF booklet (PyMuPDF).

Arabic PDFs often store letters as "presentation forms" (pre-shaped glyphs
such as ﻛ instead of ك). Unicode NFKC normalisation turns them back into
normal letters, so both the AI and our keyword search can read them.
Scanned booklets have no text layer at all; we detect that and stop early
rather than send an empty prompt to the AI.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pymupdf

MIN_TEXT_CHARS = 200


class UnreadablePDF(Exception):
    """The file is not a readable PDF, or it has no extractable text."""


def clean_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def extract_pages(path: Path) -> list[str]:
    """Return the cleaned text of every page, or raise UnreadablePDF."""
    try:
        doc = pymupdf.open(path, filetype="pdf")
    except Exception as exc:
        raise UnreadablePDF("This file could not be opened as a PDF.") from exc
    with doc:
        pages = [clean_text(page.get_text()) for page in doc]
    if sum(len(p.strip()) for p in pages) < MIN_TEXT_CHARS:
        raise UnreadablePDF("This PDF looks scanned (no text layer). OCR is not supported yet.")
    return pages
