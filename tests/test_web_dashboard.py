import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from tender_radar.db import make_engine, session_scope
from tender_radar.repository import first_profile
from tender_radar.web.app import create_app, deadline_label, render_dashboard

TODAY = date(2026, 11, 15)


@pytest.fixture
def client(db_settings):
    return TestClient(create_app(db_settings, today=TODAY))


def result_refs(html: str) -> list[str]:
    results = html.split('id="results"', 1)[1].split('id="filtered"', 1)[0]
    return re.findall(r'data-reference="([^"]+)"', results)


def test_dashboard_lists_scored_first(client):
    refs = result_refs(client.get("/en/c/najd-digital/").text)
    assert refs[0] == "000000001004"
    assert len(refs) == 9


def test_dashboard_shows_filtered_section_with_reasons(client):
    html = client.get("/en/c/najd-digital/").text
    assert "21 filtered by rules" in html
    assert "Deadline passed" in html


def test_missing_deadline_label(client):
    assert deadline_label(None, TODAY) == "No deadline stated"
    assert deadline_label(TODAY, TODAY) == "Closes today"
    assert deadline_label(date(2026, 11, 27), TODAY) == "12 days left"
    assert deadline_label(date(2026, 11, 27), TODAY, "ar") == "12 يومًا متبقيًا"
    assert "No deadline stated" in client.get("/en/c/najd-digital/tenders/000000001006").text


def test_arabic_page_lists_arabic_titles(client):
    html = client.get("/ar/c/najd-digital/").text
    assert re.search(r'<span class="title">\s*حل ذكاء اصطناعي', html)


def test_unknown_tender_404(client):
    assert client.get("/c/najd-digital/tenders/NOPE").status_code == 404


def test_read_only_hides_profile_link(db_settings):
    engine = make_engine(db_settings.database_url)
    with session_scope(engine) as s:
        profile = first_profile(s)
        live = render_dashboard(s, profile, TODAY, read_only=False)
        static = render_dashboard(s, profile, TODAY, read_only=True)
    engine.dispose()
    assert 'href="/en/c/najd-digital/profile"' in live
    assert "/profile" not in static


def test_dashboard_moves_expired_tenders_to_filtered(db_settings):
    # Matching ran on 2026-11-15; viewing on 2026-12-03 means 000000001002 (deadline 2026-12-01) has closed.
    html = TestClient(create_app(db_settings, today=date(2026, 12, 3))).get("/en/c/najd-digital/").text
    assert "000000001002" not in result_refs(html)


def test_tender_page_shows_etimad_card_fields(client):
    html = client.get("/en/c/najd-digital/tenders/000000001002").text  # paid booklet (500), closes 12:00
    assert "500 SAR" in html
    assert "12:00" in html
    assert "Inquiries until" in html
    assert "View on Etimad" not in html  # seed tenders have no source link
    free = client.get("/en/c/najd-digital/tenders/000000001001").text
    assert "<dd>Free</dd>" in free


def test_tender_page_shows_inferred_region(client):
    html = client.get("/en/c/najd-digital/tenders/000000001003").text  # agency name says "بالمنطقة الشرقية"
    assert "Eastern Province" in html and "(from the agency name)" in html
    arabic = client.get("/ar/c/najd-digital/tenders/000000001003").text
    assert "المنطقة الشرقية" in arabic and "(مستنتجة من اسم الجهة)" in arabic
