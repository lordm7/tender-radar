"""Read tenders from text a person copied (Ctrl+A, Ctrl+C) or saved from Etimad.

We never fetch Etimad automatically (its pages use a CAPTCHA and its policy
forbids copying without permission). A person opens the public list in a normal
browser and copies it; this module turns that text into Tender records.

Each card on the page starts with "تاريخ النشر", so we split there and read the
labelled lines. A card we cannot read is skipped and reported, never fatal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from tender_radar.arabic import normalize
from tender_radar.models import Tender

ETIMAD_LIST_URL = "https://tenders.etimad.sa/Tender/AllTendersForVisitor"

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "0123456789" * 2)
_CARD_START = re.compile(r"^\s*تاريخ النشر", re.MULTILINE)
_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_TIME = re.compile(r"\b(\d{1,2}:\d{2})\b")
_REFERENCE = re.compile(r"\d{6,}")
_PRICE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Labels as they appear on the card, compared after normalize() so that
# spelling differences such as إ/ا in "لإستلام" do not matter.
_LABEL_DETAILS = normalize("التفاصيل")
_LABEL_ACTIVITY = normalize("النشاط الأساسي")
_LABEL_REFERENCE = normalize("الرقم المرجعي")
_LABEL_INQUIRY = normalize("آخر موعد لإستلام الإستفسارات")
_LABEL_DEADLINE = normalize("آخر موعد لتقديم العروض")
_LABEL_PRICE = normalize("قيمة وثائق المنافسة")
_FREE = normalize("مجانا")


@dataclass
class ImportResult:
    tenders: list[Tender] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # one human-readable reason per card


class _BadCard(Exception):
    pass


def parse_etimad_text(text: str) -> ImportResult:
    """Turn copied Etimad list text into tenders; unreadable cards go to `skipped`."""
    text = text.translate(_DIGITS)
    starts = [m.start() for m in _CARD_START.finditer(text)]
    result = ImportResult()
    by_reference: dict[str, Tender] = {}
    for number, (start, end) in enumerate(zip(starts, starts[1:] + [len(text)]), start=1):
        lines = [line.strip() for line in text[start:end].splitlines() if line.strip()]
        try:
            tender = _parse_card(lines)
        except _BadCard as exc:
            label = lines[2] if len(lines) > 2 else "?"
            result.skipped.append(f"card {number} ({label[:60]}): {exc}")
            continue
        by_reference[tender.reference] = tender  # the same card twice: keep the last copy
    result.tenders = list(by_reference.values())
    return result


def _parse_card(lines: list[str]) -> Tender:
    published = _date_in(lines[0])
    header = _lines_before(lines[1:], _LABEL_DETAILS)  # type, title, agency

    reference = _value_after(lines, _LABEL_REFERENCE)
    match = _REFERENCE.search(reference or "")
    if match is None:
        raise _BadCard("no reference number")
    if len(header) < 2:
        raise _BadCard("no title")

    deadline_line = _value_after(lines, _LABEL_DEADLINE) or ""
    time = _TIME.search(deadline_line)
    return Tender(
        reference=match.group(),
        tender_type=header[0],
        title=header[1],
        agency=header[2] if len(header) > 2 else "",
        activity=_value_after(lines, _LABEL_ACTIVITY) or "",
        published_on=published,
        inquiry_deadline=_date_in(_value_after(lines, _LABEL_INQUIRY) or ""),
        deadline=_date_in(deadline_line),
        deadline_time=time.group(1) if time else None,
        booklet_price_sar=_price(lines),
        source="etimad-import",
        source_url=ETIMAD_LIST_URL,
    )


def _lines_before(lines: list[str], label: str) -> list[str]:
    out = []
    for line in lines:
        if normalize(line).startswith(label):
            break
        out.append(line)
    return out


def _value_after(lines: list[str], label: str) -> str | None:
    """The text after a label on the same line, e.g. "الرقم المرجعي 123" -> "123"."""
    for line in lines:
        normalized = normalize(line)
        if normalized.startswith(label):
            words = len(label.split())
            return " ".join(line.split()[words:])
    return None


def _date_in(text: str) -> date | None:
    match = _DATE.search(text)
    if match is None:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        raise _BadCard(f"impossible date {match.group()}") from None


def _price(lines: list[str]) -> float | None:
    """Booklet price: the label is followed (same or next line) by "مجانا" or a number."""
    for i, line in enumerate(lines):
        if normalize(line).startswith(_LABEL_PRICE):
            rest = " ".join([_value_after([line], _LABEL_PRICE) or ""] + lines[i + 1 : i + 2])
            if _FREE in normalize(rest):
                return 0.0
            number = _PRICE.search(rest)
            return float(number.group().replace(",", "")) if number else None
    return None
