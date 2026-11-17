"""Language routes (/en/…, /ar/…), the language switch, the home page and the radar."""

import json
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from tender_radar.db import make_engine, session_scope
from tender_radar.repository import list_tenders, upsert_tenders
from tender_radar.web.app import create_app, radar_point

TODAY = date(2026, 11, 15)
IT = "najd-digital"
ARABIC = re.compile(r"[؀-ۿ]")


@pytest.fixture
def client(db_settings):
    return TestClient(create_app(db_settings, today=TODAY))


# --- routing ----------------------------------------------------------------

def test_root_redirects_to_english_by_default(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307 and response.headers["location"] == "/en/"


def test_root_remembers_the_last_language(client):
    client.get("/ar/")
    response = client.get("/", follow_redirects=False)
    assert response.headers["location"] == "/ar/"


def test_unknown_language_is_404(client):
    assert client.get("/fr/").status_code == 404
    assert client.get(f"/fr/c/{IT}/").status_code == 404


def test_old_links_redirect_to_english(client):
    response = client.get(f"/c/{IT}/tenders/000000001004", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == f"/en/c/{IT}/tenders/000000001004"
    assert client.get("/briefs/sample", follow_redirects=False).headers["location"] == "/en/briefs/sample"
    assert client.get("/reader", follow_redirects=False).headers["location"] == "/en/reader"


def test_companies_page_goes_straight_to_the_only_company(client):
    response = client.get("/en/companies", follow_redirects=False)
    assert response.status_code == 307 and response.headers["location"] == f"/en/c/{IT}/"


# --- one language per page --------------------------------------------------

def test_arabic_pages_are_right_to_left(client):
    for url in ("/ar/", f"/ar/c/{IT}/", f"/ar/c/{IT}/tenders/000000001004", "/ar/reader", f"/ar/c/{IT}/profile"):
        html = client.get(url).text
        assert '<html lang="ar" dir="rtl">' in html, url


def test_english_pages_are_left_to_right(client):
    assert '<html lang="en" dir="ltr">' in client.get(f"/en/c/{IT}/").text


def test_switch_points_to_the_same_page_in_the_other_language(client):
    html = client.get(f"/en/c/{IT}/tenders/000000001004").text
    assert f'href="/ar/c/{IT}/tenders/000000001004"' in html
    html = client.get(f"/ar/c/{IT}/").text
    assert f'href="/en/c/{IT}/"' in html


def test_english_tender_page_shows_english_title_and_agency(client):
    html = client.get(f"/en/c/{IT}/tenders/000000001004").text
    assert "AI solution to analyse and classify citizen reports" in html
    assert "Coastal Governorate Municipality, Makkah Region" in html
    assert "حل ذكاء اصطناعي" not in html


def test_arabic_tender_page_shows_arabic_title(client):
    html = client.get(f"/ar/c/{IT}/tenders/000000001004").text
    assert "حل ذكاء اصطناعي لتحليل بلاغات المواطنين وتصنيفها" in html
    assert "AI solution to analyse" not in html


def test_untranslated_import_is_tagged_arabic_original(db_settings):
    engine = make_engine(db_settings.database_url)
    with session_scope(engine) as s:
        real = list_tenders(s)[0].model_copy(update={
            "reference": "999000000123", "title": "منافسة مستوردة", "title_en": None, "agency_en": None,
            "source": "etimad-import",
        })
        upsert_tenders(s, [real])
    engine.dispose()
    html = TestClient(create_app(db_settings, today=TODAY)).get(f"/en/c/{IT}/tenders/999000000123").text
    assert re.search(r'<span class="orig" lang="ar"[^>]*>منافسة مستوردة</span>', html)
    assert "Arabic original" in html


def test_bidding_profile_is_renamed(client):
    html = client.get(f"/en/c/{IT}/").text
    assert "Bidding profile" in html and "Company profile" not in html
    assert "ملف المنافسة" in client.get(f"/ar/c/{IT}/").text


def test_arabic_rule_reasons_are_translated(client):
    html = client.get(f"/ar/c/{IT}/").text
    assert "انتهى موعد التقديم" in html and "deadline passed" not in html


# --- home page --------------------------------------------------------------

def test_home_page_has_hero_stats_and_footer(client):
    html = client.get("/en/").text
    assert "Know which government tenders are worth bidding on." in html
    assert "Built by" in html and "Mohammed Alzalam" in html
    assert "https://github.com/lordm7/tender-radar" in html
    assert "not affiliated with Etimad" in html
    assert f'href="/en/c/{IT}/"' in html  # "Open live demo" goes to the only company


def test_home_page_never_shows_imported_tenders_even_in_the_live_app(db_settings):
    engine = make_engine(db_settings.database_url)
    with session_scope(engine) as s:
        real = list_tenders(s)[3].model_copy(update={
            "reference": "999000000555", "title": "منافسة حقيقية سرية", "title_en": "Secret real tender",
            "source": "etimad-import",
        })
        upsert_tenders(s, [real])
    engine.dispose()
    client = TestClient(create_app(db_settings, today=TODAY))
    for url in ("/en/", "/ar/"):
        html = client.get(url).text
        assert "999000000555" not in html and "Secret real tender" not in html and "منافسة حقيقية سرية" not in html


# --- dashboard radar ----------------------------------------------------------

def test_radar_point_is_deterministic_and_better_fits_sit_closer():
    assert radar_point("000000001004", 90) == radar_point("000000001004", 90)
    def dist(p):
        return ((p[0] - 50) ** 2 + (p[1] - 50) ** 2) ** 0.5
    assert dist(radar_point("A", 95)) < dist(radar_point("A", 40))
    assert dist(radar_point("A", 95)) == pytest.approx(5 * 0.45, abs=0.02)  # coordinates are rounded to 2 decimals
    assert all(0 <= c <= 100 for c in radar_point("B", 0))


def test_dashboard_embeds_page_language_data_and_preselects_the_best(client):
    html = client.get(f"/en/c/{IT}/").text
    data = json.loads(re.search(r'<script type="application/json" id="tr-data">(.*?)</script>', html, re.S).group(1))
    assert data[0]["ref"] == "000000001004"
    assert data[0]["title"] == "AI solution to analyse and classify citizen reports"
    assert not any(ARABIC.search(json.dumps(d, ensure_ascii=False)) for d in data)
    selected = html.split('id="selected"', 1)[1].split("</section>", 1)[0]
    assert "AI solution to analyse and classify citizen reports" in selected  # works without JS
    assert html.count('class="dot') >= 9


def test_dashboard_header_numbers(client):
    html = client.get(f"/en/c/{IT}/").text
    assert re.search(r'<b[^>]*>2</b>\s*worth bidding', html) and re.search(r'<b[^>]*>6</b>\s*worth a closer look', html)
    assert re.search(r'<b[^>]*>21</b>\s*filtered by rules', html)
