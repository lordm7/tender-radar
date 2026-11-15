from tender_radar.db import session_scope
from tender_radar.models import BookletBrief, MatchResult
from tender_radar.repository import (
    get_brief,
    get_match,
    get_profile,
    latest_brief,
    list_tenders,
    save_brief,
    save_match,
    save_profile,
    tender_content_hash,
    upsert_tenders,
)


def test_upsert_inserts_then_unchanged(engine, seed_tenders):
    with session_scope(engine) as s:
        first = upsert_tenders(s, seed_tenders)
    with session_scope(engine) as s:
        second = upsert_tenders(s, seed_tenders)
    assert (first.inserted, first.updated, first.unchanged) == (30, 0, 0)
    assert (second.inserted, second.updated, second.unchanged) == (0, 0, 30)


def test_upsert_changed_title_updates_and_drops_match(engine, seed_tenders, profile):
    t = seed_tenders[0]
    with session_scope(engine) as s:
        upsert_tenders(s, seed_tenders)
        m = MatchResult(
            tender_reference=t.reference, profile_id=profile.id, profile_version=profile.version,
            status="scored", score=80, reasons_en=["fits"], reasons_ar=["مناسب"],
        )
        save_match(s, m, tender_content_hash(t))
    changed = t.model_copy(update={"title": t.title + " (معدل)"})
    with session_scope(engine) as s:
        stats = upsert_tenders(s, [changed])
    with session_scope(engine) as s:
        assert stats.updated == 1
        assert get_match(s, t.reference, profile.id) is None
        assert len(list_tenders(s)) == 30


def test_profile_roundtrip(engine, profile):
    with session_scope(engine) as s:
        save_profile(s, profile)
    with session_scope(engine) as s:
        assert get_profile(s, profile.id) == profile


def test_brief_roundtrip_latest(engine):
    a = BookletBrief(scope="أ")
    b = BookletBrief(scope="ب")
    with session_scope(engine) as s:
        id_a = save_brief(s, "a.pdf", a)
        save_brief(s, "b.pdf", b)
    with session_scope(engine) as s:
        assert get_brief(s, id_a) == a
        assert latest_brief(s) == ("b.pdf", b)
        assert latest_brief(s, "a.pdf") == ("a.pdf", a)
