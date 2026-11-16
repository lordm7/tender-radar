"""The web app (FastAPI) and the page render functions.

Pages are rendered by plain functions (render_home, render_dashboard, …) that
return HTML strings. The FastAPI routes call them for the live app, and the
static exporter calls the same functions with static_files=True to build the
free public demo, so both always look the same.

Every page exists in two languages, one language per page: /en/… and /ar/…
(Arabic is fully right-to-left). Each company's pages live under
/<lang>/c/<company id>/. Old links without a language redirect to English.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup, escape
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
from tender_radar.web import i18n

STATIC_DIR = Path(__file__).parent / "static"
SAMPLE_BOOKLET = "sample_booklet.pdf"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
GITHUB_URL = "https://github.com/lordm7/tender-radar"
LINKEDIN_URL = "https://www.linkedin.com/"  # placeholder until the owner's profile URL is added
AUTHOR = "Mohammed Alzalam"
EVAL_AGREEMENT = "26 / 26"  # scripts/eval_matching.py with Gemini, 2026-11-16 (README "How good is the matching?")
CLOSING_SOON_DAYS = 7
LANG_COOKIE = "tr_lang"

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


def deadline_label(deadline: date | None, today: date, lang: str = "en") -> str:
    return i18n.days_label(lang, None if deadline is None else (deadline - today).days)


def radar_point(reference: str, score: int | None) -> tuple[float, float]:
    """Where a tender's dot sits on the radar (an SVG viewBox of 0-100, centre 50,50).

    Distance from the centre = 100 - score (scaled to fit), so better fits sit
    closer to the middle. The angle comes from the reference number's hash, so
    a tender always lands in the same place and screenshots are stable.
    """
    radius = (100 - score) * 0.45 if score is not None else 46
    angle = math.radians(int(hashlib.sha256(reference.encode("utf-8")).hexdigest()[:8], 16) % 360)
    return round(50 + radius * math.cos(angle), 2), round(50 + radius * math.sin(angle), 2)


# --- links ---------------------------------------------------------------------

def _page_path(page: tuple, static_files: bool) -> str:
    """A page's path inside its language folder, e.g. ("tender", "c1", "123") -> c/c1/tenders/123."""
    kind, *args = page
    if static_files:
        paths = {
            "home": lambda: "index.html",
            "companies": lambda: "companies.html",
            "dashboard": lambda c: f"c/{c}/index.html",
            "tender": lambda c, ref: f"c/{c}/tenders/{tender_slug(ref)}.html",
            "brief_sample": lambda: "briefs/sample.html",
        }
    else:
        paths = {
            "home": lambda: "",
            "companies": lambda: "companies",
            "dashboard": lambda c: f"c/{c}/",
            "tender": lambda c, ref: f"c/{c}/tenders/{ref}",
            "profile": lambda c: f"c/{c}/profile",
            "reader": lambda: "reader",
            "brief_sample": lambda: "briefs/sample",
            "brief": lambda i: f"briefs/{i}",
            "ask": lambda i: f"briefs/{i}/ask",
        }
    return paths[kind](*args)


