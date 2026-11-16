"""Ask the booklet: answer a question about a tender booklet, citing its pages.

This is a small retrieval-augmented generation (RAG) step. A short booklet is
sent whole. A long one is ranked page by page with Arabic-aware keyword
matching (an IDF score, like a mini search engine), and only the best pages
that fit the character budget go to the AI. The AI must cite the pages it
used; citations of pages it was never shown are dropped, so a page number on
screen always points at real text.
"""

from __future__ import annotations

import math
import re
from importlib import resources

from tender_radar.ai.provider import LLMProvider
from tender_radar.arabic import normalize
from tender_radar.models import BookletAnswer

MAX_CONTEXT_CHARS = 20_000  # well inside free-tier limits, and fast
NOT_FOUND_EMPTY = BookletAnswer(answer="Please type a question.", citations=[], found=False)
NO_CITATION = "The AI did not point to a page for this answer, so check it in the booklet."

_WORD = re.compile(r"\w+")
_PREFIXES = ("وال", "بال", "فال", "كال", "لل", "ال")  # "and the", "with the", "the", ...
_STOPWORDS = {
    "ما", "ماذا", "هل", "هي", "هو", "في", "من", "على", "الى", "عن", "او", "و", "كم", "متي", "اين", "كيف", "التي", "الذي",
    "what", "is", "are", "the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "does", "do", "how", "when", "which",
}


def _terms(text: str) -> list[str]:
    """Normalised words with common Arabic prefixes removed and stopwords dropped."""
    words = []
    for word in _WORD.findall(normalize(text)):
        if word in _STOPWORDS:
            continue
        for prefix in _PREFIXES:
            if word.startswith(prefix) and len(word) - len(prefix) >= 2:
                word = word[len(prefix):]
                break
        if len(word) >= 2:
            words.append(word)
    return words


def select_pages(question: str, pages: list[str], budget_chars: int = MAX_CONTEXT_CHARS) -> list[int]:
    """The 1-based page numbers to send to the AI, in page order."""
    if sum(len(p) for p in pages) <= budget_chars:
        return list(range(1, len(pages) + 1))
    page_terms = [set(_terms(p)) for p in pages]
    wanted = set(_terms(question))
    # IDF: a word found on few pages tells us more than a word found everywhere.
    idf = {t: math.log((len(pages) + 1) / (1 + sum(t in pt for pt in page_terms))) + 1 for t in wanted}
    scores = [sum(idf[t] for t in wanted if t in pt) for pt in page_terms]
    # Best-scoring pages first; pages with no match keep their order, so the
    # start of the booklet is the fallback (e.g. an English question on Arabic text).
    order = sorted(range(len(pages)), key=lambda i: (-scores[i], i))
    chosen, used = [], 0
    for i in order:
        if chosen and used + len(pages[i]) > budget_chars:
            continue
        chosen.append(i + 1)
        used += len(pages[i])
    return sorted(chosen)


def build_ask_prompt(question: str, pages: list[str], chosen: list[int]) -> str:
    template = resources.files("tender_radar.prompts").joinpath("ask_booklet.md").read_text(encoding="utf-8")
    text = "\n\n".join(f"[page {n}]\n{pages[n - 1].strip()}" for n in chosen)
    return template.replace("{question}", question.strip()).replace("{pages}", text)


def answer_question(question: str, pages: list[str], provider: LLMProvider) -> BookletAnswer:
    """Ask the AI one question about the booklet. AI errors are raised to the caller."""
    if not question.strip():
        return NOT_FOUND_EMPTY.model_copy()
    chosen = select_pages(question, pages)
    answer = provider.generate_json(build_ask_prompt(question, pages, chosen), BookletAnswer)
    allowed = set(chosen)
    citations = sorted({n for n in answer.citations if n in allowed})
    if answer.found and not citations:  # an answer we cannot trace to a page is not shown as fact
        return BookletAnswer(answer=f"{answer.answer}\n{NO_CITATION}", citations=[], found=False)
    return answer.model_copy(update={"citations": citations})
