"""The three-part AI score: fit, ability and risk from the AI, the total from Python."""

from datetime import date

import pytest
from pydantic import ValidationError

from ai_answers import ai_answer
from tender_radar.ai.provider import FakeProvider
from tender_radar.db import session_scope
from tender_radar.matching.scorer import readable_reasons, run_matching, total_score
from tender_radar.models import MatchResult, ScoreParts
from tender_radar.repository import get_match, save_match, upsert_tenders

TODAY = date(2026, 11, 15)
FIRST_PASSING = "000000001001"


def parts(**kw) -> ScoreParts:
    base = dict(fit=80, ability=70, risk=30, fit_en="f", fit_ar="ف", ability_en="a", ability_ar="ق",
                risk_en="r", risk_ar="خ")
    return ScoreParts(**{**base, **kw})


def test_total_uses_weights():
    assert total_score(parts()) == 75  # 40 + 21 + 14


def test_total_extremes():
    assert total_score(parts(fit=100, ability=100, risk=0)) == 100
    assert total_score(parts(fit=0, ability=0, risk=100)) == 0


def test_blocker_caps_at_40():
    assert total_score(parts(fit=100, ability=100, risk=0, blocker_en="No CR licence")) == 40


def test_blocker_does_not_raise_a_low_score():
    assert total_score(parts(fit=20, ability=20, risk=90, blocker_en="x")) == 18  # 10 + 6 + 2


def test_blank_blocker_is_no_blocker():
    p = parts(blocker_en="  ", blocker_ar="")
    assert not p.has_blocker
    assert total_score(p) == 75


def test_reasons_order():
    assert readable_reasons(parts(blocker_en="B", blocker_ar="ع"), "en") == ["B", "f", "a", "r"]
    assert readable_reasons(parts(), "ar") == ["ف", "ق", "خ"]


def test_part_out_of_range_is_invalid():
    with pytest.raises(ValidationError):
        parts(risk=120)


@pytest.fixture
def seeded(engine, seed_tenders):
    with session_scope(engine) as s:
        upsert_tenders(s, seed_tenders)
    return engine


def run(engine, profile, fake):
    with session_scope(engine) as s:
        return run_matching(s, profile, fake, TODAY, sleep=lambda _s: None)


def test_run_matching_stores_parts_and_total(seeded, profile):
    run(seeded, profile, FakeProvider([ai_answer(90, 80, 20, prepare_en=["Get the CR copy"], prepare_ar=["نسخة السجل"])]))
    with session_scope(seeded) as s:
        m = get_match(s, FIRST_PASSING, profile.id)
    assert m.status == "scored" and m.score == 85  # 45 + 24 + 16
    assert m.parts.fit == 90 and m.parts.prepare_en == ["Get the CR copy"]
    assert m.reasons_en[0] == "reason fit" and m.reasons_ar[0] == "سبب الملاءمة"


def test_parts_survive_the_database(seeded, profile):
    with session_scope(seeded) as s:
        save_match(s, MatchResult(tender_reference=FIRST_PASSING, profile_id=profile.id, profile_version="v",
                                  status="scored", score=71, parts=parts()), "h")
        save_match(s, MatchResult(tender_reference="000000001002", profile_id=profile.id, profile_version="v",
                                  status="scored", score=50, reasons_en=["old"]), "h")
    with session_scope(seeded) as s:
        assert get_match(s, FIRST_PASSING, profile.id).parts == parts()
        assert get_match(s, "000000001002", profile.id).parts is None


def test_out_of_range_answer_leaves_tender_unscored(seeded, profile):
    stats = run(seeded, profile, FakeProvider([ai_answer(risk=150)]))
    assert stats.unscored == 1
    with session_scope(seeded) as s:
        assert get_match(s, FIRST_PASSING, profile.id).status == "unscored"


# --- final review fixes ---

@pytest.mark.parametrize(("fit", "ability", "risk", "expected"), [
    (10, 97, 23, 50),   # 49.5 -> 50 (floating point gave 49.4999...)
    (30, 97, 23, 60),   # 59.5 -> 60
    (92, 57, 98, 64),   # 63.5 -> 64
])
def test_half_totals_round_up_exactly(fit, ability, risk, expected):
    assert total_score(parts(fit=fit, ability=ability, risk=risk)) == expected


@pytest.mark.parametrize("empty", ["None", "null", " N/A ", "none.", "لا يوجد", "-"])
def test_empty_marker_text_is_no_blocker(empty):
    p = parts(blocker_en=empty, blocker_ar=empty)
    assert not p.has_blocker
    assert total_score(p) == 75
    assert readable_reasons(p, "en") == ["f", "a", "r"]