@dataclass
class Links:
    """Where links point, for one page in one language.

    static_files: the exported demo, where every page is a relative .html file.
    read_only: hide everything that changes data (profile editor, booklet upload).
    The two are separate because a read-only *server* still uses normal routes.
    `page` is the current page, so switch() can give the same page in the other language.
    """

    lang: str
    static_files: bool
    read_only: bool
    company: str | None = None  # the company whose pages we are on, if any
    page: tuple = ("home",)
    only_company: str | None = None  # set when there is exactly one company
    companies_list: list[tuple[str, str]] = field(default_factory=list)  # (id, name in this language)

    def _url(self, page: tuple, lang: str | None = None) -> str:
        lang = lang or self.lang
        path = _page_path(page, self.static_files)
        if self.static_files:
            here = _page_path(self.page, True)
            return "../" * (here.count("/") + 1) + f"{lang}/{path}"
        return f"/{lang}/{path}"

    @property
    def root(self) -> str:
        """Prefix that reaches the site root (static files live there)."""
        return "../" * (_page_path(self.page, True).count("/") + 1) if self.static_files else "/"

    def static(self, name: str) -> str:
        return f"{self.root}static/{name}"

    def home(self) -> str:
        return self._url(("home",))

    def companies(self) -> str:
        return self._url(("companies",))

    def demo(self) -> str:
        """The "Live demo" target: the chooser, or the dashboard when there is one company."""
        return self.dashboard_of(self.only_company) if self.only_company else self.companies()

    def matches(self) -> str:
        """The current company's matches, or the demo entry point."""
        return self.dashboard_of(self.company) if self.company else self.demo()

    def dashboard_of(self, company: str) -> str:
        return self._url(("dashboard", company))

    def tender(self, reference: str) -> str:
        return self._url(("tender", self.company, reference))

    def sample_brief(self) -> str:
        return self._url(("brief_sample",))

    def brief(self, brief_id: int) -> str:
        return self._url(("brief", brief_id))

    def ask(self, brief_id: int) -> str:
        return self._url(("ask", brief_id))

    def profile(self) -> str:
        return self._url(("profile", self.company))

    def reader(self) -> str:
        return self._url(("reader",))

    def switch(self) -> str:
        """This same page in the other language."""
        return self._url(self.page, i18n.other(self.lang))


def _links(
    lang: str,
    read_only: bool,
    static_files: bool,
    page: tuple,
    company: str | None = None,
    session: Session | None = None,
) -> Links:
    profiles = list_profiles(session) if session is not None else []
    return Links(
        lang=lang,
        static_files=static_files,
        read_only=read_only or static_files,
        company=company,
        page=page,
        only_company=profiles[0].id if len(profiles) == 1 else None,
        companies_list=[(p.id, company_name(p, lang)[0]) for p in profiles],
    )


# --- page data -------------------------------------------------------------------

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


def tender_text(tender: Tender, field_name: str, lang: str) -> tuple[str, bool]:
    """(text, is_arabic_original) for a tender's title/agency/description on a page in `lang`."""
    arabic = getattr(tender, field_name)
    if lang == "ar":
        return arabic, False
    english = getattr(tender, f"{field_name}_en")
    return (english, False) if english else (arabic, True)


def company_name(profile: CompanyProfile, lang: str) -> tuple[str, bool]:
    """(name, is_original). Arabic pages fall back to the English name, marked as such."""
    if lang == "ar":
        return (profile.name_ar, False) if profile.name_ar else (profile.name, True)
    return profile.name, False


def reasons(row_match: MatchResult | None, lang: str) -> list[str]:
    """The AI or rule reasons, in the page language only."""
    if row_match is None:
        return []
    if row_match.status == "unscored":
        return [i18n.t(lang, "ai_retry")]
    if row_match.status == "filtered_out":
        return [i18n.rule_reason(lang, r) for r in row_match.reasons_en]
    return row_match.reasons_en if lang == "en" else row_match.reasons_ar


def tender_region(tender: Tender) -> tuple[str | None, bool]:
    """(region, inferred_from_agency_name)."""
    if tender.region:
        return tender.region, False
    inferred = infer_region(tender.agency)
    return inferred, inferred is not None


def booklet_label(tender: Tender, lang: str) -> str:
    if tender.booklet_price_sar is None:
        return "—"
    return i18n.t(lang, "free") if tender.booklet_price_sar == 0 else i18n.fmt_sar(lang, tender.booklet_price_sar)


def _orig(text: str, original: bool, lang: str, tag: bool = True) -> Markup:
    """Show `text`; if it is the untranslated original, mark its language and tag it."""
    if not original:
        return escape(text)
    source = "en" if text.isascii() else "ar"
    direction = "rtl" if source == "ar" else "ltr"
    html = f'<span class="orig" lang="{source}" dir="{direction}">{escape(text)}</span>'
    if tag and source == "ar":
        html += f' <span class="orig-tag">{escape(i18n.t(lang, "arabic_original"))}</span>'
    return Markup(html)


