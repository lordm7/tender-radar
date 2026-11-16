"""The web app (FastAPI) and the page render functions.

Pages are rendered by plain functions (render_dashboard, render_tender) that
return HTML strings. The FastAPI routes call them for the live app, and the
static exporter calls the same functions with read_only=True to build the
free public demo, so both always look the same.

Several companies can share one tender list. Each company's pages live under
/c/<company id>/ in the live app and c/<company id>/ in the static demo.
"""

from __future__ import annotations

import hashlib
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
from tender_radar.models import BookletAnswer, BookletBrief, CompanyProfile, MatchResult, Tender
from tender_radar.reader.ask import answer_question
from tender_radar.reader.brief import build_brief
from tender_radar.reader.pdf_text import UnreadablePDF, extract_pages
from tender_radar.regions import infer_region
from tender_radar.repository import (
    get_brief,
    get_pages,
    get_profile,
    get_tender,
    latest_brief,
    latest_brief_filename,
    latest_brief_id,
    list_answers,
    list_matches,
    list_profiles,
    list_tenders,
    save_answer,
    save_brief,
    save_profile,
)
from tender_radar.settings import Settings

STATIC_DIR = Path(__file__).parent / "static"
SAMPLE_BOOKLET = "sample_booklet.pdf"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

templates = Environment(loader=PackageLoader("tender_radar.web", "templates"), autoescape=select_autoescape())


def tender_slug(reference: str) -> str:
    """A file-name-safe version of a tender reference (used by the static demo).

    Normal references (digits) stay as they are. If unsafe characters had to be
    replaced, a short hash is added so "A/1" and "A-1" never share a file.
    """
    safe = re.sub(r"[^A-Za-z0-9-]", "-", reference)
    if safe == reference:
        return safe
    return f"{safe}-{hashlib.sha256(reference.encode('utf-8')).hexdigest()[:6]}"


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
    """Where links point.

    static_files: the exported demo, where every page is a relative .html file.
    read_only: hide everything that changes data (profile editor, booklet upload).
    The two are separate because a read-only *server* still uses normal routes.
    """

    static_files: bool
    read_only: bool
    company: str | None = None  # the company whose pages we are on, if any
    depth: int = 0  # folder depth of the current static page, for "../" prefixes

    @property
    def root(self) -> str:
        return "../" * self.depth if self.static_files else "/"

    def companies(self) -> str:
        return f"{self.root}index.html" if self.static_files else "/"

    def home(self) -> str:
        """The current company's dashboard, or the company list if there is none."""
        return self.companies() if self.company is None else self.dashboard_of(self.company)

    def dashboard_of(self, company: str) -> str:
        return f"{self.root}c/{company}/index.html" if self.static_files else f"/c/{company}/"

    def tender(self, reference: str) -> str:
        if self.static_files:
            return f"{self.root}c/{self.company}/tenders/{tender_slug(reference)}.html"
        return f"/c/{self.company}/tenders/{reference}"

    def sample_brief(self) -> str:
        return f"{self.root}briefs/sample.html" if self.static_files else "/briefs/sample"

    def static(self, name: str) -> str:
        return f"{self.root}static/{name}"

    def profile(self) -> str:
        return f"/c/{self.company}/profile"

    def reader(self) -> str:
        return "/reader"


def _links(read_only: bool, static_files: bool, company: str | None = None, depth: int = 0) -> Links:
    return Links(static_files=static_files, read_only=read_only or static_files, company=company, depth=depth)


@dataclass
class Row:
    tender: Tender
    match: MatchResult | None
    days_left: int | None


def is_public(tender: Tender) -> bool:
    """Only synthetic seed tenders may appear in the public, read-only demo.

    Tenders imported from Etimad are private (its usage policy forbids
    republishing without written permission), so read-only pages never show them.
    """
    return tender.source == "seed"


def _rows(session: Session, profile: CompanyProfile, today: date, public_only: bool = False) -> tuple[list[Row], list[Row]]:
    """Split tenders into (results to show, filtered-out), results sorted best first."""
    matches = {m.tender_reference: m for m in list_matches(session, profile.id)}
    results, filtered = [], []
    for t in list_tenders(session):
        if public_only and not is_public(t):
            continue
        m = matches.get(t.reference)
        row = Row(t, m, (t.deadline - today).days if t.deadline else None)
        expired = row.days_left is not None and row.days_left < 0  # closed since the last matching run
        (filtered if expired or (m is not None and m.status == "filtered_out") else results).append(row)
    results.sort(key=lambda r: (r.match is None or r.match.status != "scored", -(r.match.score or 0) if r.match else 0))
    return results, filtered


