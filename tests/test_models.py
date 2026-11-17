from pathlib import Path

import pytest
from pydantic import ValidationError

from tender_radar.models import AIScore, load_profile, load_seed_tenders

SEED = Path(__file__).resolve().parents[1] / "data" / "seed"


def test_seed_tenders_load():
    tenders = load_seed_tenders(SEED / "tenders.json")
    assert len(tenders) >= 30
    refs = [t.reference for t in tenders]
    assert len(refs) == len(set(refs))


def test_profile_version_changes_when_keywords_change():
    p = load_profile(SEED / "profile_it_services.json")
    p2 = p.model_copy(update={"keywords": p.keywords + ["x"]})
    assert p2.version != p.version


def test_profile_version_ignores_name():
    p = load_profile(SEED / "profile_it_services.json")
    p2 = p.model_copy(update={"name": "Another name"})
    assert p2.version == p.version


def test_ai_score_rejects_out_of_range():
    with pytest.raises(ValidationError):
        AIScore(fit=101, ability=50, risk=50, fit_en="x", fit_ar="س", ability_en="x", ability_ar="س", risk_en="x", risk_ar="س")


def test_tender_round_trips_etimad_fields():
    from datetime import date

    from tender_radar.models import Tender

    t = Tender(
        reference="000000001234", title="x", agency="y", tender_type="منافسة عامة", activity="z",
        inquiry_deadline=date(2026, 11, 20), deadline_time="10:00", booklet_price_sar=0,
        source_url="https://example.invalid/t/000000001234",
    )
    again = Tender.model_validate_json(t.model_dump_json())
    assert again == t
    assert again.inquiry_deadline == date(2026, 11, 20)
    assert again.booklet_price_sar == 0


def test_seed_uses_etimad_style_references():
    tenders = load_seed_tenders(SEED / "tenders.json")
    assert all(t.reference.isdigit() and len(t.reference) == 12 for t in tenders)
    assert sum(t.booklet_price_sar == 0 for t in tenders) >= 15
    assert all(t.inquiry_deadline is None or t.inquiry_deadline <= t.deadline for t in tenders)


def test_shift_dates_moves_every_date_by_the_same_days():
    from datetime import date

    from tender_radar.models import SEED_ANCHOR, shift_dates

    tenders = load_seed_tenders(SEED / "tenders.json")
    shifted = shift_dates(tenders, anchor=SEED_ANCHOR, today=date(2026, 12, 25))  # 40 days later
    first, moved = tenders[0], shifted[0]
    assert moved.deadline == date(2027, 1, 19)  # 2026-12-10 + 40
    assert moved.published_on == date(2026, 12, 12)
    assert moved.inquiry_deadline == date(2027, 1, 9)
    assert first.deadline == date(2026, 12, 10)  # originals untouched
    no_deadline = next(t for t in shifted if t.reference == "000000001006")
    assert no_deadline.deadline is None


def test_shift_dates_on_the_anchor_day_changes_nothing():
    from tender_radar.models import SEED_ANCHOR, shift_dates

    tenders = load_seed_tenders(SEED / "tenders.json")
    assert shift_dates(tenders, anchor=SEED_ANCHOR, today=SEED_ANCHOR) == tenders
