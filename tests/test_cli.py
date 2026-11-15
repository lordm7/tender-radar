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
