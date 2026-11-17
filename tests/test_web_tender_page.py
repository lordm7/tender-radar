"""The tender page: verdict, profile check, timeline and actions."""

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from tender_radar.web.app import create_app, tender_timeline
from tender_radar.models import Tender

TODAY = date(2026, 11, 15)
IT = "najd-digital"
# Fake scores from conftest: 1004 -> 95, 1005 -> 50, 1006 -> 40 (no deadline).


@pytest.fixture
def client(db_settings):
    return TestClient(create_app(db_settings, today=TODAY))


def page(client, ref, lang="en"):
    return client.get(f"/{lang}/c/{IT}/tenders/{ref}").text


@pytest.mark.parametrize(("ref", "verdict"), [
    ("000000001004", "Worth bidding"), ("000000001005", "Worth a closer look"), ("000000001006", "Probably skip"),
])
def test_verdict_follows_score_bands(client, ref, verdict):
    assert verdict in page(client, ref)


def test_profile_check_lists_each_rule(client):
    html = page(client, "000000001004")
    assert "Profile check" in html
    assert "Agency not on your excluded list" in html
    assert "2,200,000 SAR is within your range (200,000 SAR – 20,000,000 SAR)" in html
    assert "Makkah is covered" in html
    assert re.search(r'Matched: .*<span class="term"><span class="orig" lang="ar"[^>]*>ذكاء اصطناعي</span>', html)
    assert html.count('class="check pass"') == 5


def test_profile_check_in_arabic(client):
    html = page(client, "000000001004", "ar")
    assert "فحص الملف" in html and "مكة المكرمة مغطاة" in html


def test_timeline_shows_dates_and_today(client):
    html = page(client, "000000001004")
    assert 'class="timeline"' in html
    assert "Today" in html and "Questions close" in html and "Bid deadline" in html


def test_no_deadline_means_no_timeline_and_no_calendar(client):
    html = page(client, "000000001006")
    assert 'class="timeline"' not in html and ".ics" not in html
    assert "No deadline stated" in html


def test_actions_link_reader_and_calendar(client):
    html = page(client, "000000001004")
    assert 'href="/en/reader"' in html
    assert 'href="/en/calendar/000000001004.ics"' in html and "Add to calendar" in html


def test_calendar_route(client):
    response = client.get("/en/calendar/000000001004.ics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "DTSTART:20270105T100000Z" in response.text
    assert client.get("/en/calendar/NOPE.ics").status_code == 404


def test_timeline_positions():
    t = Tender(reference="r", title="x", agency="a", tender_type="t", activity="a",
               published_on=date(2026, 11, 5), inquiry_deadline=date(2026, 11, 10), deadline=date(2026, 11, 25))
    tl = tender_timeline(t, date(2026, 11, 15), "en")
    assert tl["today"] == 50.0
    assert [(p["key"], p["pct"], p["past"]) for p in tl["points"]] == [
        ("tl_published", 0.0, True), ("tl_inquiries", 25.0, True), ("tl_deadline", 100.0, False),
    ]
    assert tender_timeline(t.model_copy(update={"deadline": None}), TODAY, "en") is None


# --- "How the AI scored it": the three parts (conftest: 1004 -> fit 95, ability 95, risk 5) ---

from tender_radar.db import make_engine, session_scope  # noqa: E402
from tender_radar.models import MatchResult, ScoreParts  # noqa: E402
from tender_radar.repository import get_tender, save_match  # noqa: E402
from tender_radar.repository import tender_content_hash  # noqa: E402


def store_match(settings, **match):
    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        t = get_tender(s, "000000001004")
        save_match(s, MatchResult(tender_reference=t.reference, profile_id=IT, profile_version="v",
                                  status="scored", **match), tender_content_hash(t))
    engine.dispose()


def test_tender_page_shows_three_parts(client):
    html = page(client, "000000001004")
    assert "How the AI scored it" in html
    assert "Score = 50% fit + 30% ability + 20% low risk" in html
    assert html.count('class="part ') == 3
    assert "Ability" in html and "reason 95 ability" in html


def test_parts_in_arabic(client):
    html = page(client, "000000001004", "ar")
    assert "كيف قيّمها الذكاء الاصطناعي" in html and "سبب 95" in html
    assert "reason 95" not in html


def test_blocker_and_prepare_shown(db_settings):
    parts = ScoreParts(fit=90, ability=30, risk=40, fit_en="f", fit_ar="ف", ability_en="a", ability_ar="ق",
                       risk_en="r", risk_ar="خ", blocker_en="No ISO 27001", blocker_ar="لا توجد شهادة",
                       prepare_en=["Get CR copy"], prepare_ar=["أ", "ب"])
    store_match(db_settings, score=40, parts=parts, reasons_en=["No ISO 27001"], reasons_ar=["لا توجد شهادة"])
    client = TestClient(create_app(db_settings, today=TODAY))
    en = page(client, "000000001004")
    assert "Blocker" in en and "No ISO 27001" in en and "Get CR copy" in en
    ar = page(client, "000000001004", "ar")
    assert "<li>أ</li>" in ar and "<li>ب</li>" in ar and "Get CR copy" not in ar


def test_old_match_without_parts_falls_back(db_settings):
    store_match(db_settings, score=77, reasons_en=["old reason"], reasons_ar=["سبب قديم"])
    html = page(TestClient(create_app(db_settings, today=TODAY)), "000000001004")
    assert "old reason" in html and "How the AI scored it" not in html


def test_blocker_in_one_language_still_explained(db_settings):
    parts = ScoreParts(fit=90, ability=90, risk=10, fit_en="f", fit_ar="ف", ability_en="a", ability_ar="ق",
                       risk_en="r", risk_ar="خ", blocker_ar="لا توجد شهادة مطلوبة")
    store_match(db_settings, score=40, parts=parts, reasons_en=["f"], reasons_ar=["ف"])
    en = page(TestClient(create_app(db_settings, today=TODAY)), "000000001004")
    assert "A hard blocker was found, so the score is capped at 40." in en
