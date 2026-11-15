"""Render the read-only demo to plain HTML files (for GitHub Pages).

It reuses the exact page functions the live app uses, with read_only=True,
so links become relative .html files and forms disappear. The result is a
folder anyone can open without a server: no running cost, and it is never
"asleep" when a recruiter clicks the link.
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
    render_dashboard,
    render_tender,
    tender_slug,
)


def _write(path: Path, html: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


def export_site(session: Session, profile: CompanyProfile, today: date, out_dir: Path) -> list[Path]:
    """Write index.html, one page per shown tender, the sample brief and the static files."""
    out_dir = Path(out_dir)
    written = [_write(out_dir / "index.html", render_dashboard(session, profile, today, read_only=True))]

    results, _filtered = _rows(session, profile, today)
    for row in results:
        ref = row.tender.reference
        html = render_tender(session, ref, profile, today, read_only=True)
        written.append(_write(out_dir / "tenders" / f"{tender_slug(ref)}.html", html))

    sample = latest_brief(session, SAMPLE_BOOKLET)
    if sample is not None:
        written.append(_write(out_dir / "briefs" / "sample.html", render_brief(sample[1], sample[0], read_only=True)))

    static_out = out_dir / "static"
    static_out.mkdir(parents=True, exist_ok=True)
    for f in STATIC_DIR.iterdir():
        written.append(Path(shutil.copy2(f, static_out / f.name)))
    return written