def _common(session: Session, today: date, links: Links) -> dict:
    return {
        "today": today,
        "links": links,
        "deadline_label": lambda d: deadline_label(d, today),
        "infer_region": infer_region,
        "has_sample_brief": latest_brief(session, SAMPLE_BOOKLET) is not None,
        "several_companies": len(list_profiles(session)) > 1,
        "footer": (
            f"Synthetic demo data · scores precomputed on {today.isoformat()} · built with Python + AI"
            if links.read_only
            else None
        ),
    }


def render_companies(session: Session, today: date, read_only: bool, static_files: bool = False) -> str:
    """The company chooser: one card per company with its best matches."""
    cards = []
    for profile in list_profiles(session):
        results, _filtered = _rows(session, profile, today, public_only=read_only or static_files)
        scored = [r.match.score for r in results if r.match and r.match.status == "scored"]
        cards.append({"profile": profile, "count": len(results), "best": max(scored, default=None)})
    links = _links(read_only, static_files)
    return templates.get_template("companies.html").render(cards=cards, **_common(session, today, links))


def render_dashboard(
    session: Session, profile: CompanyProfile, today: date, read_only: bool, static_files: bool = False
) -> str:
    results, filtered = _rows(session, profile, today, public_only=read_only or static_files)
    agencies = sorted({r.tender.agency for r in results})
    links = _links(read_only, static_files, profile.id, depth=2)
    return templates.get_template("dashboard.html").render(
        profile=profile, results=results, filtered=filtered, agencies=agencies, **_common(session, today, links)
    )


def render_tender(
    session: Session, ref: str, profile: CompanyProfile, today: date, read_only: bool, static_files: bool = False
) -> str | None:
    tender = get_tender(session, ref)
    if tender is None or ((read_only or static_files) and not is_public(tender)):
        return None
    match = next((m for m in list_matches(session, profile.id) if m.tender_reference == ref), None)
    links = _links(read_only, static_files, profile.id, depth=3)
    return templates.get_template("tender.html").render(
        tender=tender, match=match, profile=profile, **_common(session, today, links)
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
        profile=profile, values=values, error=error, links=_links(False, False, profile.id), has_sample_brief=False
    )


def render_brief(
    brief: BookletBrief,
    filename: str,
    read_only: bool,
    static_files: bool = False,
    qa: list[tuple[str, BookletAnswer]] | None = None,
    brief_id: int | None = None,
    can_ask: bool = False,
    ask_error: str | None = None,
) -> str:
    """Brief page with its "Ask the booklet" questions. In the static demo it lives
    in briefs/, one folder down, and shows the stored answers without the form."""
    return templates.get_template("brief.html").render(
        brief=brief, filename=filename, links=_links(read_only, static_files, depth=1), has_sample_brief=False,
        qa=qa or [], brief_id=brief_id, can_ask=can_ask and not read_only and brief_id is not None, ask_error=ask_error,
    )


