"""The daily pipeline: fresh demo dates → match → sample brief → export (→ digest).

It must always produce the public demo, even when the AI is down or not set up.
"""

import tender_radar.__main__ as cli
from tender_radar.ai.provider import AIError
from tender_radar.__main__ import main


class AIDown:
    """A provider that fails every call, like Gemini during an outage."""

    calls = 0

    def generate_json(self, prompt, schema):
        AIDown.calls += 1
        raise AIError("503 UNAVAILABLE")


def use_db(tmp_path, monkeypatch):
    monkeypatch.setenv("TR_DATABASE_URL", f"sqlite:///{(tmp_path / 'daily.db').as_posix()}")


def test_daily_builds_the_whole_demo_with_the_fake_ai(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    out = tmp_path / "site"
    assert main(["daily", "--out", str(out), "--today", "2026-11-20"]) == 0
    assert (out / "index.html").exists()
    assert (out / "c" / "najd-digital" / "index.html").exists()
    assert (out / "c" / "al-bunyan" / "index.html").exists()
    assert (out / "briefs" / "sample.html").exists()
    assert "scores precomputed on 2026-11-20" in (out / "c" / "najd-digital" / "index.html").read_text(encoding="utf-8")


def test_daily_still_publishes_when_the_ai_is_down(tmp_path, monkeypatch, capsys):
    use_db(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "get_provider", lambda settings: AIDown())
    out = tmp_path / "site"
    assert main(["daily", "--out", str(out), "--today", "2026-11-20"]) == 0
    dashboard = (out / "c" / "najd-digital" / "index.html").read_text(encoding="utf-8")
    assert "not<br>scored" in dashboard
    assert not (out / "briefs" / "sample.html").exists()
    assert "brief step failed" in capsys.readouterr().out


def test_daily_without_ai_settings_still_publishes(tmp_path, monkeypatch, capsys):
    use_db(tmp_path, monkeypatch)
    monkeypatch.setenv("TR_AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    out = tmp_path / "site"
    assert main(["daily", "--out", str(out), "--today", "2026-11-20"]) == 0
    assert (out / "index.html").exists()
    assert "match step failed" in capsys.readouterr().out


def test_daily_fails_if_the_export_cannot_be_written(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    foreign = tmp_path / "not-ours"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("x", encoding="utf-8")
    assert main(["daily", "--out", str(foreign), "--today", "2026-11-20"]) == 1


def test_daily_checks_the_it_sample_booklet_against_the_it_company(tmp_path, monkeypatch):
    from tender_radar.ai.provider import FakeProvider

    use_db(tmp_path, monkeypatch)
    fake = FakeProvider()
    monkeypatch.setattr(cli, "get_provider", lambda settings: fake)
    assert main(["daily", "--out", str(tmp_path / "site"), "--today", "2026-11-20"]) == 0
    brief_prompt = fake.calls[-1]
    assert "Najd Digital Solutions" in brief_prompt
    assert "Al-Bunyan" not in brief_prompt


def test_daily_reports_its_status_for_the_deploy_gate(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    status = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(status))
    assert main(["daily", "--out", str(tmp_path / "site"), "--today", "2026-11-20"]) == 0
    lines = status.read_text(encoding="utf-8").splitlines()
    scored = int(next(l for l in lines if l.startswith("scored_total=")).split("=")[1])
    assert scored > 0


def test_daily_status_shows_zero_when_the_ai_is_down(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    status = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(status))
    monkeypatch.setattr(cli, "get_provider", lambda settings: AIDown())
    assert main(["daily", "--out", str(tmp_path / "site"), "--today", "2026-11-20"]) == 0
    assert "scored_total=0" in status.read_text(encoding="utf-8").splitlines()
