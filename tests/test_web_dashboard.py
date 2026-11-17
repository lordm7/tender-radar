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


# --- matches page polish (2026-11-17) ---
# Conftest scores: 95, 82 -> worth bidding; 75, 71, 66, 60, 58, 50 -> closer look; 40 -> skip.

from tender_radar.models import MatchResult  # noqa: E402
from tender_radar.repository import get_tender, list_matches, save_match, tender_content_hash  # noqa: E402

IT = "najd-digital"


def restore(settings, ref, **changes):
    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        m = next(m for m in list_matches(s, IT) if m.tender_reference == ref)
        save_match(s, m.model_copy(update=changes), tender_content_hash(get_tender(s, ref)))
    engine.dispose()


def selected(html: str) -> str:
    return html.split('id="selected"', 1)[1].split("</section>", 1)[0]


def test_header_counts_by_verdict(client):
    html = client.get(f"/en/c/{IT}/").text
    assert "<b>2</b> worth bidding" in html and "<b>6</b> worth a closer look" in html
    assert "worth a look" not in html


def test_list_grouped_by_verdict(client):
    html = client.get(f"/en/c/{IT}/").text
    heads = re.findall(r'<li class="group"[^>]*>([^<]+)<', html)
    assert [h.strip() for h in heads] == ["Worth bidding (2)", "Worth a closer look (6)", "Probably skip (1)"]


def test_row_shows_agency_value_and_days(client):
    html = client.get(f"/en/c/{IT}/").text
    row = html.split('data-reference="000000001004"', 1)[1].split("</li>", 1)[0]
    assert "2,200,000 SAR" in row and "Coastal Governorate Municipality" in row and "days left" in row


def test_selected_panel_shows_verdict_and_parts(client):
    sel = selected(client.get(f"/en/c/{IT}/").text)
    assert 'id="sel-verdict"' in sel and "Worth bidding" in sel
    assert 'id="sel-parts"' in sel and sel.count('class="part ') == 3


def test_selected_panel_without_parts_shows_reason(db_settings):
    restore(db_settings, "000000001004", parts=None, reasons_en=["old reason"], reasons_ar=["سبب قديم"])
    sel = selected(TestClient(create_app(db_settings, today=TODAY)).get(f"/en/c/{IT}/").text)
    assert "old reason" in sel and sel.count('class="part ') == 0


def test_unscored_tender_in_its_own_group(db_settings):
    restore(db_settings, "000000001001", status="unscored", score=None, parts=None)
    html = TestClient(create_app(db_settings, today=TODAY)).get(f"/en/c/{IT}/").text
    assert "Not scored yet (1)" in html


def test_groups_in_arabic(client):
    html = client.get(f"/ar/c/{IT}/").text
    assert "تستحق التقديم (2)" in html and "تستحق نظرة أدق (6)" in html


def test_companies_card_uses_verdict_numbers(db_settings):
    engine = make_engine(db_settings.database_url)
    with session_scope(engine) as s:
        from tender_radar.web.app import render_companies
        html = render_companies(s, TODAY, read_only=False)
    engine.dispose()
    assert "<span class=\"big\">2</span> worth bidding" in html and "6 worth a closer look" in html
    assert "worth a look" not in html
