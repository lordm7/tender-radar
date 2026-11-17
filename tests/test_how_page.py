"""The "How it works" page: the real pipeline with real numbers, and one traced tender."""

from datetime import date

from tender_radar.db import make_engine, session_scope
from tender_radar.models import MatchResult
from tender_radar.repository import get_tender, list_matches, save_match, tender_content_hash, upsert_tenders
from tender_radar.web.app import pipeline_story

TODAY = date(2026, 11, 15)
IT = "najd-digital"
# Fake scores from conftest: 1004 -> 95 (fit 95, ability 95, risk 5), then 82, 75...


def story(settings, lang="en"):
    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        result = pipeline_story(s, TODAY, lang)
    engine.dispose()
    return result


def edit(settings, fn):
    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        fn(s)
    engine.dispose()


def scored(ref, score, parts, s):
    t = get_tender(s, ref)
    save_match(s, MatchResult(tender_reference=ref, profile_id=IT, profile_version="v", status="scored",
                              score=score, parts=parts, reasons_en=["x"], reasons_ar=["س"]), tender_content_hash(t))


def test_story_traces_best_tender(db_settings):
    st = story(db_settings)
    assert st["trace"]["ref"] == "000000001004"
    assert st["trace"]["score"] == 95
    assert st["trace"]["formula"] == "0.5 × 95 + 0.3 × 95 + 0.2 × (100 − 5) = 95.0 → 95"
    assert st["trace"]["verdict"] == "verdict_bid"
    assert st["counts"] == {"tenders": 30, "filtered": 21, "scored": 9, "unscored": 0, "top": [95, 82, 75]}


def test_story_ignores_private_tenders(db_settings):
    def add_private(s):
        copy = get_tender(s, "000000001004").model_copy(update={"reference": "123456789012", "source": "etimad-import"})
        upsert_tenders(s, [copy])
        parts = list_matches(s, IT)[0].parts or next(m.parts for m in list_matches(s, IT) if m.parts)
        scored("123456789012", 99, parts, s)
    edit(db_settings, add_private)
    st = story(db_settings)
    assert st["trace"]["ref"] == "000000001004"
    assert st["counts"]["tenders"] == 30


def test_story_tie_picks_lowest_reference(db_settings):
    def tie(s):
        best = next(m for m in list_matches(s, IT) if m.tender_reference == "000000001004")
        scored("000000001002", 95, best.parts, s)
    edit(db_settings, tie)
    assert story(db_settings)["trace"]["ref"] == "000000001002"


def test_story_without_parts_has_no_trace(db_settings):
    def strip(s):
        for m in list_matches(s, IT):
            if m.status == "scored":
                scored(m.tender_reference, m.score, None, s)
    edit(db_settings, strip)
    st = story(db_settings)
    assert st["trace"] is None
    assert st["counts"]["scored"] == 9 and st["company"]


# --- the page ---

from fastapi.testclient import TestClient  # noqa: E402

from tender_radar.web.app import create_app  # noqa: E402


def test_how_page_in_both_languages(db_settings):
    client = TestClient(create_app(db_settings, today=TODAY))
    en = client.get("/en/how")
    assert en.status_code == 200
    for text in ("How Tender Radar works", "One tender, step by step",
                 "0.5 × 95 + 0.3 × 95 + 0.2 × (100 − 5) = 95.0 → 95", "matching/rules.py"):
        assert text in en.text
    ar = client.get("/ar/how").text
    assert "كيف يعمل رادار المنافسات" in ar
    assert 'lang="en" dir="ltr">Gemini' in ar


def test_how_page_read_only(db_settings):
    assert TestClient(create_app(db_settings, today=TODAY, read_only=True)).get("/en/how").status_code == 200


def test_nav_links_to_how(db_settings):
    client = TestClient(create_app(db_settings, today=TODAY))
    assert 'href="/en/how"' in client.get(f"/en/c/{IT}/").text
    assert 'href="/en/how"' in client.get("/en/").text


# --- final review fixes ---

from datetime import timedelta  # noqa: E402

from tender_radar.db import TenderRow  # noqa: E402

from tender_radar.models import ScoreParts  # noqa: E402
from tender_radar.repository import get_profile, save_profile  # noqa: E402


def test_expired_best_tender_is_not_traced(db_settings):
    def expire(s):  # closes after the last matching run: the stored match stays
        s.get(TenderRow, "000000001004").deadline = TODAY - timedelta(days=1)
    edit(db_settings, expire)
    assert next(m for m in story_matches(db_settings) if m.tender_reference == "000000001004").status == "scored"
    assert story(db_settings)["trace"]["ref"] != "000000001004"


def story_matches(settings):
    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        result = list_matches(s, IT)
    engine.dispose()
    return result


def test_blocker_cap_is_explained(db_settings):
    parts = ScoreParts(fit=95, ability=90, risk=35, fit_en="f", fit_ar="ف", ability_en="a", ability_ar="ق",
                       risk_en="r", risk_ar="خ", blocker_en="No ISO 27001 certificate", blocker_ar="لا توجد شهادة")
    def block_all(s):
        for m in list_matches(s, IT):
            if m.status == "scored":
                scored(m.tender_reference, 40, parts, s)
    edit(db_settings, block_all)
    html = TestClient(create_app(db_settings, today=TODAY)).get("/en/how").text
    assert "= 87.5 → 40" in html and "No ISO 27001 certificate" in html


def test_formula_hidden_when_stored_score_differs(db_settings):
    def rescore(s):
        best = next(m for m in list_matches(s, IT) if m.tender_reference == "000000001004")
        scored("000000001004", 99, best.parts, s)  # e.g. scored under older weights
    edit(db_settings, rescore)
    tr = story(db_settings)["trace"]
    assert tr["score"] == 99 and tr["formula"] is None


def test_company_without_arabic_name_is_marked(db_settings):
    def drop_ar(s):
        save_profile(s, get_profile(s, IT).model_copy(update={"name_ar": None}))
    edit(db_settings, drop_ar)
    ar = TestClient(create_app(db_settings, today=TODAY)).get("/ar/how").text
    assert 'lang="en"' in ar.split("numbers-for", 1)[1].split("</span>", 1)[0]
