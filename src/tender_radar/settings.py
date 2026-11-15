"""App settings, read from environment variables (and an optional .env file).

Keeping secrets (like the AI API key) in the environment means they never get
committed to git. Defaults are safe: a local SQLite file and the free "fake" AI.
A `.env` file in the project root (git-ignored) is read at startup; values
already set in the real environment always win over the file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env_file(path: Path) -> None:
    """Read KEY=value lines into os.environ, without overriding existing values."""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file(PROJECT_ROOT / ".env")


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or default


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: _env("TR_DATABASE_URL", "sqlite:///tender_radar.db"))
    ai_provider: str = field(default_factory=lambda: _env("TR_AI_PROVIDER", "fake"))
    gemini_model: str | None = field(default_factory=lambda: _env("TR_GEMINI_MODEL"))
    gemini_api_key: str | None = field(default_factory=lambda: _env("GEMINI_API_KEY"))
