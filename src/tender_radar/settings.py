"""App settings, read from environment variables.

Keeping secrets (like the AI API key) in the environment means they never get
committed to git. Defaults are safe: a local SQLite file and the free "fake" AI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: _env("TR_DATABASE_URL", "sqlite:///tender_radar.db"))
    ai_provider: str = field(default_factory=lambda: _env("TR_AI_PROVIDER", "fake"))
    gemini_model: str | None = field(default_factory=lambda: _env("TR_GEMINI_MODEL"))
    gemini_api_key: str | None = field(default_factory=lambda: _env("GEMINI_API_KEY"))
