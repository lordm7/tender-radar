"""The daily email digest: today's best open matches for one company.

It reads matches already stored by `match` (no AI calls here) and sends one
plain-text + HTML email to the owner's own address (TR_DIGEST_TO). Without SMTP
settings nothing is sent; the CLI saves a preview file instead.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from typing import Callable

from jinja2 import Environment, PackageLoader, select_autoescape
from sqlalchemy.orm import Session

from tender_radar.models import CompanyProfile
from tender_radar.settings import Settings
from tender_radar.web.app import Row, _rows, deadline_label

MIN_SCORE = 50  # below this the AI thinks it is a poor fit; not worth an email line
SMTP_TIMEOUT_SECONDS = 30

_templates = Environment(loader=PackageLoader("tender_radar.web", "templates"), autoescape=select_autoescape())


@dataclass
class Digest:
    subject: str
    text: str
    html: str
    count: int


def build_digest(session: Session, profile: CompanyProfile, today: date, top_n: int = 10) -> Digest:
    """The best still-open scored tenders (score >= MIN_SCORE), best first, newest first on ties."""
    results, _filtered = _rows(session, profile, today)
    good = [r for r in results if r.match and r.match.status == "scored" and r.match.score >= MIN_SCORE]
    good.sort(key=lambda r: (-r.match.score, -(r.tender.published_on or date.min).toordinal()))
    rows = good[:top_n]
    subject = f"رادار المنافسات: {len(rows)} منافسة مناسبة · {profile.name} · {today.isoformat()}"
    return Digest(subject=subject, text=_text(rows, profile, today), html=_html(rows, profile, today), count=len(rows))


def _line(row: Row, today: date) -> str:
    t = row.tender
    reason = row.match.reasons_en[0] if row.match.reasons_en else ""
    return (
        f"[{row.match.score}] {t.title}\n"
        f"      {t.agency} · {t.reference} · {deadline_label(t.deadline, today)}\n"
        f"      {reason}"
    )


def _text(rows: list[Row], profile: CompanyProfile, today: date) -> str:
    head = f"Tender Radar · {profile.name} · {today.isoformat()}\n{len(rows)} tenders worth a look:\n\n"
    return head + "\n\n".join(_line(r, today) for r in rows) + "\n"


def _html(rows: list[Row], profile: CompanyProfile, today: date) -> str:
    return _templates.get_template("digest_email.html").render(
        rows=rows, profile=profile, today=today, deadline_label=lambda d: deadline_label(d, today)
    )


def smtp_send(message: EmailMessage, settings: Settings) -> None:
    """Send through an SMTP server with STARTTLS (e.g. Gmail on port 587)."""
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)


def send_digest(
    digest: Digest, settings: Settings, sender: Callable[[EmailMessage, Settings], None] | None = None
) -> bool:
    """Email the digest to TR_DIGEST_TO. Returns False (and sends nothing) if SMTP is not configured."""
    if not settings.smtp_configured:
        return False
    message = EmailMessage()
    message["Subject"] = digest.subject
    message["From"] = settings.smtp_user
    message["To"] = settings.digest_to
    message.set_content(digest.text)
    message.add_alternative(digest.html, subtype="html")
    (sender or smtp_send)(message, settings)
    return True
