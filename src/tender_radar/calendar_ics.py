"""A tender's key dates as an .ics calendar file ("Add to calendar").

Two events: the last day for questions (all day) and the bid deadline (at its
closing time, Riyadh time, when Etimad gives one). Plain text built by hand,
following RFC 5545, so the static demo can ship it as a file with no server.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

RIYADH = timezone(timedelta(hours=3))  # Saudi Arabia has no daylight saving time

_TEXT = {
    "en": {"deadline": "Bid deadline: {title}", "inquiries": "Last day for questions: {title}"},
    "ar": {"deadline": "آخر موعد لتقديم العروض: {title}", "inquiries": "آخر يوم للاستفسارات: {title}"},
}


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """Split a line into pieces of at most 75 bytes; continuation lines start with a space."""
    pieces, current, limit = [], "", 75
    for ch in line:
        if len((current + ch).encode("utf-8")) > limit:
            pieces.append(current)
            current, limit = " ", 75
        current += ch
    pieces.append(current)
    return pieces


def _event(uid: str, summary: str, stamp: datetime, start: date, time: str | None, url: str | None) -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:{uid}@tender-radar", f"DTSTAMP:{stamp.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}"]
    try:
        hour, minute = (int(part) for part in (time or "").split(":"))
        local = datetime(start.year, start.month, start.day, hour, minute, tzinfo=RIYADH)
    except ValueError:  # no time, or not "HH:MM": make it an all-day event
        local = None
    if local is not None:
        lines.append(f"DTSTART:{local.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}")
    else:
        lines += [f"DTSTART;VALUE=DATE:{start:%Y%m%d}", f"DTEND;VALUE=DATE:{start + timedelta(days=1):%Y%m%d}"]
    lines.append(f"SUMMARY:{_escape(summary)}")
    if url:
        lines.append(f"URL:{url}")
    return lines + ["END:VEVENT"]


def tender_ics(tender, lang: str, stamp: datetime | None = None) -> str:
    """The calendar file for one tender, with summaries in `lang` (en|ar)."""
    stamp = stamp or datetime.now(timezone.utc)
    title = tender.title_en if lang == "en" and tender.title_en else tender.title
    text = _TEXT[lang]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Tender Radar//EN", "CALSCALE:GREGORIAN"]
    if tender.inquiry_deadline:
        summary = text["inquiries"].format(title=title)
        lines += _event(f"{tender.reference}-inquiries", summary, stamp, tender.inquiry_deadline, None, tender.source_url)
    if tender.deadline:
        summary = text["deadline"].format(title=title)
        lines += _event(f"{tender.reference}-deadline", summary, stamp, tender.deadline, tender.deadline_time, tender.source_url)
    lines.append("END:VCALENDAR")
    return "".join(piece + "\r\n" for line in lines for piece in _fold(line))