def render_reader(profiles: list[CompanyProfile], error: str | None = None) -> str:
    return templates.get_template("reader.html").render(
        error=error, profiles=profiles, links=_links(False, False), has_sample_brief=False,
        max_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
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

    def with_profile(profile_id: str, fn: Callable[[Session, CompanyProfile], str | None]) -> str | None:
        with session_scope(engine) as s:
            profile = get_profile(s, profile_id)
            if profile is None:
                raise HTTPException(404, "No company with this id")
            return fn(s, profile)

    @app.get("/", response_class=HTMLResponse)
    def home():
        with session_scope(engine) as s:
            profiles = list_profiles(s)
            if not profiles:
                raise HTTPException(503, "No company profile yet. Run: python -m tender_radar seed")
            if len(profiles) == 1:
                return RedirectResponse(f"/c/{profiles[0].id}/", status_code=307)
            return render_companies(s, current_day(), read_only)

    @app.get("/c/{profile_id}/", response_class=HTMLResponse)
    def dashboard(profile_id: str) -> str:
        return with_profile(profile_id, lambda s, p: render_dashboard(s, p, current_day(), read_only))

    @app.get("/c/{profile_id}/tenders/{reference}", response_class=HTMLResponse)
    def tender_page(profile_id: str, reference: str) -> str:
        html = with_profile(profile_id, lambda s, p: render_tender(s, reference, p, current_day(), read_only))
        if html is None:
            raise HTTPException(404, "Tender not found")
        return html

    def get_ai() -> LLMProvider:
        return provider if provider is not None else get_provider(settings)

    def brief_html(brief_id: int, ask_error: str | None = None) -> str | None:
        with session_scope(engine) as s:
            brief = get_brief(s, brief_id)
            if brief is None:
                return None
            return render_brief(
                brief, latest_brief_filename(s, brief_id) or "", read_only, qa=list_answers(s, brief_id),
                brief_id=brief_id, can_ask=get_pages(s, brief_id) is not None, ask_error=ask_error,
            )

    @app.get("/briefs/sample", response_class=HTMLResponse)
    def sample_brief() -> str:
        with session_scope(engine) as s:
            brief_id = latest_brief_id(s, SAMPLE_BOOKLET)
        if brief_id is None:
            raise HTTPException(404, "No sample brief yet. Run: python -m tender_radar brief data/seed/sample_booklet.pdf")
        return brief_html(brief_id)

    @app.get("/briefs/{brief_id}", response_class=HTMLResponse)
    def brief_page(brief_id: int) -> str:
        html = brief_html(brief_id)
        if html is None:
            raise HTTPException(404, "Brief not found")
        return html

    if not read_only:

        def all_profiles() -> list[CompanyProfile]:
            with session_scope(engine) as s:
                return list_profiles(s)

        @app.get("/reader", response_class=HTMLResponse)
        def reader_page() -> str:
            return render_reader(all_profiles())

        @app.post("/reader")
        def reader_upload(file: UploadFile = File(...), profile_id: str = Form("")):
            # A plain `def` route runs in a worker thread, so reading the PDF and
            # waiting for the AI does not freeze the app for other visitors.
            content = file.file.read(MAX_UPLOAD_BYTES + 1)
            if not content:
                return HTMLResponse(render_reader(all_profiles(), "The file is empty."), status_code=400)
            if len(content) > MAX_UPLOAD_BYTES:
                return HTMLResponse(render_reader(all_profiles(), "The file is larger than 15 MB."), status_code=413)
            filename = Path(file.filename or "booklet.pdf").name
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "upload.pdf"
                path.write_bytes(content)
                try:
                    pages = extract_pages(path)
                except UnreadablePDF as exc:
                    return HTMLResponse(render_reader(all_profiles(), str(exc)), status_code=400)
            with session_scope(engine) as s:
                profiles = list_profiles(s)
                profile = next((p for p in profiles if p.id == profile_id), profiles[0] if profiles else None)
                if profile is None:
                    raise HTTPException(503, "No company profile yet. Run: python -m tender_radar seed")
                try:
                    brief = build_brief(pages, profile, get_ai())
                except (AIError, ValidationError):
                    message = "The AI could not read this booklet right now. Please try again later."
                    return HTMLResponse(render_reader(profiles, message), status_code=502)
                brief_id = save_brief(s, filename, brief, pages=pages)
            return RedirectResponse(f"/briefs/{brief_id}", status_code=303)

        @app.post("/briefs/{brief_id}/ask", response_class=HTMLResponse)
        def ask_booklet(brief_id: int, question: str = Form("")):
            with session_scope(engine) as s:
                pages = get_pages(s, brief_id)
            if pages is None:
                raise HTTPException(404, "No booklet text for this brief (upload the booklet again to ask questions).")
            question = question.strip()[:500]
            if not question:
                return HTMLResponse(brief_html(brief_id, "Please type a question."), status_code=400)
            try:
                answer = answer_question(question, pages, get_ai())
            except (AIError, ValidationError, ValueError):
                return HTMLResponse(brief_html(brief_id, "The AI could not answer right now. Please try again later."), status_code=502)
            with session_scope(engine) as s:
                save_answer(s, brief_id, question, answer)
            # Redirect after POST, so reloading the page does not ask (and spend an AI call) again.
            return RedirectResponse(f"/briefs/{brief_id}#ask", status_code=303)

        @app.get("/c/{profile_id}/profile", response_class=HTMLResponse)
        def profile_page(profile_id: str) -> str:
            return with_profile(profile_id, lambda s, p: render_profile_form(p))

        @app.post("/c/{profile_id}/profile")
        def profile_save(
            profile_id: str,
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
                current = get_profile(s, profile_id)
                if current is None:
                    raise HTTPException(404, "No company with this id")
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
            # Saved first, so a missing AI setup never throws away the user's edits.
            try:
                ai = get_ai()
            except ValueError as exc:
                return HTMLResponse(render_profile_form(updated, form, f"Profile saved, but AI scoring is not configured: {exc}"))
            with session_scope(engine) as s:
                run_matching(s, updated, ai, current_day())
            return RedirectResponse(f"/c/{updated.id}/", status_code=303)

    app.state.engine = engine
    app.state.settings = settings
    app.state.read_only = read_only
    app.state.current_day = current_day
    app.state.with_profile = with_profile
    return app
