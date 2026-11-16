"""Data shapes used everywhere in Tender Radar.

Pydantic models validate data the moment it enters the app (seed files, AI
answers, form posts), so the rest of the code can trust what it gets. Think of
them as Java records with built-in validation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Tender(BaseModel):
    """One public tender listing (as shown on Etimad)."""

    reference: str
    title: str
    agency: str
    tender_type: str
    activity: str
    region: str | None = None
    published_on: date | None = None
    deadline: date | None = None
    inquiry_deadline: date | None = None  # last day to send questions to the agency
    deadline_time: str | None = None  # closing time on the deadline day, "HH:MM"
    booklet_price_sar: float | None = None  # price of the tender documents; 0 = free
    source_url: str | None = None  # link to the original listing (real imports only)
    estimated_value_sar: float | None = None
    description: str = ""
    source: str = "seed"
    # English text for English-mode pages: hand-written for seed tenders, written by
    # the scoring call for imports. Not part of the content (see tender_content_hash).
    title_en: str | None = None
    agency_en: str | None = None
    description_en: str | None = None


ENGLISH_FIELDS = ("title_en", "agency_en", "description_en")


class CompanyProfile(BaseModel):
    """What the company does and which tenders it can bid on."""

    id: str
    name: str
    name_ar: str | None = None  # the company name shown on Arabic pages
    activities: list[str]
    keywords: list[str]
    certifications: list[str] = []
    min_value_sar: float | None = None
    max_value_sar: float | None = None
    regions: list[str] = []
    excluded_agencies: list[str] = []

    @model_validator(mode="after")
    def _check_value_range(self) -> "CompanyProfile":
        if self.min_value_sar is not None and self.max_value_sar is not None and self.min_value_sar > self.max_value_sar:
            raise ValueError("Minimum value must not be greater than the maximum value")
        return self

    @property
    def version(self) -> str:
        """Short fingerprint of everything that affects matching.

        The id and name are left out on purpose: renaming the company does not
        change which tenders fit, so it must not trigger paid AI re-scoring.
        """
        payload = self.model_dump_json(exclude={"id", "name", "name_ar"})
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


class MatchResult(BaseModel):
    """The verdict for one tender against one profile version."""

    tender_reference: str
    profile_id: str
    profile_version: str
    status: Literal["filtered_out", "scored", "unscored"]
    score: int | None = Field(default=None, ge=0, le=100)
    reasons_en: list[str] = []
    reasons_ar: list[str] = []


class AIScore(BaseModel):
    """The JSON shape we ask the AI to return when scoring a tender."""

    score: int = Field(ge=0, le=100)
    reasons_en: list[str]
    reasons_ar: list[str]
    title_en: str | None = None  # English translation of the tender title, for English pages
    agency_en: str | None = None


class ChecklistItem(BaseModel):
    """One go/no-go line: does the company meet this requirement?"""

    item: str
    status: Literal["meets", "gap", "check"]
    note: str = ""


class BookletBrief(BaseModel):
    """The one-page summary the AI writes from a tender booklet."""

    scope: str
    deliverables: list[str] = []
    key_dates: list[str] = []
    eligibility: list[str] = []
    required_documents: list[str] = []
    evaluation_criteria: list[str] = []
    risks: list[str] = []
    go_no_go: list[ChecklistItem] = []
    truncated: bool = False


class BookletAnswer(BaseModel):
    """The AI's answer to one question about a booklet, with the pages it used."""

    answer: str
    citations: list[int] = []  # 1-based page numbers the answer comes from
    found: bool = True  # False when the booklet does not say


def _read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_seed_tenders(path: Path) -> list[Tender]:
    """Load tenders from a JSON file shaped like {"_note": ..., "tenders": [...]}."""
    data = _read_json(path)
    return [Tender.model_validate(item) for item in data["tenders"]]


# The day the synthetic seed dates were written for. `seed --rolling` moves every
# date forward by (today - SEED_ANCHOR), so the public demo never looks stale.
SEED_ANCHOR = date(2026, 11, 15)
_DATE_FIELDS = ("published_on", "inquiry_deadline", "deadline")


def shift_dates(tenders: list[Tender], anchor: date, today: date) -> list[Tender]:
    """Copies of the tenders with every date moved by the days between anchor and today."""
    delta = timedelta(days=(today - anchor).days)
    return [
        t.model_copy(update={f: getattr(t, f) + delta for f in _DATE_FIELDS if getattr(t, f) is not None})
        for t in tenders
    ]


def load_profile(path: Path) -> CompanyProfile:
    """Load a company profile; extra keys such as "_note" are ignored."""
    return CompanyProfile.model_validate(_read_json(path))
