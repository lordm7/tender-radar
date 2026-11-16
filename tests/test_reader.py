import pymupdf
import pytest

from tender_radar.ai.provider import FakeProvider
from tender_radar.reader.brief import MAX_INPUT_CHARS, build_brief
from tender_radar.reader.pdf_text import UnreadablePDF, clean_text, extract_pages

TEXT = "Scope of work: build a digital appointments platform with a web portal and mobile app. " * 5
BRIEF = {
    "scope": "تطوير منصة رقمية",
    "deliverables": ["بوابة ويب"],
    "key_dates": ["آخر موعد: 2026-12-20"],
    "eligibility": ["تصنيف تقنية المعلومات"],
    "required_documents": ["السجل التجاري"],
    "evaluation_criteria": ["الفني 70% والمالي 30%"],
    "risks": ["مدة تنفيذ قصيرة"],
    "go_no_go": [{"item": "ISO 27001", "status": "meets", "note": "متوفرة"}],
}


def make_text_pdf(path, pages=(TEXT, TEXT)):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, 555, 800), text, fontsize=10)
    doc.save(path)
    return path


def make_scanned_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100), False)
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(40, 40, 440, 240), pixmap=pix)
    doc.save(path)
    return path


def test_extract_text_pdf(tmp_path):
    pages = extract_pages(make_text_pdf(tmp_path / "ok.pdf"))
    assert len(pages) == 2
    assert "digital appointments platform" in pages[0]


def test_clean_text_turns_presentation_forms_into_letters():
    assert clean_text("ﻛﺮﺍﺳﺔ ﺍﻟﺸﺮﻭﻁ") == "كراسة الشروط"


def test_scanned_pdf_raises_unreadable_and_no_ai_call(tmp_path):
    fake = FakeProvider()
    with pytest.raises(UnreadablePDF, match="scanned"):
        extract_pages(make_scanned_pdf(tmp_path / "scan.pdf"))
    assert fake.calls == []


def test_corrupt_file_raises_unreadable(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf at all")
    with pytest.raises(UnreadablePDF):
        extract_pages(bad)


def test_long_booklet_truncated_flag(profile):
    fake = FakeProvider()
    brief = build_brief(["x" * 50_000, "y" * 50_000], profile, fake)
    assert brief.truncated is True
    assert len(fake.calls[0]) < MAX_INPUT_CHARS + 5_000


def test_short_booklet_not_truncated_and_has_page_markers(profile):
    fake = FakeProvider()
    brief = build_brief(["first", "second"], profile, fake)
    assert brief.truncated is False
    assert "[page 2]" in fake.calls[0]


def test_brief_uses_provider_schema(profile):
    brief = build_brief([TEXT], profile, FakeProvider([BRIEF]))
    assert brief.scope == "تطوير منصة رقمية"
    assert brief.go_no_go[0].status == "meets"


def test_encrypted_pdf_raises_unreadable(tmp_path):
    path = tmp_path / "locked.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(40, 40, 555, 800), TEXT)
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    with pytest.raises(UnreadablePDF, match="password"):
        extract_pages(path)


def test_pdf_with_no_pages_has_its_own_message(tmp_path, monkeypatch):
    import pymupdf

    from tender_radar.reader import pdf_text

    class NoPages:
        needs_pass = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            return iter([])

        def __len__(self):
            return 0

    monkeypatch.setattr(pymupdf, "open", lambda *a, **k: NoPages())
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"%PDF-1.7")
    with pytest.raises(pdf_text.UnreadablePDF, match="The PDF has no pages"):
        pdf_text.extract_pages(path)


# --- bilingual brief (redesign) ---------------------------------------------

def test_old_brief_without_english_still_loads_and_falls_back_to_arabic():
    from tender_radar.models import BookletBrief

    old = BookletBrief.model_validate_json('{"scope": "نطاق العمل", "risks": ["غرامة"]}')
    text, original = old.in_lang("en")
    assert original is True and text.scope == "نطاق العمل"
    text, original = old.in_lang("ar")
    assert original is False and text.risks == ["غرامة"]


def test_brief_with_english_shows_english():
    from tender_radar.models import BookletBrief, BriefText, ChecklistItem

    brief = BookletBrief(
        scope="نطاق", en=BriefText(scope="Scope", go_no_go=[ChecklistItem(item="ISO 27001", status="meets")])
    )
    text, original = brief.in_lang("en")
    assert original is False and text.scope == "Scope" and text.go_no_go[0].status == "meets"


def test_brief_prompt_asks_for_an_english_copy():
    from importlib import resources

    template = resources.files("tender_radar.prompts").joinpath("booklet_brief.md").read_text(encoding="utf-8")
    assert "en:" in template
