from datetime import date

import pymupdf
from fastapi.testclient import TestClient

from tender_radar.ai.provider import AIError, FakeProvider
from tender_radar.db import make_engine, session_scope
from tender_radar.repository import list_matches, list_profiles

TODAY = date(2026, 11, 15)


def pdf_bytes() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(40, 40, 555, 800), "Acme IT builds software and cloud platforms. " * 20)
    return doc.tobytes()

FORM = {
    "name": "Acme IT",
    "name_ar": "أكمي للتقنية",
    "activities": "تقنية المعلومات",
    "keywords": "برمجيات\nsoftware",
    "certifications": "ISO 27001",
    "regions": "",
    "excluded_agencies": "",
    "min_value_sar": "100000",
    "max_value_sar": "",
}


def app(settings, **kw):
    from tender_radar.web.app import create_app

    return TestClient(create_app(settings, today=TODAY, **kw))


def profiles(settings):
    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        found = {p.id: p for p in list_profiles(s)}
        matches = {pid: list_matches(s, pid) for pid in found}
    engine.dispose()
    return found, matches


def test_add_company_page_in_both_languages(db_settings):
    client = app(db_settings)
    en = client.get("/en/companies/new")
    assert en.status_code == 200
    assert 'type="file"' in en.text and 'name="keywords"' in en.text
    assert "Add your company" in en.text
    ar = client.get("/ar/companies/new")
    assert ar.status_code == 200 and 'dir="rtl"' in ar.text


def test_manual_add_saves_and_matches(db_settings):
    fake = FakeProvider()
    response = app(db_settings, provider=fake).post("/en/companies/new", data=FORM, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/en/c/acme-it/"
    found, matches = profiles(db_settings)
    assert found["acme-it"].name_ar == "أكمي للتقنية"
    assert found["acme-it"].keywords == ["برمجيات", "software"]
    assert matches["acme-it"]  # matching ran for the new company
    assert "najd-digital" in found  # the existing company is untouched


def test_same_name_gets_a_new_id(db_settings):
    client = app(db_settings, provider=FakeProvider())
    client.post("/en/companies/new", data=FORM)
    response = client.post("/en/companies/new", data=FORM, follow_redirects=False)
    assert response.headers["location"] == "/en/c/acme-it-2/"


def test_bad_value_range_keeps_input(db_settings):
    form = {**FORM, "min_value_sar": "5000000", "max_value_sar": "1000"}
    response = app(db_settings, provider=FakeProvider()).post("/en/companies/new", data=form)
    assert response.status_code == 422
    assert "The minimum value must not be greater than the maximum value." in response.text
    assert "برمجيات" in response.text
    assert "acme-it" not in profiles(db_settings)[0]


def test_blank_name_is_rejected(db_settings):
    response = app(db_settings, provider=FakeProvider()).post("/en/companies/new", data={**FORM, "name": "  "})
    assert response.status_code == 422
    assert "Please enter a company name." in response.text


def test_saved_without_ai_still_creates_company(db_settings):
    from tender_radar.settings import Settings

    broken = Settings(database_url=db_settings.database_url, ai_provider="gemini", gemini_api_key=None, gemini_model=None)
    response = app(broken).post("/en/companies/new", data=FORM, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/en/c/acme-it/"
    assert "acme-it" in profiles(db_settings)[0]


def test_upload_prefills_form_without_saving(db_settings):
    fake = FakeProvider([{"name": "Draft Co", "keywords": ["سحابية", "cloud"], "min_value_sar": 250000}])
    response = app(db_settings, provider=fake).post(
        "/en/companies/new/extract", files={"file": ("profile.pdf", pdf_bytes(), "application/pdf")}
    )
    assert response.status_code == 200
    assert 'value="Draft Co"' in response.text
    assert "سحابية\ncloud" in response.text
    assert 'value="250000"' in response.text
    assert "draft-co" not in profiles(db_settings)[0]


def test_upload_unreadable_pdf_shows_error_and_form(db_settings):
    fake = FakeProvider()
    response = app(db_settings, provider=fake).post(
        "/en/companies/new/extract", files={"file": ("p.pdf", b"not a pdf", "application/pdf")}
    )
    assert response.status_code == 400
    assert 'role="alert"' in response.text and 'name="keywords"' in response.text
    assert fake.calls == []


def test_upload_empty_file(db_settings):
    response = app(db_settings, provider=FakeProvider()).post(
        "/en/companies/new/extract", files={"file": ("p.pdf", b"", "application/pdf")}
    )
    assert response.status_code == 400 and "The file is empty." in response.text


def test_upload_ai_failure_still_shows_form(db_settings):
    fake = FakeProvider([AIError("down")] * 3)
    response = app(db_settings, provider=fake).post(
        "/en/companies/new/extract", files={"file": ("p.pdf", pdf_bytes(), "application/pdf")}
    )
    assert response.status_code == 502
    assert 'role="alert"' in response.text and 'name="keywords"' in response.text


def test_read_only_shows_preview_without_forms(db_settings):
    client = app(db_settings, read_only=True)
    page = client.get("/en/companies/new")
    assert page.status_code == 200
    assert "<form" not in page.text and "disabled" in page.text
    assert "runs locally" in page.text
    assert client.post("/en/companies/new", data=FORM).status_code in (404, 405)
    assert client.post("/en/companies/new/extract", files={"file": ("p.pdf", b"x", "application/pdf")}).status_code in (404, 405)


def test_home_hero_links_to_add_company_not_source(db_settings):
    html = app(db_settings).get("/en/").text
    assert 'href="/en/companies/new"' in html
    assert "View source" not in html and "Open source" not in html


def test_companies_page_has_add_card(db_settings):
    client = app(db_settings, provider=FakeProvider())
    client.post("/en/companies/new", data=FORM)  # two companies, so the chooser shows
    html = client.get("/en/companies").text
    assert 'href="/en/companies/new"' in html
