"""Several companies share one tender list; each gets its own matches and pages."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from tender_radar.ai.provider import FakeProvider
from tender_radar.db import make_engine, session_scope
from tender_radar.export.static_site import ExportError, export_site
from tender_radar.matching.scorer import run_matching
from tender_radar.models import load_profile
from tender_radar.repository import list_matches, list_profiles, save_profile
from tender_radar.web.app import create_app, tender_slug

from conftest import SEED

TODAY = date(2026, 11, 15)
IT, BUILD = "najd-digital", "al-bunyan"


@pytest.fixture
def two_companies(db_settings):
    engine = make_engine(db_settings.database_url)
    with session_scope(engine) as s:
        contracting = load_profile(SEED / "profile_contracting.json")
        save_profile(s, contracting)
        run_matching(s, contracting, FakeProvider(), TODAY)
    engine.dispose()
    return db_settings


def passed(settings, profile_id):
    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        refs = {m.tender_reference for m in list_matches(s, profile_id) if m.status != "filtered_out"}
    engine.dispose()
    return refs


def test_each_company_gets_its_own_matches(two_companies):
    it, build = passed(two_companies, IT), passed(two_companies, BUILD)
    assert "000000002001" in build and "000000002001" not in it  # office building construction
    assert "000000001004" in it and "000000001004" not in build  # AI platform
    assert "000000002006" not in build  # roads in Makkah: region not covered


def test_chooser_lists_companies_when_several(two_companies):
    client = TestClient(create_app(two_companies, today=TODAY))
    html = client.get("/en/companies").text
    assert "Najd Digital Solutions (synthetic)" in html
    assert "Al-Bunyan Contracting &amp; Maintenance (synthetic)" in html
    assert f'href="/en/c/{BUILD}/"' in html
    assert "نجد للحلول الرقمية" in client.get("/ar/companies").text
    assert 'href="/en/companies"' in client.get("/en/").text  # "Live demo" opens the chooser


def test_chooser_goes_straight_to_the_only_company(db_settings):
    response = TestClient(create_app(db_settings, today=TODAY)).get("/en/companies", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == f"/en/c/{IT}/"


def test_unknown_company_404(db_settings):
    assert TestClient(create_app(db_settings, today=TODAY)).get("/en/c/nobody/").status_code == 404


def test_company_dashboard_links_stay_inside_the_company(two_companies):
    html = TestClient(create_app(two_companies, today=TODAY)).get(f"/en/c/{BUILD}/").text
    assert f'href="/en/c/{BUILD}/tenders/000000002001"' in html
    assert f'href="/en/c/{BUILD}/profile"' in html


def test_read_only_server_uses_real_routes_not_html_files(two_companies):
    client = TestClient(create_app(two_companies, today=TODAY, read_only=True))
    html = client.get(f"/en/c/{IT}/").text
    assert f'href="/en/c/{IT}/tenders/000000001004"' in html
    assert ".html" not in html
    assert "<form" not in client.get(f"/en/c/{IT}/tenders/000000001004").text


def test_reader_lets_you_pick_the_company(two_companies):
    html = TestClient(create_app(two_companies, today=TODAY)).get("/en/reader").text
    assert f'<option value="{BUILD}"' in html


def export(settings, out):
    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        written = export_site(s, list_profiles(s), TODAY, out)
    engine.dispose()
    return written


def test_export_has_a_chooser_and_one_folder_per_company(two_companies, tmp_path):
    out = tmp_path / "site"
    export(two_companies, out)
    chooser = (out / "en" / "companies.html").read_text(encoding="utf-8")
    assert f'href="../en/c/{IT}/index.html"' in chooser and f'href="../en/c/{BUILD}/index.html"' in chooser
    assert 'href="../en/companies.html"' in (out / "en" / "index.html").read_text(encoding="utf-8")  # live demo
    build = (out / "en" / "c" / BUILD / "index.html").read_text(encoding="utf-8")
    assert 'href="../../../en/c/al-bunyan/tenders/000000002001.html"' in build  # relative to the site root
    assert (out / "en" / "c" / BUILD / "tenders" / "000000002001.html").exists()
    assert (out / "ar" / "c" / BUILD / "tenders" / "000000002001.html").exists()
    assert 'src="../../../static/app.js"' in build
    detail = (out / "en" / "c" / BUILD / "tenders" / "000000002001.html").read_text(encoding="utf-8")
    assert 'href="../../../../en/c/al-bunyan/index.html"' in detail


def test_export_removes_stale_files(two_companies, tmp_path):
    out = tmp_path / "site"
    export(two_companies, out)
    stale = out / "en" / "c" / IT / "tenders" / "old-tender.html"
    stale.write_text("old", encoding="utf-8")
    export(two_companies, out)
    assert not stale.exists()


def test_export_refuses_to_clear_a_folder_it_did_not_create(two_companies, tmp_path):
    precious = tmp_path / "my-documents"
    precious.mkdir()
    (precious / "report.docx").write_text("important", encoding="utf-8")
    with pytest.raises(ExportError):
        export(two_companies, precious)
    assert (precious / "report.docx").exists()


def test_slug_avoids_collisions():
    assert tender_slug("000000001004") == "000000001004"
    assert tender_slug("A/1") != tender_slug("A-1")
    assert tender_slug("A/1") != tender_slug("A?1")
