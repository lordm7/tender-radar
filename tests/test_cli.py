from tender_radar.__main__ import main
from tender_radar.db import make_engine, session_scope
from tender_radar.repository import list_matches


def test_seed_then_match_with_fake(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'cli.db').as_posix()}"
    monkeypatch.setenv("TR_DATABASE_URL", url)
    monkeypatch.setenv("TR_AI_PROVIDER", "fake")
    assert main(["seed"]) == 0
    assert main(["match", "--today", "2026-11-15"]) == 0
    with session_scope(make_engine(url)) as s:
        assert len(list_matches(s, "najd-digital")) == 30


def test_brief_command_saves_brief(tmp_path, monkeypatch, capsys):
    import pymupdf

    from tender_radar.repository import latest_brief

    url = f"sqlite:///{(tmp_path / 'cli.db').as_posix()}"
    monkeypatch.setenv("TR_DATABASE_URL", url)
    monkeypatch.setenv("TR_AI_PROVIDER", "fake")
    pdf = tmp_path / "booklet.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(40, 40, 555, 800), "Scope of work for a digital platform. " * 20)
    doc.save(pdf)
    assert main(["seed"]) == 0
    assert main(["brief", str(pdf)]) == 0
    with session_scope(make_engine(url)) as s:
        assert latest_brief(s, "booklet.pdf") is not None


def test_brief_command_unreadable_pdf_returns_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATABASE_URL", f"sqlite:///{(tmp_path / 'cli.db').as_posix()}")
    monkeypatch.setenv("TR_AI_PROVIDER", "fake")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"nope")
    assert main(["seed"]) == 0
    assert main(["brief", str(bad)]) == 1
    assert "could not be opened" in capsys.readouterr().out


def test_export_command_writes_site(tmp_path, monkeypatch):
    monkeypatch.setenv("TR_DATABASE_URL", f"sqlite:///{(tmp_path / 'cli.db').as_posix()}")
    monkeypatch.setenv("TR_AI_PROVIDER", "fake")
    out = tmp_path / "site"
    assert main(["seed"]) == 0
    assert main(["match", "--today", "2026-11-15"]) == 0
    assert main(["export", "--out", str(out), "--today", "2026-11-15"]) == 0
    assert (out / "index.html").exists()


def test_brief_command_ai_failure_returns_1(tmp_path, monkeypatch, capsys):
    import pymupdf

    import tender_radar.__main__ as cli
    from tender_radar.ai.provider import AIError, FakeProvider

    monkeypatch.setenv("TR_DATABASE_URL", f"sqlite:///{(tmp_path / 'cli.db').as_posix()}")
    monkeypatch.setattr(cli, "get_provider", lambda settings: FakeProvider([AIError("503 UNAVAILABLE")]))
    pdf = tmp_path / "booklet.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(40, 40, 555, 800), "Scope of work for a digital platform. " * 20)
    doc.save(pdf)
    assert main(["seed"]) == 0
    assert main(["brief", str(pdf)]) == 1
    assert "AI could not read this booklet" in capsys.readouterr().out


def test_import_command_reads_copied_text_and_saved_html(tmp_path, monkeypatch, capsys):
    from pathlib import Path

    from tender_radar.repository import get_tender

    fixture = Path(__file__).parent / "fixtures" / "etimad_copy.txt"
    url = f"sqlite:///{(tmp_path / 'cli.db').as_posix()}"
    monkeypatch.setenv("TR_DATABASE_URL", url)
    assert main(["seed"]) == 0
    assert main(["import", str(fixture)]) == 0
    out = capsys.readouterr().out
    assert "3 new" in out and "1 skipped" in out and "no reference number" in out
    html = tmp_path / "saved.html"
    html.write_text("<div>" + fixture.read_text(encoding="utf-8").replace("\n", "</div><div>") + "</div>", encoding="utf-8")
    assert main(["import", str(html)]) == 0
    assert "3 unchanged" in capsys.readouterr().out
    with session_scope(make_engine(url)) as s:
        assert get_tender(s, "999000000001").source == "etimad-import"


def test_import_missing_file_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATABASE_URL", f"sqlite:///{(tmp_path / 'cli.db').as_posix()}")
    assert main(["import", str(tmp_path / "nope.txt")]) == 1
    assert "not found" in capsys.readouterr().out
