"""Render the read-only demo to plain HTML files (for GitHub Pages).

It reuses the exact page functions the live app uses, with static_files=True,
so links become relative .html files and forms disappear. The result is a
folder anyone can open without a server: no running cost, and it is never
"asleep" when a recruiter clicks the link.

Layout, once per language (en/, ar/): index.html (home), companies.html,
companies/new.html (add-a-company preview), how.html (How it works),
c/<id>/index.html (matches), c/<id>/tenders/<slug>.html,
calendar/<slug>.ics, briefs/sample.html.
The root index.html sends visitors to en/; static/ is shared.
Only synthetic seed tenders are written; imported Etimad tenders stay private.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from tender_radar.calendar_ics import tender_ics
from tender_radar.models import CompanyProfile
from tender_radar.repository import latest_brief, latest_brief_id, list_answers
from tender_radar.web import i18n
from tender_radar.web.app import (
    SAMPLE_BOOKLET,
    STATIC_DIR,
    _rows,
    render_add_company,
    render_brief,
    render_companies,
    render_how,
    render_dashboard,
    render_home,
    render_tender,
    tender_slug,
)

# Written into every export so we know the folder is ours to clear next time.
MARKER = ".tender-radar-export"


class ExportError(Exception):
    pass


def _write(path: Path, html: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8", newline="")  # write as is: .ics files need their exact CRLF line ends
    return path


def _prepare(out_dir: Path) -> None:
    """Start from an empty folder so pages of tenders that are gone do not linger.

    We only ever delete a folder that a previous export created (it holds the
    marker file) or an empty one, never a folder of the user's own files.
    """
    if out_dir.exists() and any(out_dir.iterdir()):
        if not (out_dir / MARKER).exists():
            raise ExportError(f"{out_dir} is not empty and was not created by an export; choose another folder")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / MARKER).write_text("created by: python -m tender_radar export\n", encoding="utf-8")


ROOT_INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=en/index.html">
<title>Tender Radar</title></head>
<body><a href="en/index.html">Tender Radar</a> · <a href="ar/index.html" lang="ar">رادار المنافسات</a></body></html>
"""


def export_site(session: Session, profiles: list[CompanyProfile], today: date, out_dir: Path) -> list[Path]:
    """Write every page in both languages, the root redirect and the static files."""
    out_dir = Path(out_dir)
    _prepare(out_dir)
    written = [_write(out_dir / "index.html", ROOT_INDEX)]
    sample = latest_brief(session, SAMPLE_BOOKLET)
    sample_id = latest_brief_id(session, SAMPLE_BOOKLET)

    for lang in i18n.LANGS:
        base = out_dir / lang
        written.append(_write(base / "index.html", render_home(session, today, lang, static_files=True)))
        html = render_companies(session, today, read_only=True, static_files=True, lang=lang)
        written.append(_write(base / "companies.html", html))
        html = render_add_company(session, today, read_only=True, static_files=True, lang=lang)
        written.append(_write(base / "companies" / "new.html", html))  # a disabled preview, no form
        written.append(_write(base / "how.html", render_how(session, today, True, static_files=True, lang=lang)))
        for profile in profiles:
            company_dir = base / "c" / profile.id
            html = render_dashboard(session, profile, today, read_only=True, static_files=True, lang=lang)
            written.append(_write(company_dir / "index.html", html))
            results, _filtered = _rows(session, profile, today, public_only=True)
            for row in results:
                ref = row.tender.reference
                html = render_tender(session, ref, profile, today, read_only=True, static_files=True, lang=lang)
                written.append(_write(company_dir / "tenders" / f"{tender_slug(ref)}.html", html))
                if row.tender.deadline:  # the page's "Add to calendar" file
                    written.append(_write(base / "calendar" / f"{tender_slug(ref)}.ics", tender_ics(row.tender, lang)))
        if sample is not None:
            qa = list_answers(session, sample_id, lang=lang)  # "Ask the booklet" examples in this language
            html = render_brief(sample[1], sample[0], read_only=True, static_files=True, qa=qa, lang=lang, session=session)
            written.append(_write(base / "briefs" / "sample.html", html))

    static_out = out_dir / "static"
    static_out.mkdir(parents=True, exist_ok=True)
    for f in STATIC_DIR.iterdir():
        written.append(Path(shutil.copy2(f, static_out / f.name)))
    return written
