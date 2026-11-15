"""Shared test fixtures: a fresh in-memory database and the seed data."""

from pathlib import Path

import pytest

from tender_radar.db import init_db, make_engine
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
