"""Data shapes used everywhere in Tender Radar.

Pydantic models validate data the moment it enters the app (seed files, AI
answers, form posts), so the rest of the code can trust what it gets. Think of
them as Java records with built-in validation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
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
    estimated_value_sar: float | None = None
    description: str = ""
    source: str = "seed"


class CompanyProfile(BaseModel):
    """What the company does and which tenders it can bid on."""

    id: str
    name: str
    activities: list[str]
    keywords: list[str]
    certifications: list[str] = []
    min_value_sar: float | None = None
    max_value_sar: float | None = None
    regions: list[str] = []
    excluded_agencies: list[str] = []

    @property
    def version(self) -> str:
        """Short fingerprint of everything that affects matching.

        The id and name are left out on purpose: renaming the company does not
        change which tenders fit, so it must not trigger paid AI re-scoring.
        """
        payload = self.model_dump_json(exclude={"id", "name"})
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


def _read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_seed_tenders(path: Path) -> list[Tender]:
    """Load tenders from a JSON file shaped like {"_note": ..., "tenders": [...]}."""
    data = _read_json(path)
    return [Tender.model_validate(item) for item in data["tenders"]]


def load_profile(path: Path) -> CompanyProfile:
    """Load a company profile; extra keys such as "_note" are ignored."""
    return CompanyProfile.model_validate(_read_json(path))
