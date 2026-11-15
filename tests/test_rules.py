from datetime import date

from tender_radar.arabic import normalize
from tender_radar.matching.rules import prefilter
from tender_radar.models import Tender

TODAY = date(2026, 11, 15)


def make_tender(**overrides) -> Tender:
    base = dict(
        reference="T-1", title="تطوير برمجيات", agency="جهة", tender_type="منافسة عامة",
        activity="غير محدد", region="الرياض", deadline=date(2026, 12, 1),
        estimated_value_sar=1_000_000,
    )
    base.update(overrides)
    return Tender(**base)


def test_normalize_variants():
    assert normalize("الأمن السيبرانيّ") == normalize("الامن السيبراني")
    assert normalize("مشروع ٢٠٢٦") == "مشروع 2026"


def test_keyword_match_across_hamza_variants(profile):
    p = profile.model_copy(update={"keywords": ["أمن سيبراني"], "activities": []})
    result = prefilter(make_tender(title="خدمات امن سيبراني"), p, TODAY)
    assert result.passed


def test_past_deadline_filtered(profile):
    result = prefilter(make_tender(deadline=date(2026, 11, 14)), profile, TODAY)
    assert not result.passed
    assert result.reasons == ["deadline passed"]


def test_missing_deadline_passes(profile):
    assert prefilter(make_tender(deadline=None), profile, TODAY).passed


def test_excluded_agency(profile):
    result = prefilter(make_tender(agency="هيئة الموارد الإقليمية"), profile, TODAY)
    assert result.reasons == ["excluded agency"]


def test_value_out_of_range(profile):
    result = prefilter(make_tender(estimated_value_sar=45_000_000), profile, TODAY)
    assert result.reasons == ["value outside range"]


def test_non_it_tender_filtered(profile):
    result = prefilter(make_tender(title="أعمال النظافة العامة", activity="التشغيل والصيانة والنظافة"), profile, TODAY)
    assert result.reasons == ["no keyword match"]


def test_seed_data_split(profile, seed_tenders):
    passed = [t for t in seed_tenders if prefilter(t, profile, TODAY).passed]
    assert 8 <= len(passed) <= 14
