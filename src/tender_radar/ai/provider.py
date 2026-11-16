"""The AI provider interface, a fake for tests, and the factory.

Every AI call in the app goes through `generate_json(prompt, schema)`: send a
prompt and get back a validated Pydantic object. Like a Java interface, this
lets us swap Gemini for another provider, or for FakeProvider in tests, without
touching the matching or reader code. Tests never spend money or need a key.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol, TypeVar

from pydantic import BaseModel

from tender_radar.models import AIScore, BookletAnswer, BookletBrief, BriefText, ChecklistItem
from tender_radar.settings import Settings

T = TypeVar("T", bound=BaseModel)


class AIError(Exception):
    """The AI call failed or returned something unusable."""


class RateLimited(AIError):
    """The provider said 'too many requests' (HTTP 429); worth retrying later."""


R = TypeVar("R")
_sleep: Callable[[float], None] = time.sleep  # tests replace this so they never wait


def call_with_retry(
    fn: Callable[[], R], retries: int = 2, wait: float = 20, sleep: Callable[[float], None] | None = None
) -> R:
    """Run one AI call; on a rate limit (429) or outage (503, bad answer) wait and try again.

    The free tier allows about 15 calls a minute, so waits grow 20s, 40s, …
    After the last retry the error is raised for the caller to report.
    """
    for attempt in range(retries + 1):
        try:
            return fn()
        except AIError:
            if attempt == retries:
                raise
            (sleep or _sleep)(wait * (2**attempt))
    raise AssertionError("unreachable")


class LLMProvider(Protocol):
    def generate_json(self, prompt: str, schema: type[T]) -> T: ...


_DEFAULTS: dict[type[BaseModel], BaseModel] = {
    AIScore: AIScore(score=70, reasons_en=["fake"], reasons_ar=["تجريبي"]),
    BookletBrief: BookletBrief(
        scope="ملخص تجريبي",
        go_no_go=[ChecklistItem(item="ISO 27001", status="meets", note="تجريبي")],
        en=BriefText(scope="Fake summary", go_no_go=[ChecklistItem(item="ISO 27001", status="meets", note="fake")]),
    ),
    BookletAnswer: BookletAnswer(answer="إجابة تجريبية", citations=[1], found=True),
}


class FakeProvider:
    """Test double: returns queued answers, then a fixed default per schema.

    A queued Exception is raised instead of returned, to simulate failures.
    """

    def __init__(self, responses: list[dict | Exception] | None = None):
        self._responses = list(responses or [])
        self.calls: list[str] = []

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        self.calls.append(prompt)
        if self._responses:
            item = self._responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return schema.model_validate(item)
        if schema not in _DEFAULTS:
            raise AIError(f"FakeProvider has no default for {schema.__name__}")
        return _DEFAULTS[schema].model_copy(deep=True)


def get_provider(settings: Settings) -> LLMProvider:
    """Build the provider named in settings ("fake" or "gemini")."""
    if settings.ai_provider == "fake":
        return FakeProvider()
    if settings.ai_provider == "gemini":
        from tender_radar.ai.gemini import GeminiProvider

        if not settings.gemini_api_key or not settings.gemini_model:
            raise ValueError("Set GEMINI_API_KEY and TR_GEMINI_MODEL to use the Gemini provider")
        return GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)
    raise ValueError(f"Unknown AI provider: {settings.ai_provider!r}")
