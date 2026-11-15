"""The daily email digest: built from stored matches, sent only when SMTP is set up.

A fake sender records messages instead of sending them; no test touches a real
mail server.
"""

from datetime import date

from tender_radar.__main__ import main
from tender_radar.db import make_engine, session_scope
from tender_radar.digest import build_digest, send_digest
from tender_radar.repository import first_profile
from tender_radar.settings import Settings

TODAY = date(2026, 11, 15)


def digest_for(settings, today=TODAY, top_n=10):
    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        digest = build_digest(s, first_profile(s), today, top_n=top_n)
    engine.dispose()
    return digest


def smtp_settings(base: Settings) -> Settings:
    return Settings(
        database_url=base.database_url, ai_provider="fake", smtp_host="smtp.example.invalid", smtp_port=587,
        smtp_user="me@example.invalid", smtp_password="app-password", digest_to="me@example.invalid",
    )


def test_digest_lists_best_matches_first(db_settings):
    digest = digest_for(db_settings)
    assert digest.count == 8  # conftest SCORES: 8 of the 9 open matches score >= 50 (one scores 40)
    assert "Najd Digital Solutions (synthetic)" in digest.subject
    assert "منافسة" in digest.subject  # Arabic subject line
    best = "حل ذكاء اصطناعي لتحليل بلاغات المواطنين وتصنيفها"  # 1004, score 95
    assert best in digest.html and best in digest.text
    assert digest.text.index("95") < digest.text.index("82")


def test_digest_respects_top_n(db_settings):
    assert digest_for(db_settings, top_n=3).count == 3


def test_digest_skips_closed_tenders(db_settings):
    later = digest_for(db_settings, today=date(2026, 12, 3))  # 1002 (75) closed on 12-01
    assert "000000001002" not in later.text


def test_empty_digest(db_settings):
    assert digest_for(db_settings, today=date(2028, 1, 1)).count == 0


def test_send_uses_the_configured_address(db_settings):
    sent = []
    ok = send_digest(digest_for(db_settings), smtp_settings(db_settings), sender=lambda msg, s: sent.append(msg))
    assert ok is True
    msg = sent[0]
    assert msg["To"] == "me@example.invalid"
    assert "Najd Digital" in msg["Subject"]
    assert msg.get_body(("html",)) is not None and msg.get_body(("plain",)) is not None


def test_send_without_smtp_does_nothing(db_settings):
    sent = []
    assert send_digest(digest_for(db_settings), db_settings, sender=lambda msg, s: sent.append(msg)) is False
    assert sent == []


def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TR_DATABASE_URL", f"sqlite:///{(tmp_path / 'cli.db').as_posix()}")
    assert main(["seed"]) == 0
    assert main(["match", "--today", "2026-11-15"]) == 0


def test_cli_without_smtp_saves_a_preview(tmp_path, monkeypatch, capsys):
    cli_env(tmp_path, monkeypatch)
    out = tmp_path / "digests"
    assert main(["digest", "--today", "2026-11-15", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "not sent (SMTP not configured)" in printed
    assert (out / "najd-digital.html").exists()


def test_cli_nothing_to_send(tmp_path, monkeypatch, capsys):
    cli_env(tmp_path, monkeypatch)
    assert main(["digest", "--today", "2028-01-01", "--out", str(tmp_path / "d")]) == 0
    assert "nothing new" in capsys.readouterr().out


def test_cli_sends_when_configured(tmp_path, monkeypatch, capsys):
    import tender_radar.digest as digest_module

    cli_env(tmp_path, monkeypatch)
    for name, value in [("TR_SMTP_HOST", "smtp.example.invalid"), ("TR_SMTP_USER", "me@example.invalid"),
                        ("TR_SMTP_PASSWORD", "x"), ("TR_DIGEST_TO", "me@example.invalid")]:
        monkeypatch.setenv(name, value)
    sent = []
    monkeypatch.setattr(digest_module, "smtp_send", lambda msg, s: sent.append(msg))
    assert main(["digest", "--today", "2026-11-15", "--profile", "najd-digital", "--out", str(tmp_path / "d")]) == 0
    assert len(sent) == 1
    assert "sent to me@example.invalid" in capsys.readouterr().out
    assert main(["digest", "--dry-run", "--today", "2026-11-15", "--out", str(tmp_path / "d")]) == 0
    assert len(sent) == 1  # dry run never sends