def _ctx(lang: str, links: Links, today: date, **extra) -> dict:
    """What every template gets: the language helpers and the links."""
    return {
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
        "t": lambda key, **fmt: i18n.t(lang, key, **fmt),
        "vocab": lambda value: i18n.vocab(lang, value),
        "days": lambda d: i18n.days_label(lang, d),
        "fmt_date": lambda d: i18n.fmt_date(lang, d),
        "fmt_sar": lambda v: i18n.fmt_sar(lang, v),
        "orig": lambda text, original, tag=True: _orig(text, original, lang, tag),
        "links": links,
        "today": today,
        "author": AUTHOR,
        "github_url": GITHUB_URL,
        "linkedin_url": LINKEDIN_URL,
        "has_sample_brief": False,
        **extra,
    }


def _tender_card(row: Row, links: Links, lang: str) -> dict:
    """Everything the matches page shows about one tender, in the page language."""
    t = row.tender
    title, title_orig = tender_text(t, "title", lang)
    agency, agency_orig = tender_text(t, "agency", lang)
    score = row.match.score if row.match and row.match.status == "scored" else None
    found = reasons(row.match, lang)
    x, y = radar_point(t.reference, score)
    return {
        "ref": t.reference,
        "score": score,
        "title": title,
        "title_orig": title_orig,
        "agency": agency,
        "agency_orig": agency_orig,
        "agency_raw": t.agency,
        "reason": found[0] if found else "",
        "reasons": found,
        "days": row.days_left,
        "days_label": i18n.days_label(lang, row.days_left),
        "closes": i18n.fmt_date(lang, t.deadline),
        "booklet": booklet_label(t, lang),
        "inquiries": i18n.t(lang, "until", date=i18n.fmt_date(lang, t.inquiry_deadline)) if t.inquiry_deadline else "—",
        "url": links.tender(t.reference),
        "x": x,
        "y": y,
        "soon": row.days_left is not None and 0 <= row.days_left <= CLOSING_SOON_DAYS,
    }


def _radar_json(cards: list[dict]) -> Markup:
    """Data for app.js, embedded in the page (no extra request, works on GitHub Pages)."""
    keys = ("ref", "score", "title", "title_orig", "reason", "closes", "days_label", "booklet", "inquiries", "url")
    payload = json.dumps([{k: c[k] for k in keys} for c in cards], ensure_ascii=False)
    return Markup(payload.replace("<", "\\u003c"))  # never let data close the <script> tag


def _has_sample(session: Session) -> bool:
    return latest_brief(session, SAMPLE_BOOKLET) is not None


# --- render functions ------------------------------------------------------------

def render_home(session: Session, today: date, lang: str = "en", static_files: bool = False) -> str:
    """The home / about page. Always public-only: it is the page recruiters see."""
    profiles = list_profiles(session)
    public = [t for t in list_tenders(session) if is_public(t)]
    total_checks = filtered_checks = 0
    for p in profiles:
        results, filtered = _rows(session, p, today, public_only=True)
        total_checks += len(results) + len(filtered)
        filtered_checks += len(filtered)
    links = _links(lang, True, static_files, ("home",), session=session)
    preview = None
    if profiles:
        first = profiles[0]
        results, filtered = _rows(session, first, today, public_only=True)
        preview_links = _links(lang, True, static_files, ("home",), first.id, session)
        preview = {
            "cards": [_tender_card(r, preview_links, lang) for r in results],
            "faint": [radar_point(r.tender.reference, None) for r in filtered],
            "filtered": len(filtered),
            "closing": sum(1 for r in results if r.days_left is not None and 0 <= r.days_left <= CLOSING_SOON_DAYS),
        }
    stats = {
        "screened": len(public),
        "filtered_pct": round(100 * filtered_checks / total_checks) if total_checks else 0,
        "agreement": EVAL_AGREEMENT,
    }
    return templates.get_template("home.html").render(
        stats=stats, preview=preview, **_ctx(lang, links, today, has_sample_brief=_has_sample(session))
    )


