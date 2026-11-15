"""Shared test fixtures: a fresh in-memory database and the seed data."""

from datetime import date
from pathlib import Path

import pytest

from tender_radar.ai.provider import FakeProvider
from tender_radar.db import init_db, make_engine, session_scope
from tender_radar.matching.scorer import run_matching
from tender_radar.repository import save_profile, upsert_tenders
from tender_radar.settings import Settings
from tender_radar.models import load_profile, load_seed_tenders

SEED = Path(__file__).resolve().parents[1] / "data" / "seed"


@pytest.fixture
def engine():
    eng = make_engine("sqlite://")
    init_db(eng)
    return eng


@pytest.fixture
def seed_tenders():
    return load_seed_tenders(SEED / "tenders.json")


@pytest.fixture
def profile():
    return load_profile(SEED / "profile_it_services.json")


# Scores for the 9 tenders that pass the rule filter, in reference order:
# 1001, 1002, 1003, 1004, 1005, 1006, 1007, 1009, 1014 -> 1004 is the best fit.
SCORES = [60, 75, 82, 95, 50, 40, 66, 71, 58]


@pytest.fixture
def db_settings(tmp_path, seed_tenders, profile):
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'web.db').as_posix()}", ai_provider="fake")
    engine = make_engine(settings.database_url)
    init_db(engine)
    fake = FakeProvider([{"score": s, "reasons_en": [f"reason {s}"], "reasons_ar": [f"سبب {s}"]} for s in SCORES])
    with session_scope(engine) as s:
        upsert_tenders(s, seed_tenders)
        save_profile(s, profile)
        run_matching(s, profile, fake, date(2026, 11, 15))
    engine.dispose()
    return settings
