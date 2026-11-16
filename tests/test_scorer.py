from datetime import date

import pytest

from tender_radar.ai.provider import FakeProvider, RateLimited
from tender_radar.db import session_scope
from tender_radar.matching.scorer import build_score_prompt, run_matching
from tender_radar.repository import get_match, upsert_tenders

TODAY = date(2026, 11, 15)
PASSING = 9  # seed tenders that pass the rule filter (see test_rules.test_seed_data_split)
FIRST_PASSING = "000000001001"
VALID = {"score": 88, "reasons_en": ["strong fit"], "reasons_ar": ["مناسب جدا"]}


def no_sleep(_seconds: float) -> None:
    pass


@pytest.fixture
def seeded(engine, seed_tenders):
    with session_scope(engine) as s:
        upsert_tenders(s, seed_tenders)
    return engine


def run(engine, profile, fake, **kw):
    with session_scope(engine) as s:
        return run_matching(s, profile, fake, TODAY, sleep=no_sleep, **kw)


def test_prompt_contains_tender_and_profile(seed_tenders, profile):
    prompt = build_score_prompt(seed_tenders[0], profile)
    assert seed_tenders[0].title in prompt
    assert profile.name in prompt


def test_run_scores_only_prefiltered(seeded, profile):
    fake = FakeProvider()
    stats = run(seeded, profile, fake)
    assert stats.scored == PASSING
    assert stats.filtered_out == 30 - PASSING
    assert len(fake.calls) == PASSING


def test_second_run_is_fully_cached(seeded, profile):
    run(seeded, profile, FakeProvider())
    fake = FakeProvider()
    stats = run(seeded, profile, fake)
    assert len(fake.calls) == 0
    assert stats.cached == 30


def test_profile_change_rescores(seeded, profile):
    run(seeded, profile, FakeProvider())
    changed = profile.model_copy(update={"keywords": profile.keywords + ["شبكات"]})
    fake = FakeProvider()
    stats = run(seeded, changed, fake)
    assert stats.cached == 0
    assert len(fake.calls) >= PASSING


def test_prompt_change_rescores(seeded, profile, monkeypatch):
    """Editing score_tender.md must invalidate cached scores, or a calibrated
    prompt would never reach tenders that were already scored."""
    from tender_radar.matching import scorer

    run(seeded, profile, FakeProvider())
    monkeypatch.setattr(scorer, "_prompt_template", lambda: "a new, calibrated prompt {profile_json} {tender_json}")
    fake = FakeProvider()
    stats = run(seeded, profile, fake)
    assert stats.cached == 0
    assert len(fake.calls) == PASSING


def test_scoring_stores_english_title_once(engine, profile):
    from tender_radar.models import Tender
    from tender_radar.repository import get_tender

    imported = Tender(reference="R9", title="تطوير برمجيات", agency="جهة بمنطقة الرياض", tender_type="منافسة عامة",
                      activity="تقنية المعلومات", estimated_value_sar=1_000_000, source="etimad-import")
    with session_scope(engine) as s:
        upsert_tenders(s, [imported])
    answer = dict(VALID, title_en="Software development", agency_en="An agency, Riyadh Region")
    run(engine, profile, FakeProvider([answer]))
    with session_scope(engine) as s:
        t = get_tender(s, "R9")
    assert (t.title_en, t.agency_en) == ("Software development", "An agency, Riyadh Region")
    fake = FakeProvider()
    stats = run(engine, profile, fake)  # writing the English title is not a content change
    assert fake.calls == [] and stats.cached == 1


def test_score_prompt_asks_for_english_title_but_never_sends_ours(seed_tenders, profile):
    from tender_radar.matching import scorer

    assert '"title_en"' in scorer._prompt_template() and '"agency_en"' in scorer._prompt_template()
    prompt = build_score_prompt(seed_tenders[0], profile)
    assert seed_tenders[0].title_en not in prompt  # the AI translates the Arabic, it is not shown our English


def test_malformed_json_marks_unscored_and_continues(seeded, profile):
    stats = run(seeded, profile, FakeProvider([{"score": "high"}]))
    assert stats.unscored == 1
    assert stats.scored == PASSING - 1
    with session_scope(seeded) as s:
        assert get_match(s, FIRST_PASSING, profile.id).status == "unscored"


def test_rate_limit_retries_then_succeeds(seeded, profile):
    stats = run(seeded, profile, FakeProvider([RateLimited("429"), VALID]))
    assert stats.unscored == 0
    with session_scope(seeded) as s:
        m = get_match(s, FIRST_PASSING, profile.id)
    assert (m.status, m.score) == ("scored", 88)


def test_rate_limit_exhausted_unscored_and_retried_next_run(seeded, profile):
    stats = run(seeded, profile, FakeProvider([RateLimited("429")] * 3), max_retries=2)
    assert stats.unscored == PASSING  # quota gone: the rest of the run is skipped, not hammered
    fake = FakeProvider([VALID])
    second = run(seeded, profile, fake)
    assert len(fake.calls) == PASSING
    assert second.scored == PASSING
    with session_scope(seeded) as s:
        assert get_match(s, FIRST_PASSING, profile.id).score == 88


def test_cached_score_is_filtered_once_deadline_passes(engine, profile):
    from tender_radar.models import Tender

    t = Tender(reference="R1", title="تطوير برمجيات", agency="جهة", tender_type="عامة", activity="تقنية المعلومات",
               region="الرياض", deadline=date(2026, 11, 20), estimated_value_sar=1_000_000)
    with session_scope(engine) as s:
        upsert_tenders(s, [t])
        assert run_matching(s, profile, FakeProvider(), date(2026, 11, 15), sleep=no_sleep).scored == 1
    with session_scope(engine) as s:
        later = run_matching(s, profile, FakeProvider(), date(2026, 12, 1), sleep=no_sleep)
        m = get_match(s, "R1", profile.id)
    assert later.filtered_out == 1
    assert (m.status, m.reasons_en) == ("filtered_out", ["deadline passed"])


def test_quota_exhausted_stops_calling_ai_for_rest_of_run(seeded, profile):
    fake = FakeProvider([RateLimited("429")] * 50)
    stats = run(seeded, profile, fake, max_retries=2)
    assert len(fake.calls) == 3
    assert stats.unscored == PASSING


def test_out_of_range_score_is_rejected_not_stored(seeded, profile):
    stats = run(seeded, profile, FakeProvider([{"score": 150, "reasons_en": ["x"], "reasons_ar": ["س"]}]))
    assert stats.unscored == 1
    with session_scope(seeded) as s:
        assert get_match(s, FIRST_PASSING, profile.id).score is None


def test_unscored_tender_is_logged_with_the_reason(seeded, profile, caplog):
    from tender_radar.ai.provider import AIError

    with caplog.at_level("WARNING", logger="tender_radar.matching.scorer"):
        run(seeded, profile, FakeProvider([AIError("503 UNAVAILABLE")]))
    assert any(FIRST_PASSING in r.getMessage() and "503 UNAVAILABLE" in r.getMessage() for r in caplog.records)
