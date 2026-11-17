import pytest

from tender_radar.ai.provider import AIError, FakeProvider
from tender_radar.reader.profile_extract import ProfileDraft, extract_profile, new_profile_id


def test_extract_maps_ai_answer_to_a_draft():
    fake = FakeProvider([{
        "name": "Acme IT",
        "name_ar": "أكمي للتقنية",
        "activities": ["تقنية المعلومات"],
        "keywords": ["برمجيات", "cloud"],
        "certifications": ["ISO 27001"],
        "regions": ["الرياض"],
        "min_value_sar": 100000,
        "max_value_sar": None,
    }])
    draft = extract_profile(["Acme IT company profile", "We build software"], fake)
    assert draft.name == "Acme IT" and draft.name_ar == "أكمي للتقنية"
    assert draft.keywords == ["برمجيات", "cloud"]
    assert draft.min_value_sar == 100000 and draft.max_value_sar is None
    assert "[page 2]" in fake.calls[0] and "We build software" in fake.calls[0]


def test_unknown_fields_stay_empty():
    draft = extract_profile(["text"], FakeProvider([{}]))
    assert draft == ProfileDraft()
    assert draft.name == "" and draft.activities == [] and draft.min_value_sar is None


def test_ai_failure_is_raised():
    with pytest.raises(AIError):
        extract_profile(["text"], FakeProvider([AIError("down")] * 3))


def test_draft_becomes_form_values():
    draft = ProfileDraft(name="Acme", keywords=["a", "b"], min_value_sar=5000.0)
    values = draft.form_values()
    assert values["name"] == "Acme" and values["keywords"] == "a\nb"
    assert values["min_value_sar"] == "5000" and values["max_value_sar"] == ""


@pytest.mark.parametrize(
    ("name", "existing", "expected"),
    [
        ("Acme IT Services", [], "acme-it-services"),
        ("Acme IT", ["acme-it"], "acme-it-2"),
        ("Acme IT", ["acme-it", "acme-it-2"], "acme-it-3"),
        ("  Al-Bunyan & Co. (synthetic) ", [], "al-bunyan-co-synthetic"),
        ("شركة أكمي", [], "company-1"),
        ("شركة أكمي", ["company-1"], "company-2"),
    ],
)
def test_new_profile_id(name, existing, expected):
    assert new_profile_id(name, existing) == expected
