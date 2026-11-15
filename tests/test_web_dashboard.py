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
    refs = result_refs(client.get("/").text)
    assert refs[0] == "TR-2026-1004"
    assert len(refs) == 9


def test_dashboard_shows_filtered_section_with_reasons(client):
    html = client.get("/").text
    assert "Filtered out (21)" in html
    assert "deadline passed" in html


def test_missing_deadline_label(client):
    assert deadline_label(None, TODAY) == "غير محدد / not stated"
    assert deadline_label(TODAY, TODAY) == "Closes today"
    assert deadline_label(date(2026, 11, 27), TODAY) == "12 days left"
    assert "غير محدد / not stated" in client.get("/tenders/TR-2026-1006").text


def test_arabic_title_has_dir_auto(client):
    html = client.get("/").text
    assert re.search(r'dir="auto"[^>]*>\s*حل ذكاء اصطناعي', html)


def test_unknown_tender_404(client):
    assert client.get("/tenders/NOPE").status_code == 404


def test_read_only_hides_profile_link(db_settings):
    engine = make_engine(db_settings.database_url)
    with session_scope(engine) as s:
        profile = first_profile(s)
        live = render_dashboard(s, profile, TODAY, read_only=False)
        static = render_dashboard(s, profile, TODAY, read_only=True)
    engine.dispose()
    assert 'href="/profile"' in live
    assert "/profile" not in static


def test_dashboard_moves_expired_tenders_to_filtered(db_settings):
    # Matching ran on 2026-11-15; viewing on 2026-12-03 means TR-2026-1002 (deadline 2026-12-01) has closed.
    html = TestClient(create_app(db_settings, today=date(2026, 12, 3))).get("/").text
    assert "TR-2026-1002" not in result_refs(html)
