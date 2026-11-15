from pathlib import Path

import pytest
from pydantic import ValidationError

from tender_radar.models import AIScore, load_profile, load_seed_tenders

SEED = Path(__file__).resolve().parents[1] / "data" / "seed"


def test_seed_tenders_load():
    tenders = load_seed_tenders(SEED / "tenders.json")
    assert len(tenders) >= 30
    refs = [t.reference for t in tenders]
    assert len(refs) == len(set(refs))


def test_profile_version_changes_when_keywords_change():
    p = load_profile(SEED / "profile_it_services.json")
    p2 = p.model_copy(update={"keywords": p.keywords + ["x"]})
    assert p2.version != p.version


def test_profile_version_ignores_name():
    p = load_profile(SEED / "profile_it_services.json")
    p2 = p.model_copy(update={"name": "Another name"})
    assert p2.version == p.version


def test_ai_score_rejects_out_of_range():
    with pytest.raises(ValidationError):
        AIScore(score=101, reasons_en=["x"], reasons_ar=["س"])
