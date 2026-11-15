"""The matching run: rule filter, then AI scoring, with caching and safe failure.

For every tender:
  1. If we already have a verdict for this exact tender content and profile
     version, reuse it (no AI call, no cost).
  2. If the free rule filter rejects it, store "filtered_out" with the reason.
  3. Otherwise ask the AI for a score. If the provider is rate-limited, wait and
     retry a few times. If it still fails, or returns bad JSON, store
     "unscored" and move on. One bad answer never stops the whole run, and
     unscored tenders are retried on the next run.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from importlib import resources
from typing import Callable

from pydantic import ValidationError
from sqlalchemy.orm import Session

from tender_radar.ai.provider import AIError, LLMProvider, RateLimited
from tender_radar.matching.rules import prefilter
from tender_radar.models import AIScore, CompanyProfile, MatchResult, Tender
from tender_radar.repository import get_match, get_match_hash, get_tender_hash, list_tenders, save_match

log = logging.getLogger(__name__)

UNSCORED_REASON = "AI unavailable – will retry next run"
# Free-tier quotas are counted per minute, so wait long enough for the window to move (15s, then 30s).
RETRY_WAIT_SECONDS = 15


@dataclass
class RunStats:
    filtered_out: int = 0
    scored: int = 0
    unscored: int = 0
    cached: int = 0


def build_score_prompt(tender: Tender, profile: CompanyProfile) -> str:
    """Fill the scoring prompt template with the profile and the tender."""
    template = resources.files("tender_radar.prompts").joinpath("score_tender.md").read_text(encoding="utf-8")
    return template.replace("{profile_json}", profile.model_dump_json(indent=2)).replace(
        "{tender_json}", tender.model_dump_json(indent=2)
    )


def _ask_ai(
    provider: LLMProvider, prompt: str, max_retries: int, sleep: Callable[[float], None], reference: str = ""
) -> AIScore | None:
    """Return the AI score, or None if the answer was unusable.

    Raises RateLimited when the provider is still rate-limited after all retries,
    so the caller can stop spending calls for the rest of the run.
    """
    for attempt in range(max_retries + 1):
        try:
            return provider.generate_json(prompt, AIScore)
        except RateLimited:
            if attempt == max_retries:
                raise
            sleep(RETRY_WAIT_SECONDS * (2**attempt))
        except (AIError, ValidationError) as exc:
            log.warning("Tender %s left unscored: %s", reference, " ".join(str(exc).split())[:300])
            return None
    return None


def run_matching(
    session: Session,
    profile: CompanyProfile,
    provider: LLMProvider,
    today: date,
    max_retries: int = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> RunStats:
    """Score every stored tender against the profile; see the module docstring."""
    stats = RunStats()
    version = profile.version
    quota_exhausted = False  # after the AI keeps saying "too many requests", stop asking this run
    for tender in list_tenders(session):
        content_hash = get_tender_hash(session, tender.reference)
        existing = get_match(session, tender.reference, profile.id)
        # The rules are free, so they always run: a deadline can pass while the cached score stays valid.
        rules = prefilter(tender, profile, today)
        cache_valid = (
            existing is not None
            and existing.status != "unscored"
            and existing.profile_version == version
            and get_match_hash(session, tender.reference, profile.id) == content_hash
        )
        if cache_valid and (rules.passed or existing.status == "filtered_out"):
            stats.cached += 1
            continue

        base = dict(tender_reference=tender.reference, profile_id=profile.id, profile_version=version)
        if not rules.passed:
            save_match(session, MatchResult(**base, status="filtered_out", reasons_en=rules.reasons), content_hash)
            stats.filtered_out += 1
            continue

        ai = None
        if not quota_exhausted:
            try:
                ai = _ask_ai(provider, build_score_prompt(tender, profile), max_retries, sleep, tender.reference)
            except RateLimited:
                quota_exhausted = True
                log.warning("AI still rate-limited after %d retries; skipping AI calls for the rest of this run", max_retries)
        if ai is None:
            save_match(session, MatchResult(**base, status="unscored", reasons_en=[UNSCORED_REASON]), content_hash)
            stats.unscored += 1
        else:
            save_match(
                session,
                MatchResult(**base, status="scored", score=ai.score, reasons_en=ai.reasons_en, reasons_ar=ai.reasons_ar),
                content_hash,
            )
            stats.scored += 1
    return stats