def render_companies(
    session: Session, today: date, read_only: bool, static_files: bool = False, lang: str = "en"
) -> str:
    """The company chooser: one card per company with its best matches."""
    cards = []
    for profile in list_profiles(session):
        results, _filtered = _rows(session, profile, today, public_only=read_only or static_files)
        scored = [r.match.score for r in results if r.match and r.match.status == "scored"]
        activities = [i18n.vocab(lang, a) for a in profile.activities]
        cards.append({
            "profile": profile,
            "name": company_name(profile, lang),
            "activities": [text for text, original in activities if not original],
            "count": len(results),
            "best": max(scored, default=None),
        })
    links = _links(lang, read_only, static_files, ("companies",), session=session)
    return templates.get_template("companies.html").render(
        cards=cards, **_ctx(lang, links, today, has_sample_brief=_has_sample(session))
    )


def render_dashboard(
    session: Session, profile: CompanyProfile, today: date, read_only: bool, static_files: bool = False, lang: str = "en"
) -> str:
    results, filtered = _rows(session, profile, today, public_only=read_only or static_files)
    links = _links(lang, read_only, static_files, ("dashboard", profile.id), profile.id, session)
    cards = [_tender_card(r, links, lang) for r in results]
    filtered_cards = [_tender_card(r, links, lang) for r in filtered]
    agencies = sorted({(c["agency_raw"], c["agency"], c["agency_orig"]) for c in cards}, key=lambda a: a[1])
    regions = {tender_region(r.tender)[0] for r in results} - {None}
    stats = {
        "worth": len(results),
        "filtered": len(filtered),
        "closing": sum(1 for c in cards if c["soon"]),
        "regions": len(regions),
    }
    return templates.get_template("dashboard.html").render(
        profile=profile,
        name=company_name(profile, lang),
        cards=cards,
        filtered=filtered_cards,
        faint=[(c["x"], c["y"]) for c in filtered_cards],
        agencies=agencies,
        stats=stats,
        data=_radar_json(cards),
        **_ctx(lang, links, today, has_sample_brief=_has_sample(session)),
    )


def render_tender(
    session: Session,
    ref: str,
    profile: CompanyProfile,
    today: date,
    read_only: bool,
    static_files: bool = False,
    lang: str = "en",
) -> str | None:
    tender = get_tender(session, ref)
    if tender is None or ((read_only or static_files) and not is_public(tender)):
        return None
    match = next((m for m in list_matches(session, profile.id) if m.tender_reference == ref), None)
    links = _links(lang, read_only, static_files, ("tender", profile.id, ref), profile.id, session)
    region, inferred = tender_region(tender)
    description, description_orig = tender_text(tender, "description", lang)
    return templates.get_template("tender.html").render(
        tender=tender,
        match=match,
        profile=profile,
        name=company_name(profile, lang),
        title=tender_text(tender, "title", lang),
        agency=tender_text(tender, "agency", lang),
        description="" if description_orig else description,  # English pages hide untranslated descriptions
        reasons=reasons(match, lang),
        region=i18n.vocab(lang, region) if region else None,
        region_inferred=inferred,
        days_label=deadline_label(tender.deadline, today, lang),
        booklet=booklet_label(tender, lang),
        **_ctx(lang, links, today, has_sample_brief=_has_sample(session)),
    )


