from datetime import date

import pymupdf
from fastapi.testclient import TestClient

from tender_radar.ai.provider import FakeProvider
from tender_radar.models import BookletBrief
from tender_radar.web.app import MAX_UPLOAD_BYTES, create_app, render_brief

TODAY = date(2026, 11, 15)


def pdf_bytes(with_text: bool = True) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    if with_text:
        page.insert_textbox(pymupdf.Rect(40, 40, 555, 800), "Scope: digital appointments platform. " * 20)
    else:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
        pix.clear_with(200)
        page.insert_image(pymupdf.Rect(40, 40, 240, 240), pixmap=pix)
    return doc.tobytes()


def upload(client, content: bytes, name: str = "booklet.pdf"):
    return client.post("/en/reader", files={"file": (name, content, "application/pdf")}, follow_redirects=False)


def test_reader_page_has_upload_form(db_settings):
    html = TestClient(create_app(db_settings, today=TODAY)).get("/en/reader").text
    assert 'type="file"' in html


def test_upload_pdf_shows_brief(db_settings):
    client = TestClient(create_app(db_settings, today=TODAY, provider=FakeProvider()))
    response = upload(client, pdf_bytes())
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert "Fake summary" in page.text and "ملخص تجريبي" not in page.text  # English page, English brief
    assert "ISO 27001" in page.text
    arabic = client.get(response.headers["location"].replace("/en/", "/ar/"))
    assert "ملخص تجريبي" in arabic.text and "Fake summary" not in arabic.text


def test_upload_scanned_pdf_shows_friendly_error(db_settings):
    fake = FakeProvider()
    client = TestClient(create_app(db_settings, today=TODAY, provider=fake))
    response = upload(client, pdf_bytes(with_text=False))
    assert response.status_code == 400
    assert "looks scanned" in response.text
    assert fake.calls == []


def test_oversize_upload_413(db_settings):
    fake = FakeProvider()
    client = TestClient(create_app(db_settings, today=TODAY, provider=fake))
    response = upload(client, b"%PDF-" + b"0" * MAX_UPLOAD_BYTES)
    assert response.status_code == 413
    assert fake.calls == []


def test_brief_truncated_banner():
    html = render_brief(BookletBrief(scope="نطاق", truncated=True), "big.pdf", read_only=False)
    assert "Long booklet: only the first part was analysed." in html


def test_sample_brief_route(db_settings):
    client = TestClient(create_app(db_settings, today=TODAY, provider=FakeProvider()))
    assert client.get("/en/briefs/sample").status_code == 404
    upload(client, pdf_bytes(), name="sample_booklet.pdf")
    assert client.get("/en/briefs/sample").status_code == 200
    assert client.get("/ar/briefs/sample").status_code == 200


def test_reader_absent_in_read_only(db_settings):
    client = TestClient(create_app(db_settings, today=TODAY, read_only=True))
    assert client.get("/en/reader").status_code == 404


def test_ai_failure_shows_friendly_502(db_settings):
    from tender_radar.ai.provider import AIError

    client = TestClient(create_app(db_settings, today=TODAY, provider=FakeProvider([AIError("503")])))
    response = upload(client, pdf_bytes())
    assert response.status_code == 502
    assert "could not read this booklet right now" in response.text


def test_empty_upload_is_rejected_without_ai(db_settings):
    fake = FakeProvider()
    client = TestClient(create_app(db_settings, today=TODAY, provider=fake))
    response = upload(client, b"")
    assert response.status_code == 400
    assert "The file is empty" in response.text
    assert fake.calls == []


def test_upload_route_runs_in_a_worker_thread():
    """A plain `def` route runs in FastAPI's thread pool, so PDF reading and the
    AI call do not block other visitors (an `async def` route would)."""
    import inspect

    app = create_app(today=TODAY)
    route = next(r for r in app.routes if getattr(r, "path", "") == "/{lang}/reader" and "POST" in r.methods)
    assert not inspect.iscoroutinefunction(route.endpoint)
