from tender_radar.settings import load_env_file


def test_env_file_fills_missing_values_only(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\n\nGEMINI_API_KEY=abc123\nTR_GEMINI_MODEL = some-model \nTR_AI_PROVIDER=gemini\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("TR_GEMINI_MODEL", raising=False)
    monkeypatch.setenv("TR_AI_PROVIDER", "fake")
    load_env_file(env)
    import os
    assert os.environ["GEMINI_API_KEY"] == "abc123"
    assert os.environ["TR_GEMINI_MODEL"] == "some-model"
    assert os.environ["TR_AI_PROVIDER"] == "fake"  # real environment wins over the file


def test_missing_env_file_is_fine(tmp_path):
    load_env_file(tmp_path / "nope.env")