def _lines(text: str) -> list[str]:
    """Textarea → list: one item per line, blanks dropped."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _number(text: str) -> float | None:
    text = text.strip().replace(",", "")
    return float(text) if text else None


def render_profile_form(
    profile: CompanyProfile, form: dict | None = None, error: str | None = None, lang: str = "en",
    session: Session | None = None,
) -> str:
    values = form or {
        "name": profile.name,
        "name_ar": profile.name_ar or "",
        "activities": "\n".join(profile.activities),
        "keywords": "\n".join(profile.keywords),
        "certifications": "\n".join(profile.certifications),
        "regions": "\n".join(profile.regions),
        "excluded_agencies": "\n".join(profile.excluded_agencies),
        "min_value_sar": "" if profile.min_value_sar is None else f"{profile.min_value_sar:.0f}",
        "max_value_sar": "" if profile.max_value_sar is None else f"{profile.max_value_sar:.0f}",
    }
    links = _links(lang, False, False, ("profile", profile.id), profile.id, session)
    return templates.get_template("profile.html").render(
        profile=profile, name=company_name(profile, lang), values=values, error=error,
        **_ctx(lang, links, date.today()),
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
    lang: str = "en",
    session: Session | None = None,
) -> str:
    """Brief page with its "Ask the booklet" questions. The static demo shows the
    stored answers for the sample booklet without the form."""
    page = ("brief", brief_id) if brief_id is not None and not static_files else ("brief_sample",)
    if filename == SAMPLE_BOOKLET:
        page = ("brief_sample",)
    links = _links(lang, read_only, static_files, page, session=session)
    text, original = brief.in_lang(lang)
    return templates.get_template("brief.html").render(
        brief=brief, text=text, original=original, filename=filename, qa=qa or [], brief_id=brief_id,
        can_ask=can_ask and not links.read_only and brief_id is not None, ask_error=ask_error,
        **_ctx(lang, links, date.today()),
    )


def render_reader(profiles: list[CompanyProfile], error: str | None = None, lang: str = "en", session: Session | None = None) -> str:
    links = _links(lang, False, False, ("reader",), session=session)
    return templates.get_template("reader.html").render(
        error=error, profiles=[(p.id, company_name(p, lang)[0]) for p in profiles],
        max_mb=MAX_UPLOAD_BYTES // (1024 * 1024), **_ctx(lang, links, date.today()),
    )


# --- the app -------------------------------------------------------------------------

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

    def check_lang(lang: str) -> None:
        if lang not in i18n.LANGS:
            raise HTTPException(404, "Unknown language")

    def with_profile(profile_id: str, fn: Callable[[Session, CompanyProfile], str | None]) -> str | None:
        with session_scope(engine) as s:
            profile = get_profile(s, profile_id)
            if profile is None:
                raise HTTPException(404, "No company with this id")
            return fn(s, profile)

    def get_ai() -> LLMProvider:
        return provider if provider is not None else get_provider(settings)

    @app.middleware("http")
    async def remember_language(request: Request, call_next):
        """A page in /en/ or /ar/ remembers its language, so "/" can return to it."""
        response = await call_next(request)
        first = request.url.path.strip("/").split("/", 1)[0]
        if first in i18n.LANGS and response.status_code < 400:
            response.set_cookie(LANG_COOKIE, first, max_age=365 * 24 * 3600, samesite="lax")
        return response

    @app.get("/")
    def root(request: Request):
        lang = request.cookies.get(LANG_COOKIE)
        return RedirectResponse(f"/{lang if lang in i18n.LANGS else 'en'}/", status_code=307)

    # Links from before the language prefix (README, bookmarks) keep working; 307 keeps POSTs.
    @app.api_route("/c/{rest:path}", methods=["GET", "POST"])
    def old_company_link(rest: str, request: Request):
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"/en/c/{rest}{query}", status_code=307)

    @app.api_route("/briefs/{rest:path}", methods=["GET", "POST"])
    def old_brief_link(rest: str):
        return RedirectResponse(f"/en/briefs/{rest}", status_code=307)

    @app.api_route("/reader", methods=["GET", "POST"])
    def old_reader_link():
        return RedirectResponse("/en/reader", status_code=307)

    @app.get("/{lang}/", response_class=HTMLResponse)
    def home(lang: str) -> str:
        check_lang(lang)
        with session_scope(engine) as s:
            return render_home(s, current_day(), lang)

    @app.get("/{lang}/companies", response_class=HTMLResponse)
    def companies(lang: str):
        check_lang(lang)
        with session_scope(engine) as s:
            profiles = list_profiles(s)
            if not profiles:
                raise HTTPException(503, "No company profile yet. Run: python -m tender_radar seed")
            if len(profiles) == 1:
                return RedirectResponse(f"/{lang}/c/{profiles[0].id}/", status_code=307)
            return HTMLResponse(render_companies(s, current_day(), read_only, lang=lang))

    @app.get("/{lang}/c/{profile_id}/", response_class=HTMLResponse)
    def dashboard(lang: str, profile_id: str) -> str:
        check_lang(lang)
        return with_profile(profile_id, lambda s, p: render_dashboard(s, p, current_day(), read_only, lang=lang))

    @app.get("/{lang}/c/{profile_id}/tenders/{reference}", response_class=HTMLResponse)
    def tender_page(lang: str, profile_id: str, reference: str) -> str:
        check_lang(lang)
        html = with_profile(profile_id, lambda s, p: render_tender(s, reference, p, current_day(), read_only, lang=lang))
        if html is None:
            raise HTTPException(404, "Tender not found")
        return html

    def brief_html(lang: str, brief_id: int, ask_error: str | None = None) -> str | None:
        with session_scope(engine) as s:
            brief = get_brief(s, brief_id)
            if brief is None:
                return None
            return render_brief(
                brief, latest_brief_filename(s, brief_id) or "", read_only, qa=list_answers(s, brief_id, lang=lang),
                brief_id=brief_id, can_ask=get_pages(s, brief_id) is not None, ask_error=ask_error, lang=lang,
                session=s,
            )

    @app.get("/{lang}/briefs/sample", response_class=HTMLResponse)
    def sample_brief(lang: str) -> str:
        check_lang(lang)
        with session_scope(engine) as s:
            brief_id = latest_brief_id(s, SAMPLE_BOOKLET)
        if brief_id is None:
            raise HTTPException(404, "No sample brief yet. Run: python -m tender_radar brief data/seed/sample_booklet.pdf")
        return brief_html(lang, brief_id)

    @app.get("/{lang}/briefs/{brief_id}", response_class=HTMLResponse)
    def brief_page(lang: str, brief_id: int) -> str:
        check_lang(lang)
        html = brief_html(lang, brief_id)
        if html is None:
            raise HTTPException(404, "Brief not found")
        return html

    if not read_only:

        def reader_error(lang: str, key: str, status: int, **fmt) -> HTMLResponse:
            with session_scope(engine) as s:
                html = render_reader(list_profiles(s), i18n.t(lang, key, **fmt), lang=lang, session=s)
            return HTMLResponse(html, status_code=status)

        @app.get("/{lang}/reader", response_class=HTMLResponse)
        def reader_page(lang: str) -> str:
            check_lang(lang)
            with session_scope(engine) as s:
                return render_reader(list_profiles(s), lang=lang, session=s)

        @app.post("/{lang}/reader")
        def reader_upload(lang: str, file: UploadFile = File(...), profile_id: str = Form("")):
            # A plain `def` route runs in a worker thread, so reading the PDF and
            # waiting for the AI does not freeze the app for other visitors.
            check_lang(lang)
            content = file.file.read(MAX_UPLOAD_BYTES + 1)
            if not content:
                return reader_error(lang, "err_empty_file", 400)
            if len(content) > MAX_UPLOAD_BYTES:
                return reader_error(lang, "err_too_big", 413, mb=MAX_UPLOAD_BYTES // (1024 * 1024))
            filename = Path(file.filename or "booklet.pdf").name
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "upload.pdf"
                path.write_bytes(content)
                try:
                    pages = extract_pages(path)
                except UnreadablePDF as exc:
                    return reader_error(lang, exc.code, 400)
            with session_scope(engine) as s:
                profiles = list_profiles(s)
                profile = next((p for p in profiles if p.id == profile_id), profiles[0] if profiles else None)
                if profile is None:
                    raise HTTPException(503, "No company profile yet. Run: python -m tender_radar seed")
                try:
                    brief = build_brief(pages, profile, get_ai())
                except (AIError, ValidationError):
                    return HTMLResponse(
                        render_reader(profiles, i18n.t(lang, "err_reader_ai"), lang=lang, session=s), status_code=502
                    )
                brief_id = save_brief(s, filename, brief, pages=pages)
            return RedirectResponse(f"/{lang}/briefs/{brief_id}", status_code=303)

        @app.post("/{lang}/briefs/{brief_id}/ask", response_class=HTMLResponse)
        def ask_booklet(lang: str, brief_id: int, question: str = Form("")):
            check_lang(lang)
            with session_scope(engine) as s:
                pages = get_pages(s, brief_id)
            if pages is None:
                raise HTTPException(404, i18n.t(lang, "no_brief_text"))
            question = question.strip()[:500]
            if not question:
                return HTMLResponse(brief_html(lang, brief_id, i18n.t(lang, "ask_empty")), status_code=400)
            try:
                answer = answer_question(question, pages, get_ai())
            except (AIError, ValidationError, ValueError):
                return HTMLResponse(brief_html(lang, brief_id, i18n.t(lang, "ask_failed")), status_code=502)
            with session_scope(engine) as s:
                save_answer(s, brief_id, question, answer, lang=lang)
            # Redirect after POST, so reloading the page does not ask (and spend an AI call) again.
            return RedirectResponse(f"/{lang}/briefs/{brief_id}#ask", status_code=303)

        @app.get("/{lang}/c/{profile_id}/profile", response_class=HTMLResponse)
        def profile_page(lang: str, profile_id: str) -> str:
            check_lang(lang)
            return with_profile(profile_id, lambda s, p: render_profile_form(p, lang=lang, session=s))

        @app.post("/{lang}/c/{profile_id}/profile")
        def profile_save(
            lang: str,
            profile_id: str,
            name: str = Form(...),
            name_ar: str = Form(""),
            activities: str = Form(""),
            keywords: str = Form(""),
            certifications: str = Form(""),
            regions: str = Form(""),
            excluded_agencies: str = Form(""),
            min_value_sar: str = Form(""),
            max_value_sar: str = Form(""),
        ):
            check_lang(lang)
            form = dict(
                name=name, name_ar=name_ar, activities=activities, keywords=keywords, certifications=certifications,
                regions=regions, excluded_agencies=excluded_agencies,
                min_value_sar=min_value_sar, max_value_sar=max_value_sar,
            )
            with session_scope(engine) as s:
                current = get_profile(s, profile_id)
                if current is None:
                    raise HTTPException(404, "No company with this id")
                try:
                    updated = CompanyProfile(
                        id=current.id, name=name.strip(), name_ar=name_ar.strip() or None,
                        activities=_lines(activities), keywords=_lines(keywords),
                        certifications=_lines(certifications), regions=_lines(regions),
                        excluded_agencies=_lines(excluded_agencies),
                        min_value_sar=_number(min_value_sar), max_value_sar=_number(max_value_sar),
                    )
                except ValidationError:
                    message = i18n.t(lang, "err_value_range")
                    return HTMLResponse(render_profile_form(current, form, message, lang, s), status_code=422)
                except ValueError:
                    return HTMLResponse(render_profile_form(current, form, i18n.t(lang, "err_numbers"), lang, s), status_code=422)
                save_profile(s, updated)
            # Saved first, so a missing AI setup never throws away the user's edits.
            try:
                ai = get_ai()
            except ValueError:
                with session_scope(engine) as s:
                    return HTMLResponse(render_profile_form(updated, form, i18n.t(lang, "saved_no_ai"), lang, s))
            with session_scope(engine) as s:
                run_matching(s, updated, ai, current_day())
            return RedirectResponse(f"/{lang}/c/{updated.id}/", status_code=303)

    app.state.engine = engine
    app.state.settings = settings
    app.state.read_only = read_only
    app.state.current_day = current_day
    app.state.with_profile = with_profile
    return app
