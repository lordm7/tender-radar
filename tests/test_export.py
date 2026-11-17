import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from tender_radar.db import make_engine, session_scope
from tender_radar.export.static_site import export_site
from tender_radar.models import BookletAnswer, BookletBrief
from tender_radar.repository import first_profile, save_answer, save_brief

TODAY = date(2026, 11, 15)
ARABIC = re.compile(r"[؀-ۿ]")
LATIN_WORD = re.compile(r"[A-Za-z]+")
# Latin words allowed on Arabic pages: names of standards, formats and products.
AR_ALLOWED = {"PDF", "ISO", "iOS", "Android", "ERP"}


def run_export(settings, out_dir, with_sample=True):
    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        if with_sample:
            brief_id = save_brief(s, "sample_booklet.pdf", BookletBrief(scope="نطاق تجريبي"))
            save_answer(s, brief_id, "What is the penalty?", BookletAnswer(answer="1% a week", citations=[4]), lang="en")
            save_answer(s, brief_id, "ما الغرامة؟", BookletAnswer(answer="1% أسبوعيًا", citations=[4]), lang="ar")
        written = export_site(s, [first_profile(s)], TODAY, out_dir)
    engine.dispose()
    return written


def pages(out_dir) -> dict[Path, str]:
    return {p: p.read_text(encoding="utf-8") for p in out_dir.rglob("*.html")}


class _Visible(HTMLParser):
    """Collects visible text, skipping <head>, <script>, form values and any element
    marked with a language other than the page's (the "Arabic original" exception)."""

    def __init__(self, page_lang: str):
        super().__init__()
        self.page_lang, self.skip, self.text = page_lang, [], []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("meta", "link", "input", "br", "img", "circle", "line", "path", "stop"):
            return
        hidden = tag in ("head", "script", "style", "textarea", "option") or (a.get("lang") and a["lang"] != self.page_lang)
        self.stack.append(hidden)

    def handle_endtag(self, tag):
        if tag in ("meta", "link", "input", "br", "img", "circle", "line", "path", "stop"):
            return
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if not any(self.stack[1:]):  # stack[0] is <html lang=…> itself
            self.text.append(data)


def visible_text(html: str, lang: str) -> str:
    parser = _Visible(lang)
    parser.feed(html)
    return " ".join(parser.text)


