import pytest

from tender_radar.ai.provider import AIError, FakeProvider, RateLimited, get_provider
from tender_radar.models import AIScore
from tender_radar.settings import Settings


def test_fake_returns_queued_then_default():
    fake = FakeProvider([{"score": 91, "reasons_en": ["a"], "reasons_ar": ["ا"]}])
    first = fake.generate_json("p1", AIScore)
    second = fake.generate_json("p2", AIScore)
    assert first.score == 91
    assert second == AIScore(score=70, reasons_en=["fake"], reasons_ar=["تجريبي"])
    assert fake.calls == ["p1", "p2"]


def test_fake_raises_queued_exception():
    fake = FakeProvider([RateLimited("slow down")])
    with pytest.raises(RateLimited):
        fake.generate_json("p", AIScore)
    assert issubclass(RateLimited, AIError)


def test_get_provider_unknown_raises():
    with pytest.raises(ValueError):
        get_provider(Settings(ai_provider="nope"))


def test_get_provider_fake_default():
    assert isinstance(get_provider(Settings(ai_provider="fake")), FakeProvider)


def test_gemini_client_has_timeout(monkeypatch):
    from google import genai

    from tender_radar.ai.gemini import REQUEST_TIMEOUT_MS, GeminiProvider

    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(genai, "Client", FakeClient)
    GeminiProvider(api_key="k", model="m")._get_client()
    assert captured["http_options"].timeout == REQUEST_TIMEOUT_MS == 60_000
