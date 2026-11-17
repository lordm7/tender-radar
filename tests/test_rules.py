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


def test_normalize_wider_variants():
    assert normalize("مدرسة") == normalize("مدرسه")
    assert normalize("مستشفى") == normalize("مستشفي")
    assert normalize("ٱلرياض") == normalize("الرياض")
    assert normalize("سنة ۲۰۲۶") == "سنه 2026"  # Persian digits
    assert normalize("ﻻ") == normalize("لا")  # presentation form via NFKC
    assert normalize("الأمن") == normalize("الأمن")  # decomposed hamza


def test_latin_keyword_matches_whole_words_only(profile):
    p = profile.model_copy(update={"keywords": ["AI"], "activities": []})
    assert not prefilter(make_tender(title="building maintenance"), p, TODAY).passed
    assert prefilter(make_tender(title="AI platform"), p, TODAY).passed


def test_region_inferred_from_agency(profile):
    p = profile.model_copy(update={"regions": ["الرياض"]})
    far = make_tender(region=None, agency="أمانة منطقة عسير")
    near = make_tender(region=None, agency="فرع الوزارة بمنطقة الرياض")
    assert prefilter(far, p, TODAY).reasons == ["region not covered"]
    assert prefilter(near, p, TODAY).passed


def test_no_region_anywhere_passes(profile):
    p = profile.model_copy(update={"regions": ["الرياض"]})
    assert prefilter(make_tender(region=None, agency="وزارة الخدمات الرقمية"), p, TODAY).passed


# --- check_rules: every rule's result, for the tender page's "Profile check" ---

from tender_radar.matching.rules import check_rules  # noqa: E402


def by_name(checks):
    return {c.name: c for c in checks}


def test_check_rules_reports_every_rule_when_all_pass(profile):
    checks = by_name(check_rules(make_tender(title="تطوير برمجيات سحابية"), profile, TODAY))
    assert list(checks) == ["agency", "deadline", "value", "region", "keywords"]
    assert all(c.passed for c in checks.values())
    assert checks["value"].detail == {"value": 1_000_000, "min": 200_000, "max": 20_000_000}
    assert checks["region"].detail == {"region": "الرياض"}
    assert "برمجيات" in checks["keywords"].detail["terms"]


def test_check_rules_keeps_going_after_a_failure(profile):
    checks = by_name(check_rules(make_tender(region="جازان", estimated_value_sar=50), profile, TODAY))
    assert checks["value"].passed is False and checks["value"].reason == "value outside range"
    assert checks["region"].passed is False and checks["region"].reason == "region not covered"
    assert checks["keywords"].passed is True  # still evaluated


def test_check_rules_unknown_when_tender_lacks_data(profile):
    t = make_tender(deadline=None, estimated_value_sar=None, region=None, agency="جهة")
    checks = by_name(check_rules(t, profile, TODAY))
    assert checks["deadline"].passed is None
    assert checks["value"].passed is None
    assert checks["region"].passed is None


def test_prefilter_agrees_with_first_failed_check(profile):
    t = make_tender(region="جازان", estimated_value_sar=50)
    assert prefilter(t, profile, TODAY).reasons == ["value outside range"]
