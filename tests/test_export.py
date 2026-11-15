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
