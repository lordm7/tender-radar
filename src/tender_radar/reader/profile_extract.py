"""Read a company-profile PDF and draft a bidding profile from it with one AI call.

A new company can upload its profile document instead of typing everything.
The AI only proposes values (a ProfileDraft); the person checks and edits the
form before anything is saved, so a wrong guess never reaches matching.
"""

from __future__ import annotations

import re
from importlib import resources

from pydantic import BaseModel

from tender_radar.ai.provider import LLMProvider, call_with_retry
from tender_radar.reader.brief import MAX_INPUT_CHARS, _join_pages


class ProfileDraft(BaseModel):
    """Every CompanyProfile field except the id; anything the document does not say stays empty."""

    name: str = ""
    name_ar: str | None = None
    activities: list[str] = []
    keywords: list[str] = []
    certifications: list[str] = []
    regions: list[str] = []
    excluded_agencies: list[str] = []
    min_value_sar: float | None = None
    max_value_sar: float | None = None

    def form_values(self) -> dict[str, str]:
        """The draft as the profile form's text fields (lists become one item per line)."""
        return {
            "name": self.name,
            "name_ar": self.name_ar or "",
            "activities": "\n".join(self.activities),
            "keywords": "\n".join(self.keywords),
            "certifications": "\n".join(self.certifications),
            "regions": "\n".join(self.regions),
            "excluded_agencies": "\n".join(self.excluded_agencies),
            "min_value_sar": "" if self.min_value_sar is None else f"{self.min_value_sar:.0f}",
            "max_value_sar": "" if self.max_value_sar is None else f"{self.max_value_sar:.0f}",
        }


def extract_profile(pages: list[str], provider: LLMProvider) -> ProfileDraft:
    """Ask the AI to fill a ProfileDraft from the document's pages (retries on 429/503)."""
    text = _join_pages(pages)[:MAX_INPUT_CHARS]
    template = resources.files("tender_radar.prompts").joinpath("extract_profile.md").read_text(encoding="utf-8")
    prompt = template.replace("{document_text}", text)
    return call_with_retry(lambda: provider.generate_json(prompt, ProfileDraft))


def new_profile_id(name: str, existing_ids: list[str]) -> str:
    """A URL-safe id for a new company: "Acme IT" -> "acme-it", "acme-it-2" on a clash.

    Names with no Latin letters (an Arabic-only name) get "company-1", "company-2", …
    """
    taken = set(existing_ids)
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not base:
        n = 1
        while f"company-{n}" in taken:
            n += 1
        return f"company-{n}"
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f"{base}-{n}"
    return candidate
