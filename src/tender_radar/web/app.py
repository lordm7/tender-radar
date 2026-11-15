"""The web app (FastAPI) and the page render functions.

Pages are rendered by plain functions (render_dashboard, render_tender) that
return HTML strings. The FastAPI routes call them for the live app, and the
static exporter calls the same functions with read_only=True to build the
free public demo, so both always look the same.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, PackageLoader, select_autoescape
from sqlalchemy.orm import Session

from tender_radar.db import init_db, make_engine, session_scope
from tender_radar.models import CompanyProfile, MatchResult, Tender
from tender_radar.repository import first_profile, get_tender, latest_brief, list_matches, list_tenders
from tender_radar.settings import Settings

STATIC_DIR = Path(__file__).parent / "static"
SAMPLE_BOOKLET = "sample_booklet.pdf"

templates = Environment(loader=PackageLoader("tender_radar.web", "templates"), autoescape=select_autoescape())


def tender_slug(reference: str) -> str:
    """A file-name-safe version of a tender reference (used by the static demo)."""
    return re.sub(r"[^A-Za-z0-9-]", "-", reference)


def deadline_label(deadline: date | None, today: date) -> str:
    if deadline is None:
        return "غير محدد / not stated"
    days = (deadline - today).days
    if days < 0:
        return "Closed"
    if days == 0:
        return "Closes today"
    return "1 day left" if days == 1 else f"{days} days left"


@dataclass
class Links:
    """Where links point: absolute routes for the live app, relative .html files for the static demo."""

    read_only: bool
    root: str  # "" or "../" in the static demo, "/" in the live app

    def home(self) -> str:
        return f"{self.root}index.html" if self.read_only else "/"

    def tender(self, reference: str) -> str:
        return f"{self.root}tenders/{tender_slug(reference)}.html" if self.read_only else f"/tenders/{reference}"

    def sample_brief(self) -> str:
        return f"{self.root}briefs/sample.html" if self.read_only else "/briefs/sample"

    def static(self, name: str) -> str:
        return f"{self.root}static/{name}"


def _links(read_only: bool, depth: int = 0) -> Links:
    return Links(read_only=read_only, root=("../" * depth) if read_only else "/")


@dataclass
class Row:
    tender: Tender
    match: MatchResult | None
    days_left: int | None


def _rows(session: Session, profile: CompanyProfile, today: date) -> tuple[list[Row], list[Row]]:
    """Split tenders into (results to show, filtered-out), results sorted best first."""
    matches = {m.tender_reference: m for m in list_matches(session, profile.id)}
    results, filtered = [], []
    for t in list_tenders(session):
        m = matches.get(t.reference)
        row = Row(t, m, (t.deadline - today).days if t.deadline else None)
        (filtered if m is not None and m.status == "filtered_out" else results).append(row)
    results.sort(key=lambda r: (r.match is None or r.match.status != "scored", -(r.match.score or 0) if r.match else 0))
    return results, filtered


def _common(session: Session, profile: CompanyProfile, today: date, links: Links) -> dict:
    return {
        "profile": profile,
        "today": today,
        "links": links,
        "deadline_label": lambda d: deadline_label(d, today),
        "has_sample_brief": latest_brief(session, SAMPLE_BOOKLET) is not None,
    }


def render_dashboard(session: Session, profile: CompanyProfile, today: date, read_only: bool) -> str:
    results, filtered = _rows(session, profile, today)
    agencies = sorted({r.tender.agency for r in results})
    return templates.get_template("dashboard.html").render(
        results=results, filtered=filtered, agencies=agencies, **_common(session, profile, today, _links(read_only))
    )


def render_tender(session: Session, ref: str, profile: CompanyProfile, today: date, read_only: bool) -> str | None:
    tender = get_tender(session, ref)
    if tender is None:
        return None
    match = next((m for m in list_matches(session, profile.id) if m.tender_reference == ref), None)
    return templates.get_template("tender.html").render(
        tender=tender, match=match, **_common(session, profile, today, _links(read_only, depth=1))
    )


def create_app(settings: Settings | None = None, today: date | None = None, read_only: bool = False) -> FastAPI:
    """Build the FastAPI app. `today` can be fixed for tests and demos."""
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    init_db(engine)
    app = FastAPI(title="Tender Radar")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def current_day() -> date:
        return today or date.today()

    def with_profile(fn: Callable[[Session, CompanyProfile], str | None]) -> str | None:
        with session_scope(engine) as s:
            profile = first_profile(s)
            if profile is None:
                raise HTTPException(503, "No company profile yet. Run: python -m tender_radar seed")
            return fn(s, profile)

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return with_profile(lambda s, p: render_dashboard(s, p, current_day(), read_only))

    @app.get("/tenders/{reference}", response_class=HTMLResponse)
    def tender_page(reference: str) -> str:
        html = with_profile(lambda s, p: render_tender(s, reference, p, current_day(), read_only))
        if html is None:
            raise HTTPException(404, "Tender not found")
        return html

    app.state.engine = engine
    app.state.settings = settings
    app.state.read_only = read_only
    app.state.current_day = current_day
    app.state.with_profile = with_profile
    return app
