"""The Etimad importer reads text a person copied or saved from the public list.

The fixture is fictional (999… references, made-up agencies) but laid out
exactly like a Ctrl+A / Ctrl+C copy of the visitor tender list.
"""

from datetime import date
from html import escape
from pathlib import Path

from tender_radar.importer.etimad_html import html_to_text
from tender_radar.importer.etimad_text import ETIMAD_LIST_URL, parse_etimad_text

FIXTURE = Path(__file__).parent / "fixtures" / "etimad_copy.txt"


def parsed():
    return parse_etimad_text(FIXTURE.read_text(encoding="utf-8"))


def test_parses_complete_cards():
    result = parsed()
    assert [t.reference for t in result.tenders] == ["999000000001", "999000000002", "999000000003"]
    first = result.tenders[0]
    assert first.title == "تطوير بوابة إلكترونية لخدمات المستفيدين في الجهة النموذجية"
    assert first.agency == "وزارة الخدمات التجريبية - فرع منطقة الرياض"
    assert first.tender_type == "منافسة عامة"
    assert first.activity == "تقنية المعلومات"
    assert first.published_on == date(2026, 11, 15)
    assert first.inquiry_deadline == date(2026, 11, 20)
    assert (first.deadline, first.deadline_time) == (date(2026, 11, 27), "10:00")
    assert first.booklet_price_sar == 0
    assert first.source == "etimad-import"
    assert first.source_url == ETIMAD_LIST_URL


def test_arabic_indic_digits_paid_booklet_and_no_time():
    second = parsed().tenders[1]
    assert second.reference == "999000000002"
    assert second.published_on == date(2026, 11, 14)
    assert (second.deadline, second.deadline_time) == (date(2026, 11, 20), None)
    assert second.booklet_price_sar == 1500
    assert second.title.endswith("...")  # truncated titles are kept as shown


def test_missing_optional_fields_stay_empty():
    third = parsed().tenders[2]
    assert third.inquiry_deadline is None
    assert third.booklet_price_sar is None
    assert third.deadline_time == "09:59"


def test_broken_card_is_skipped_with_a_reason():
    skipped = parsed().skipped
    assert len(skipped) == 1
    assert "no reference number" in skipped[0]
    assert "بطاقة ناقصة" in skipped[0]


def test_garbage_never_crashes():
    for text in ["", "random text", "تاريخ النشر :", "تاريخ النشر :2026-99-99\nx\ny\nالرقم المرجعي 1\nآخر موعد لتقديم العروض 2026-02-31"]:
        result = parse_etimad_text(text)
        assert result.tenders == []


def test_saved_html_gives_the_same_result():
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    html = "<html><head><style>.x{}</style><script>var a = 'تاريخ النشر :2020-01-01';</script></head><body>"
    html += "".join(f"<div><span>{escape(line)}</span></div>\n" for line in lines) + "</body></html>"
    assert parse_etimad_text(html_to_text(html)) == parsed()


CARD = """تاريخ النشر :2026-11-15
منافسة عامة
عنوان منافسة تجريبية
جهة تجريبية
التفاصيل
النشاط الأساسي
تقنية المعلومات
الرقم المرجعي
999000000009
آخر موعد لإستلام الإستفسارات
2026-11-20
آخر موعد لتقديم العروض
2026-11-27 10:00
"""


def test_values_on_the_line_after_their_label():
    t = parse_etimad_text(CARD).tenders[0]
    assert t.reference == "999000000009"
    assert t.activity == "تقنية المعلومات"
    assert t.inquiry_deadline == date(2026, 11, 20)
    assert (t.deadline, t.deadline_time) == (date(2026, 11, 27), "10:00")


def test_saved_html_with_inline_label_and_value():
    """Saved pages may put a label and its value in neighbouring <span>s."""

    def to_div(line: str) -> str:
        label = "الرقم المرجعي"
        if line.startswith(label):
            return f"<div><span>{label}</span><span>{escape(line[len(label):].strip())}</span></div>"
        return f"<div>{escape(line)}</div>"

    html = "".join(to_div(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines())
    refs = [t.reference for t in parse_etimad_text(html_to_text(html)).tenders]
    assert refs == ["999000000001", "999000000002", "999000000003"]


def test_hijri_or_odd_dates_are_not_mistaken_for_gregorian():
    hijri = CARD.replace("2026-11-27 10:00", "1448-05-24")
    result = parse_etimad_text(hijri)
    assert result.tenders == []
    assert "not a Gregorian date" in result.skipped[0]


def test_card_without_a_readable_deadline_gets_a_warning():
    result = parse_etimad_text(CARD.replace("2026-11-27 10:00", "27/11/2026"))
    assert result.tenders[0].deadline is None
    assert any("no deadline" in w for w in result.warnings)
