"""UI translations: both languages complete, Arabic strings really Arabic."""

import re
from datetime import date

import pytest

from tender_radar.web import i18n

LATIN_WORD = re.compile(r"[A-Za-z]+")
# Latin tokens that legitimately appear on Arabic pages (product and standard names).
AR_ALLOWED = {"EN", "PDF", "ISO", "GitHub", "LinkedIn", "Mohammed", "Alzalam"}


def test_both_languages_have_the_same_keys():
    assert set(i18n.STRINGS["en"]) == set(i18n.STRINGS["ar"])


def test_arabic_strings_have_no_stray_latin_words():
    for key, value in i18n.STRINGS["ar"].items():
        words = set(LATIN_WORD.findall(re.sub(r"\{[a-z_]+\}", "", value)))
        assert words <= AR_ALLOWED, (key, words - AR_ALLOWED)


def test_english_strings_have_no_arabic():
    for key, value in i18n.STRINGS["en"].items():
        assert not re.search(r"[؀-ۿ]", value), key


def test_t_formats_and_fails_loudly_on_unknown_keys():
    assert i18n.t("en", "matches") == "Matches"
    assert i18n.t("ar", "matches") == "المطابقات"
    with pytest.raises(KeyError):
        i18n.t("en", "no-such-key")


def test_other_language():
    assert i18n.other("en") == "ar" and i18n.other("ar") == "en"


def test_vocab_translates_known_terms_and_flags_unknown_ones():
    assert i18n.vocab("en", "تقنية المعلومات") == ("Information technology", False)
    assert i18n.vocab("en", "منطقة مكة المكرمة") == ("Makkah Region", False)
    assert i18n.vocab("en", "منافسة عامة") == ("Public tender", False)
    assert i18n.vocab("en", "نشاط غير معروف") == ("نشاط غير معروف", True)
    assert i18n.vocab("ar", "تقنية المعلومات") == ("تقنية المعلومات", False)
    assert i18n.vocab("en", "ISO 27001") == ("ISO 27001", False)


def test_days_label():
    assert i18n.days_label("en", None) == "No deadline stated"
    assert i18n.days_label("en", -1) == "Closed"
    assert i18n.days_label("en", 0) == "Closes today"
    assert i18n.days_label("en", 1) == "1 day left"
    assert i18n.days_label("en", 51) == "51 days left"
    assert i18n.days_label("ar", 2) == "يومان متبقيان"
    assert i18n.days_label("ar", 5) == "5 أيام متبقية"
    assert i18n.days_label("ar", 51) == "51 يومًا متبقيًا"


def test_dates_and_money():
    assert i18n.fmt_date("en", date(2027, 1, 5)) == "5 Jan 2027"
    assert i18n.fmt_date("ar", date(2027, 1, 5)) == "5 يناير 2027"
    assert i18n.fmt_date("en", None) == "—"
    assert i18n.fmt_sar("en", 3_500_000) == "3,500,000 SAR"
    assert i18n.fmt_sar("ar", 3_500_000) == "3,500,000 ريال"


def test_rule_reasons():
    assert i18n.rule_reason("ar", "deadline passed") == "انتهى موعد التقديم"
    assert i18n.rule_reason("en", "deadline passed") == "Deadline passed"
    assert i18n.rule_reason("en", "matched: cloud") == "Matched: cloud"
    assert i18n.rule_reason("ar", "matched: سحابية") == "تطابق: سحابية"
    assert i18n.rule_reason("en", "something new") == "something new"
