"""The cheap, free rule filter that runs before any AI call.

Most tenders are obviously wrong for the company (wrong field, deadline gone,
too big). Rejecting them with simple rules keeps AI usage, and cost, low.
Rules run in order and the first failure decides the reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from tender_radar.arabic import normalize
from tender_radar.models import CompanyProfile, Tender


@dataclass
class RuleResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def prefilter(tender: Tender, profile: CompanyProfile, today: date) -> RuleResult:
    """Decide whether a tender is worth sending to the AI for scoring."""
    excluded = {normalize(a) for a in profile.excluded_agencies}
    if normalize(tender.agency) in excluded:
        return RuleResult(False, ["excluded agency"])

    if tender.deadline is not None and tender.deadline < today:
        return RuleResult(False, ["deadline passed"])

    value = tender.estimated_value_sar
    if value is not None:
        if profile.min_value_sar is not None and value < profile.min_value_sar:
            return RuleResult(False, ["value outside range"])
        if profile.max_value_sar is not None and value > profile.max_value_sar:
            return RuleResult(False, ["value outside range"])

    if profile.regions and tender.region:
        if normalize(tender.region) not in {normalize(r) for r in profile.regions}:
            return RuleResult(False, ["region not covered"])

    haystack = normalize(f"{tender.title} {tender.activity} {tender.description}")
    matched = [term for term in profile.keywords + profile.activities if normalize(term) in haystack]
    if not matched:
        return RuleResult(False, ["no keyword match"])
    return RuleResult(True, [f"matched: {term}" for term in matched])
