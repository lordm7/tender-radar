from datetime import date

from fastapi.testclient import TestClient

from tender_radar.ai.provider import FakeProvider
from tender_radar.db import make_engine, session_scope
from tender_radar.repository import first_profile
from tender_radar.web.app import create_app

TODAY = date(2026, 11, 15)


def form_from(profile, **overrides) -> dict:
    data = {
        "name": profile.name,
        "activities": "\n".join(profile.activities),
        "keywords": "\n".join(profile.keywords),
        "certifications": "\n".join(profile.certifications),
        "regions": "\n".join(profile.regions),
        "excluded_agencies": "\n".join(profile.excluded_agencies),
        "min_value_sar": str(profile.min_value_sar or ""),
        "max_value_sar": str(profile.max_value_sar or ""),
    }
    data.update(overrides)
    return data


def current_profile(settings):
    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        p = first_profile(s)
    engine.dispose()
    return p


def test_profile_page_shows_form(db_settings):
    client = TestClient(create_app(db_settings, today=TODAY))
    html = client.get("/profile").text
    assert "<form" in html
    assert "سيبراني" in html


def test_profile_edit_saves_and_rescores(db_settings, profile):
    fake = FakeProvider()
    client = TestClient(create_app(db_settings, today=TODAY, provider=fake))
    form = form_from(profile, keywords="\n".join(profile.keywords + ["صيانة"]))
    response = client.post("/profile", data=form, follow_redirects=False)
    assert response.status_code == 303
    saved = current_profile(db_settings)
    assert "صيانة" in saved.keywords
    assert saved.version != profile.version
    assert len(fake.calls) > 0


def test_profile_rejects_min_greater_than_max(db_settings, profile):
    client = TestClient(create_app(db_settings, today=TODAY, provider=FakeProvider()))
    response = client.post("/profile", data=form_from(profile, min_value_sar="5000000", max_value_sar="1000"))
    assert response.status_code == 422
    assert "Minimum value must not be greater than the maximum value" in response.text
    assert current_profile(db_settings).min_value_sar == profile.min_value_sar


def test_profile_route_absent_in_read_only(db_settings):
    client = TestClient(create_app(db_settings, today=TODAY, read_only=True))
    assert client.get("/profile").status_code == 404
