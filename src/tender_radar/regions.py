"""Guess a tender's region from its agency name.

Real Etimad cards rarely state a region, but agency names often contain one
("أمانة منطقة عسير", "بلدية الخبر"). We look for the 13 administrative regions
and their big cities; the earliest mention in the text wins.
"""

from __future__ import annotations

import re

from tender_radar.arabic import normalize

# place name -> official region. Region names map to themselves.
_PLACES: dict[str, str] = {
    "الرياض": "الرياض", "الخرج": "الرياض", "الدرعية": "الرياض", "المجمعة": "الرياض",
    "مكة المكرمة": "مكة المكرمة", "مكة": "مكة المكرمة", "جدة": "مكة المكرمة", "الطائف": "مكة المكرمة",
    "المدينة المنورة": "المدينة المنورة", "ينبع": "المدينة المنورة", "العلا": "المدينة المنورة",
    "القصيم": "القصيم", "بريدة": "القصيم", "عنيزة": "القصيم",
    "المنطقة الشرقية": "المنطقة الشرقية", "الشرقية": "المنطقة الشرقية", "الدمام": "المنطقة الشرقية",
    "الخبر": "المنطقة الشرقية", "الظهران": "المنطقة الشرقية", "الأحساء": "المنطقة الشرقية",
    "الجبيل": "المنطقة الشرقية", "حفر الباطن": "المنطقة الشرقية",
    "عسير": "عسير", "أبها": "عسير", "خميس مشيط": "عسير",
    "تبوك": "تبوك", "نيوم": "تبوك",
    "حائل": "حائل",
    "الحدود الشمالية": "الحدود الشمالية", "عرعر": "الحدود الشمالية",
    "جازان": "جازان", "جيزان": "جازان",
    "نجران": "نجران",
    "الباحة": "الباحة",
    "الجوف": "الجوف", "سكاكا": "الجوف",
}
# A place counts only as a whole word; Arabic glues و/ب/ل/ف onto the front ("بالرياض").
_PATTERNS = [
    (re.compile(rf"(?:^|\s)[وبلف]?{re.escape(normalize(place))}(?=\s|$)"), region)
    for place, region in _PLACES.items()
]


def infer_region(agency: str) -> str | None:
    """Return the region named (directly or via a city) in the text, or None."""
    text = normalize(agency)
    found = [(m.start(), region) for pattern, region in _PATTERNS if (m := pattern.search(text))]
    return min(found)[1] if found else None
