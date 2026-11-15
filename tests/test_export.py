from datetime import date

from tender_radar.db import make_engine, session_scope
from tender_radar.export.static_site import export_site
from tender_radar.models import BookletBrief
from tender_radar.repository import first_profile, save_brief

TODAY = date(2026, 11, 15)


def run_export(settings, out_dir, with_sample=True):
    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        if with_sample:
            save_brief(s, "sample_booklet.pdf", BookletBrief(scope="نطاق تجريبي"))
        written = export_site(s, first_profile(s), TODAY, out_dir)
    engine.dispose()
    return written


def all_html(out_dir) -> list[str]:
    return [p.read_text(encoding="utf-8") for p in out_dir.rglob("*.html")]


def test_export_writes_index_and_detail_pages(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    assert (out / "index.html").exists()
    assert len(list((out / "tenders").glob("*.html"))) == 9
    assert (out / "tenders" / "261139001004.html").exists()
    assert (out / "briefs" / "sample.html").exists()
    assert (out / "static" / "app.js").exists()
    assert "scores precomputed on 2026-11-15" in (out / "index.html").read_text(encoding="utf-8")


def test_export_without_sample_brief_has_no_brief_link(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out, with_sample=False)
    assert not (out / "briefs").exists()
    assert "briefs/sample.html" not in (out / "index.html").read_text(encoding="utf-8")


def test_exported_links_are_relative(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    for html in all_html(out):
        assert 'href="/' not in html
        assert 'src="/' not in html


def test_export_has_no_upload_or_profile_forms(db_settings, tmp_path):
    out = tmp_path / "site"
    run_export(db_settings, out)
    for html in all_html(out):
        assert "<form" not in html
        assert "/profile" not in html


def test_imported_tenders_never_reach_the_public_export(db_settings, tmp_path):
    """Real Etimad data is private: the read-only demo shows seed tenders only."""
    from tender_radar.repository import upsert_tenders

    engine = make_engine(db_settings.database_url)
    with session_scope(engine) as s:
        from tender_radar.ai.provider import FakeProvider
        from tender_radar.matching.scorer import run_matching
        from tender_radar.repository import list_tenders

        real = list_tenders(s)[0].model_copy(update={"reference": "999000000777", "title": "منافسة حقيقية سرية", "source": "etimad-import"})
        upsert_tenders(s, [real])
        run_matching(s, first_profile(s), FakeProvider(), TODAY)
    engine.dispose()
    out = tmp_path / "site"
    run_export(db_settings, out)
    for html in all_html(out):
        assert "999000000777" not in html
        assert "منافسة حقيقية سرية" not in html


def test_read_only_app_hides_imported_tender(db_settings):
    from fastapi.testclient import TestClient

    from tender_radar.repository import list_tenders, upsert_tenders
    from tender_radar.web.app import create_app

    engine = make_engine(db_settings.database_url)
    with session_scope(engine) as s:
        real = list_tenders(s)[0].model_copy(update={"reference": "999000000778", "source": "etimad-import"})
        upsert_tenders(s, [real])
    engine.dispose()
    assert TestClient(create_app(db_settings, today=TODAY, read_only=True)).get("/tenders/999000000778").status_code == 404
    assert TestClient(create_app(db_settings, today=TODAY)).get("/tenders/999000000778").status_code == 200
