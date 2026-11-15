"""Render the read-only demo to plain HTML files (for GitHub Pages).

It reuses the exact page functions the live app uses, with static_files=True,
so links become relative .html files and forms disappear. The result is a
folder anyone can open without a server: no running cost, and it is never
"asleep" when a recruiter clicks the link.

Layout: index.html (company chooser), c/<id>/index.html (dashboard),
c/<id>/tenders/<slug>.html, briefs/sample.html, static/.
Only synthetic seed tenders are written; imported Etimad tenders stay private.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from tender_radar.models import CompanyProfile
from tender_radar.repository import latest_brief
from tender_radar.web.app import (
    SAMPLE_BOOKLET,
    STATIC_DIR,
    _rows,
    render_brief,
    render_companies,
    render_dashboard,
    render_tender,
    tender_slug,
)

# Written into every export so we know the folder is ours to clear next time.
MARKER = ".tender-radar-export"


class ExportError(Exception):
    pass


def _write(path: Path, html: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
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


def export_site(session: Session, profiles: list[CompanyProfile], today: date, out_dir: Path) -> list[Path]:
    """Write the chooser, each company's dashboard and tender pages, the sample brief and static files."""
    out_dir = Path(out_dir)
    _prepare(out_dir)
    written = [_write(out_dir / "index.html", render_companies(session, today, read_only=True, static_files=True))]

    for profile in profiles:
        company_dir = out_dir / "c" / profile.id
        html = render_dashboard(session, profile, today, read_only=True, static_files=True)
        written.append(_write(company_dir / "index.html", html))
        results, _filtered = _rows(session, profile, today, public_only=True)
        for row in results:
            ref = row.tender.reference
            html = render_tender(session, ref, profile, today, read_only=True, static_files=True)
            written.append(_write(company_dir / "tenders" / f"{tender_slug(ref)}.html", html))

    sample = latest_brief(session, SAMPLE_BOOKLET)
    if sample is not None:
        html = render_brief(sample[1], sample[0], read_only=True, static_files=True)
        written.append(_write(out_dir / "briefs" / "sample.html", html))

    static_out = out_dir / "static"
    static_out.mkdir(parents=True, exist_ok=True)
    for f in STATIC_DIR.iterdir():
        written.append(Path(shutil.copy2(f, static_out / f.name)))
    return written
