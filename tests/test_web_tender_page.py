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
