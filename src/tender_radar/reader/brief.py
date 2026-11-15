"""Turn booklet pages into a structured brief with one AI call.

Pages are joined with "[page N]" markers so the AI can tell where things are.
Long booklets are cut at MAX_INPUT_CHARS to stay inside free-tier limits, and
the brief is flagged `truncated` so the page can say so honestly.
"""

from __future__ import annotations

from importlib import resources

from tender_radar.ai.provider import LLMProvider
from tender_radar.models import BookletBrief, CompanyProfile

MAX_INPUT_CHARS = 60_000


def _join_pages(pages: list[str]) -> str:
    return "\n\n".join(f"[page {i}]\n{text.strip()}" for i, text in enumerate(pages, start=1))


def build_brief(pages: list[str], profile: CompanyProfile, provider: LLMProvider) -> BookletBrief:
    text = _join_pages(pages)
    truncated = len(text) > MAX_INPUT_CHARS
    if truncated:
        text = text[:MAX_INPUT_CHARS]
    template = resources.files("tender_radar.prompts").joinpath("booklet_brief.md").read_text(encoding="utf-8")
    prompt = template.replace("{profile_json}", profile.model_dump_json(indent=2)).replace("{booklet_text}", text)
    brief = provider.generate_json(prompt, BookletBrief)
    return brief.model_copy(update={"truncated": truncated})
