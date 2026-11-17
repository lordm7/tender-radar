"""The cheap, free rule filter that runs before any AI call.

Most tenders are obviously wrong for the company (wrong field, deadline gone,
too big). Rejecting them with simple rules keeps AI usage, and cost, low.
Rules run in order and the first failure decides the reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from tender_radar.arabic import normalize
from tender_radar.models import CompanyProfile, Tender
from tender_radar.regions import infer_region


@dataclass
class RuleResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class RuleCheck:
    """One rule's outcome. passed=None means the tender lacks the data to check it
    (no deadline, no value, unknown region); like a pass, it never filters a tender out."""

    name: str  # agency | deadline | value | region | keywords
    passed: bool | None
    reason: str = ""  # the stored filter reason when it fails, e.g. "value outside range"
    detail: dict = field(default_factory=dict)  # values the tender page shows


def check_rules(tender: Tender, profile: CompanyProfile, today: date) -> list[RuleCheck]:
    """Run every rule and report each result (the tender page's "Profile check")."""
    excluded = {normalize(a) for a in profile.excluded_agencies}
    checks = [RuleCheck("agency", normalize(tender.agency) not in excluded, "excluded agency")]

    if tender.deadline is None:
        checks.append(RuleCheck("deadline", None))
    else:
        checks.append(RuleCheck("deadline", tender.deadline >= today, "deadline passed", {"deadline": tender.deadline}))

    value = tender.estimated_value_sar
    low, high = profile.min_value_sar, profile.max_value_sar
    if value is None:
        checks.append(RuleCheck("value", None))
    else:
        inside = (low is None or value >= low) and (high is None or value <= high)
        checks.append(RuleCheck("value", inside, "value outside range", {"value": value, "min": low, "max": high}))

    region = tender.region or infer_region(tender.agency)
    if not profile.regions:
        checks.append(RuleCheck("region", True, detail={"region": None}))  # the company covers every region
    elif not region:
        checks.append(RuleCheck("region", None))
    else:
        covered = normalize(region) in {normalize(r) for r in profile.regions}
        checks.append(RuleCheck("region", covered, "region not covered", {"region": region}))

    haystack = normalize(f"{tender.title} {tender.activity} {tender.description}")
    matched = [term for term in profile.keywords + profile.activities if _contains(haystack, normalize(term))]
    checks.append(RuleCheck("keywords", bool(matched), "no keyword match", {"terms": matched}))
    return checks


def prefilter(tender: Tender, profile: CompanyProfile, today: date) -> RuleResult:
    """Decide whether a tender is worth sending to the AI for scoring.

    The first failed rule (in check_rules order) decides the reason.
    """
    checks = check_rules(tender, profile, today)
    failed = next((c for c in checks if c.passed is False), None)
    if failed is not None:
        return RuleResult(False, [failed.reason])
    return RuleResult(True, [f"matched: {term}" for term in checks[-1].detail["terms"]])


def _contains(haystack: str, term: str) -> bool:
    """Arabic terms match anywhere (words take prefixes like ال/و/ب); Latin terms
    match whole words only, so "AI" does not match inside "maintenance"."""
    if term.isascii():
        return re.search(rf"\b{re.escape(term)}\b", haystack) is not None
    return term in haystack
