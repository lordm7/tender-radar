"""The web app (FastAPI) and the page render functions.

Pages are rendered by plain functions (render_dashboard, render_tender) that
return HTML strings. The FastAPI routes call them for the live app, and the
static exporter calls the same functions with read_only=True to build the
free public demo, so both always look the same.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, PackageLoader, select_autoescape
from pydantic import ValidationError
from sqlalchemy.orm import Session

from tender_radar.ai.provider import AIError, LLMProvider, get_provider
from tender_radar.db import init_db, make_engine, session_scope
from tender_radar.matching.scorer import run_matching
from tender_radar.models import BookletBrief, CompanyProfile, MatchResult, Tender
from tender_radar.reader.brief import build_brief
from tender_radar.reader.pdf_text import UnreadablePDF, extract_pages
from tender_radar.repository import (
    first_profile,
    get_brief,
    get_tender,
    latest_brief,
    latest_brief_filename,
    list_matches,
    list_tenders,
    save_brief,
    save_profile,
)
from tender_radar.settings import Settings

STATIC_DIR = Path(__file__).parent / "static"
SAMPLE_BOOKLET = "sample_booklet.pdf"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

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


def _lines(text: str) -> list[str]:
    """Textarea → list: one item per line, blanks dropped."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _number(text: str) -> float | None:
    text = text.strip().replace(",", "")
    return float(text) if text else None


def render_profile_form(profile: CompanyProfile, form: dict | None = None, error: str | None = None) -> str:
    values = form or {
        "name": profile.name,
        "activities": "\n".join(profile.activities),
        "keywords": "\n".join(profile.keywords),
        "certifications": "\n".join(profile.certifications),
        "regions": "\n".join(profile.regions),
        "excluded_agencies": "\n".join(profile.excluded_agencies),
        "min_value_sar": "" if profile.min_value_sar is None else f"{profile.min_value_sar:.0f}",
        "max_value_sar": "" if profile.max_value_sar is None else f"{profile.max_value_sar:.0f}",
    }
    return templates.get_template("profile.html").render(
        profile=profile, values=values, error=error, links=_links(False), has_sample_brief=False
    )


def render_brief(brief: BookletBrief, filename: str, read_only: bool) -> str:
    """Brief page. In the static demo it lives in briefs/, one folder down."""
    return templates.get_template("brief.html").render(
        brief=brief, filename=filename, links=_links(read_only, depth=1), has_sample_brief=False
    )


def render_reader(error: str | None = None) -> str:
    return templates.get_template("reader.html").render(
        error=error, links=_links(False), has_sample_brief=False, max_mb=MAX_UPLOAD_BYTES // (1024 * 1024)
    )


def create_app(
    settings: Settings | None = None,
    today: date | None = None,
    read_only: bool = False,
    provider: LLMProvider | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    `today` can be fixed for tests and demos; `provider` overrides the AI
    provider from settings (tests pass a FakeProvider to count calls).
    """
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

    def get_ai() -> LLMProvider:
        return provider if provider is not None else get_provider(settings)

    @app.get("/briefs/sample", response_class=HTMLResponse)
    def sample_brief() -> str:
        with session_scope(engine) as s:
            found = latest_brief(s, SAMPLE_BOOKLET)
        if found is None:
            raise HTTPException(404, "No sample brief yet. Run: python -m tender_radar brief data/seed/sample_booklet.pdf")
        return render_brief(found[1], found[0], read_only)

    @app.get("/briefs/{brief_id}", response_class=HTMLResponse)
    def brief_page(brief_id: int) -> str:
        with session_scope(engine) as s:
            brief = get_brief(s, brief_id)
            filename = latest_brief_filename(s, brief_id)
        if brief is None:
            raise HTTPException(404, "Brief not found")
        return render_brief(brief, filename or "", read_only)

    if not read_only:

        @app.get("/reader", response_class=HTMLResponse)
        def reader_page() -> str:
            return render_reader()

        @app.post("/reader")
        async def reader_upload(file: UploadFile = File(...)):
            content = await file.read(MAX_UPLOAD_BYTES + 1)
            if len(content) > MAX_UPLOAD_BYTES:
                return HTMLResponse(render_reader("The file is larger than 15 MB."), status_code=413)
            filename = Path(file.filename or "booklet.pdf").name
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "upload.pdf"
                path.write_bytes(content)
                try:
                    pages = extract_pages(path)
                except UnreadablePDF as exc:
                    return HTMLResponse(render_reader(str(exc)), status_code=400)
            with session_scope(engine) as s:
                profile = first_profile(s)
                if profile is None:
                    raise HTTPException(503, "No company profile yet. Run: python -m tender_radar seed")
                try:
                    brief = build_brief(pages, profile, get_ai())
                except (AIError, ValidationError):
                    return HTMLResponse(render_reader("The AI could not read this booklet right now. Please try again later."), status_code=502)
                brief_id = save_brief(s, filename, brief)
            return RedirectResponse(f"/briefs/{brief_id}", status_code=303)

        @app.get("/profile", response_class=HTMLResponse)
        def profile_page() -> str:
            return with_profile(lambda s, p: render_profile_form(p))

        @app.post("/profile")
        def profile_save(
            name: str = Form(...),
            activities: str = Form(""),
            keywords: str = Form(""),
            certifications: str = Form(""),
            regions: str = Form(""),
            excluded_agencies: str = Form(""),
            min_value_sar: str = Form(""),
            max_value_sar: str = Form(""),
        ):
            form = dict(
                name=name, activities=activities, keywords=keywords, certifications=certifications,
                regions=regions, excluded_agencies=excluded_agencies,
                min_value_sar=min_value_sar, max_value_sar=max_value_sar,
            )
            with session_scope(engine) as s:
                current = first_profile(s)
                if current is None:
                    raise HTTPException(503, "No company profile yet. Run: python -m tender_radar seed")
                try:
                    updated = CompanyProfile(
                        id=current.id, name=name.strip(), activities=_lines(activities), keywords=_lines(keywords),
                        certifications=_lines(certifications), regions=_lines(regions),
                        excluded_agencies=_lines(excluded_agencies),
                        min_value_sar=_number(min_value_sar), max_value_sar=_number(max_value_sar),
                    )
                except (ValidationError, ValueError) as exc:
                    message = "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors()) if isinstance(
                        exc, ValidationError) else "Values must be numbers"
                    return HTMLResponse(render_profile_form(current, form, message), status_code=422)
                save_profile(s, updated)
                run_matching(s, updated, get_ai(), current_day())
            return RedirectResponse("/", status_code=303)

    app.state.engine = engine
    app.state.settings = settings
    app.state.read_only = read_only
    app.state.current_day = current_day
    app.state.with_profile = with_profile
    return app
