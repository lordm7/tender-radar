from datetime import date, datetime, timezone

from tender_radar.calendar_ics import tender_ics
from tender_radar.models import Tender

STAMP = datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc)


def make(**kw) -> Tender:
    base = dict(
        reference="000000001004", title="حل ذكاء اصطناعي لتحليل البلاغات", agency="أمانة", tender_type="منافسة محدودة",
        activity="تقنية المعلومات", deadline=date(2027, 1, 5), deadline_time="13:00",
        inquiry_deadline=date(2026, 12, 26), title_en="AI solution, phase 1; reports",
    )
    base.update(kw)
    return Tender(**base)


def unfolded(ics: str) -> str:
    return ics.replace("\r\n ", "")


def test_deadline_with_time_is_converted_from_riyadh_to_utc():
    ics = tender_ics(make(), "en", STAMP)
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20270105T100000Z" in ics  # 13:00 Riyadh = 10:00 UTC
    assert "UID:000000001004-deadline@tender-radar" in ics


def test_inquiry_deadline_is_an_all_day_event():
    ics = tender_ics(make(), "en", STAMP)
    assert "DTSTART;VALUE=DATE:20261226" in ics
    assert ics.count("BEGIN:VEVENT") == 2


def test_summary_uses_page_language_and_escapes_text():
    en = unfolded(tender_ics(make(), "en", STAMP))
    assert "SUMMARY:Bid deadline: AI solution\\, phase 1\\; reports" in en
    ar = unfolded(tender_ics(make(), "ar", STAMP))
    assert "SUMMARY:آخر موعد لتقديم العروض: حل ذكاء اصطناعي لتحليل البلاغات" in ar


def test_deadline_without_time_is_all_day_and_no_inquiry_event():
    ics = tender_ics(make(deadline_time=None, inquiry_deadline=None), "en", STAMP)
    assert "DTSTART;VALUE=DATE:20270105" in ics and "DTEND;VALUE=DATE:20270106" in ics
    assert ics.count("BEGIN:VEVENT") == 1


def test_long_lines_are_folded_to_75_bytes():
    ics = tender_ics(make(title="منافسة " * 30), "ar", STAMP)
    assert all(len(line.encode("utf-8")) <= 75 for line in ics.split("\r\n"))
