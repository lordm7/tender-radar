"""English text for tenders and companies, kept safely next to the Arabic.

English titles are written by hand (seed) or by the scoring call (imports).
They must never look like a content change, or every run would re-score.
"""

import re
from datetime import date
from pathlib import Path

from sqlalchemy import text

from tender_radar.db import init_db, make_engine, session_scope
from tender_radar.models import BookletAnswer, BookletBrief, Tender, load_profile, load_seed_tenders
from tender_radar.repository import (
    get_tender,
    list_answers,
    list_tenders,
    save_answer,
    save_brief,
    set_tender_english,
    tender_content_hash,
    upsert_tenders,
)

SEED = Path(__file__).resolve().parents[1] / "data" / "seed"
ARABIC = re.compile(r"[؀-ۿ]")


def tender(**kw) -> Tender:
    base = dict(reference="R1", title="تطوير منصة", agency="جهة", tender_type="منافسة عامة", activity="تقنية المعلومات")
    base.update(kw)
    return Tender(**base)


def test_english_fields_do_not_change_the_hash():
    plain = tender()
    english = tender(title_en="Platform development", agency_en="Agency", description_en="Build it")
    assert tender_content_hash(plain) == tender_content_hash(english)
    assert tender_content_hash(plain) != tender_content_hash(tender(title="عنوان آخر"))


def test_set_tender_english_only_fills_empty_fields(engine):
    with session_scope(engine) as s:
        upsert_tenders(s, [tender(agency_en="Hand-written agency")])
        set_tender_english(s, "R1", "AI title", "AI agency")
    with session_scope(engine) as s:
        t = get_tender(s, "R1")
    assert t.title_en == "AI title"
    assert t.agency_en == "Hand-written agency"  # never overwritten


def test_reimport_keeps_english_title(engine):
    with session_scope(engine) as s:
        upsert_tenders(s, [tender()])
        set_tender_english(s, "R1", "AI title", "AI agency")
    with session_scope(engine) as s:
        stats = upsert_tenders(s, [tender()])  # the same import again, without English
    assert stats.unchanged == 1
    with session_scope(engine) as s:
        assert get_tender(s, "R1").title_en == "AI title"


def test_init_db_adds_missing_columns_to_an_old_database(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with engine.begin() as conn:  # the tenders table as it was before the redesign
        conn.execute(text(
            "CREATE TABLE tenders (reference VARCHAR PRIMARY KEY, title TEXT, agency VARCHAR, tender_type VARCHAR, "
            "activity VARCHAR, region VARCHAR, published_on DATE, deadline DATE, inquiry_deadline DATE, "
            "deadline_time VARCHAR, booklet_price_sar FLOAT, source_url VARCHAR, estimated_value_sar FLOAT, "
            "description TEXT, source VARCHAR, content_hash VARCHAR, updated_at DATETIME)"
        ))
        conn.execute(text(
            "INSERT INTO tenders (reference, title, agency, tender_type, activity, description, source, content_hash) "
            "VALUES ('R1', 'عنوان', 'جهة', 'منافسة عامة', 'تقنية', '', 'seed', 'x')"
        ))
    init_db(engine)
    with session_scope(engine) as s:
        tenders = list_tenders(s)
    engine.dispose()
    assert [t.reference for t in tenders] == ["R1"]
    assert tenders[0].title_en is None


def test_every_seed_tender_and_profile_has_english_and_arabic_names():
    for t in load_seed_tenders(SEED / "tenders.json"):
        assert t.title_en and t.agency_en and t.description_en, t.reference
        for value in (t.title_en, t.agency_en, t.description_en):
            assert not ARABIC.search(value), (t.reference, value)
    for path in SEED.glob("profile_*.json"):
        profile = load_profile(path)
        assert profile.name_ar and ARABIC.search(profile.name_ar)


def test_answers_filtered_by_language(engine):
    with session_scope(engine) as s:
        brief_id = save_brief(s, "b.pdf", BookletBrief(scope="x"))
        save_answer(s, brief_id, "What is the penalty?", BookletAnswer(answer="1%"), lang="en")
        save_answer(s, brief_id, "ما الغرامة؟", BookletAnswer(answer="1%"), lang="ar")
    with session_scope(engine) as s:
        assert [q for q, _ in list_answers(s, brief_id, lang="en")] == ["What is the penalty?"]
        assert [q for q, _ in list_answers(s, brief_id, lang="ar")] == ["ما الغرامة؟"]
        assert len(list_answers(s, brief_id)) == 2