def test_export_writes_both_language_trees(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    for lang in ("en", "ar"):
        assert (out / lang / "index.html").exists()
        assert len(list((out / lang / "c" / "najd-digital" / "tenders").glob("*.html"))) == 9
        assert (out / lang / "c" / "najd-digital" / "tenders" / "000000001004.html").exists()
        assert (out / lang / "briefs" / "sample.html").exists()
    assert (out / "static" / "app.js").exists() and (out / "static" / "app.css").exists()
    assert "Scores precomputed on 15 Nov 2026" in (out / "en" / "c" / "najd-digital" / "index.html").read_text(encoding="utf-8")


def test_root_index_sends_visitors_to_english(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    root = (out / "index.html").read_text(encoding="utf-8")
    assert 'url=en/index.html' in root and 'href="en/index.html"' in root


def test_every_relative_link_points_to_an_exported_file(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    for path, html in pages(out).items():
        for link in re.findall(r'(?:href|src)="([^"#]+)', html):
            if link.startswith(("http://", "https://", "mailto:")) or link.startswith("url="):
                continue
            assert not link.startswith("/"), (path, link)
            assert (path.parent / link).resolve().exists(), (path.relative_to(out), link)


def test_language_switch_keeps_the_same_page(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    detail = (out / "en" / "c" / "najd-digital" / "tenders" / "000000001004.html").read_text(encoding="utf-8")
    assert 'href="../../../../ar/c/najd-digital/tenders/000000001004.html"' in detail


def test_one_language_per_exported_page(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    for path, html in pages(out).items():
        rel = path.relative_to(out).parts
        if rel[0] not in ("en", "ar"):
            continue
        text = visible_text(html, rel[0])
        if rel[0] == "en":
            assert not ARABIC.search(text), (path.relative_to(out), ARABIC.findall(text)[:5])
        else:
            stray = set(LATIN_WORD.findall(text)) - AR_ALLOWED
            assert not stray, (path.relative_to(out), stray)


def test_exported_sample_brief_shows_only_its_language_questions(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    en = (out / "en" / "briefs" / "sample.html").read_text(encoding="utf-8")
    ar = (out / "ar" / "briefs" / "sample.html").read_text(encoding="utf-8")
    assert "What is the penalty?" in en and "ما الغرامة؟" not in en
    assert "ما الغرامة؟" in ar and "What is the penalty?" not in ar


def test_export_without_sample_brief_has_no_brief_link(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out, with_sample=False)
    assert not (out / "en" / "briefs").exists()
    assert "briefs/sample.html" not in (out / "en" / "c" / "najd-digital" / "index.html").read_text(encoding="utf-8")


def test_export_has_no_upload_or_profile_forms(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    for html in pages(out).values():
        assert "<form" not in html
        assert "/profile" not in html


def test_imported_tenders_never_reach_the_public_export(db_settings, tmp_path):
    """Real Etimad data is private: the read-only demo shows seed tenders only."""
    from tender_radar.ai.provider import FakeProvider
    from tender_radar.matching.scorer import run_matching
    from tender_radar.repository import list_tenders, upsert_tenders

    engine = make_engine(db_settings.database_url)
    with session_scope(engine) as s:
        real = list_tenders(s)[0].model_copy(update={
            "reference": "999000000777", "title": "منافسة حقيقية سرية", "title_en": "Secret real tender",
            "source": "etimad-import",
        })
        upsert_tenders(s, [real])
        run_matching(s, first_profile(s), FakeProvider(), TODAY)
    engine.dispose()
    out = tmp_path / "site"
    run_export(db_settings, out)
    for html in pages(out).values():
        assert "999000000777" not in html
        assert "منافسة حقيقية سرية" not in html and "Secret real tender" not in html


def test_read_only_app_hides_imported_tender(db_settings):
    from fastapi.testclient import TestClient

    from tender_radar.repository import list_tenders, upsert_tenders
    from tender_radar.web.app import create_app

    engine = make_engine(db_settings.database_url)
    with session_scope(engine) as s:
        real = list_tenders(s)[0].model_copy(update={"reference": "999000000778", "source": "etimad-import"})
        upsert_tenders(s, [real])
    engine.dispose()
    url = "/en/c/najd-digital/tenders/999000000778"
    assert TestClient(create_app(db_settings, today=TODAY, read_only=True)).get(url).status_code == 404
    assert TestClient(create_app(db_settings, today=TODAY)).get(url).status_code == 200


def test_export_has_add_company_preview(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    for lang in ("en", "ar"):
        page = out / lang / "companies" / "new.html"
        assert page.exists()
        html = page.read_text(encoding="utf-8")
        assert "disabled" in html and "<form" not in html
        assert f'href="../{lang}/companies/new.html"' in (out / lang / "index.html").read_text(encoding="utf-8")
    assert "runs locally" in (out / "en" / "companies" / "new.html").read_text(encoding="utf-8")


def test_no_page_claims_open_source(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    for html in pages(out).values():
        assert "Open source" not in html and "مفتوح المصدر" not in html


def test_export_writes_calendar_files(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    ics = (out / "en" / "calendar" / "000000001004.ics").read_bytes()
    assert ics.startswith(b"BEGIN:VCALENDAR\r\n") and b"\r\r\n" not in ics
    assert b"DTSTART:20270105T100000Z" in ics
    assert not (out / "en" / "calendar" / "000000001006.ics").exists()  # no deadline, no calendar
    page = (out / "en" / "c" / "najd-digital" / "tenders" / "000000001004.html").read_text(encoding="utf-8")
    assert 'href="../../../../en/calendar/000000001004.ics"' in page


def test_export_has_how_page(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    for lang in ("en", "ar"):
        assert (out / lang / "how.html").exists()
    assert 'href="../en/how.html"' in (out / "en" / "index.html").read_text(encoding="utf-8")
