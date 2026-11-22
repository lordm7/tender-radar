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
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup, escape
from pydantic import ValidationError
from sqlalchemy.orm import Session

from tender_radar.ai.provider import AIError, LLMProvider, get_provider
from tender_radar.calendar_ics import tender_ics
from tender_radar.db import init_db, make_engine, session_scope
from tender_radar.matching.rules import check_rules
from tender_radar.matching.scorer import WEIGHTS, run_matching, total_score
from tender_radar.models import BookletAnswer, BookletBrief, CompanyProfile, MatchResult, ScoreParts, Tender
from tender_radar.reader.ask import answer_question
from tender_radar.reader.brief import build_brief
from tender_radar.reader.pdf_text import UnreadablePDF, extract_pages
from tender_radar.reader.profile_extract import extract_profile, new_profile_id
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
LINKEDIN_URL = "https://www.linkedin.com/in/mohammed-alzalam"
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
            "add_company": lambda: "companies/new.html",
            "how": lambda: "how.html",
            "dashboard": lambda c: f"c/{c}/index.html",
            "tender": lambda c, ref: f"c/{c}/tenders/{tender_slug(ref)}.html",
            "calendar": lambda ref: f"calendar/{tender_slug(ref)}.ics",
            "brief_sample": lambda: "briefs/sample.html",
        }
    else:
        paths = {
            "home": lambda: "",
            "companies": lambda: "companies",
            "add_company": lambda: "companies/new",
            "how": lambda: "how",
            "add_company_extract": lambda: "companies/new/extract",
            "dashboard": lambda c: f"c/{c}/",
            "tender": lambda c, ref: f"c/{c}/tenders/{ref}",
            "calendar": lambda ref: f"calendar/{ref}.ics",
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

    def add_company(self) -> str:
        return self._url(("add_company",))

    def how(self) -> str:
        return self._url(("how",))

    def add_company_extract(self) -> str:
        return self._url(("add_company_extract",))

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

    def calendar(self, reference: str) -> str:
        return self._url(("calendar", reference))

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
    verdict = verdict_key(row.match)
    return {
        "verdict": verdict,
        "verdict_text": i18n.t(lang, verdict) if verdict else "",
        "value": i18n.fmt_sar(lang, t.estimated_value_sar) if t.estimated_value_sar else "",
        "parts": score_parts(row.match, lang),
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
    keys = ("ref", "score", "title", "title_orig", "reason", "closes", "days_label", "booklet", "inquiries", "url",
            "verdict", "verdict_text", "parts")
    payload = json.dumps([{k: c[k] for k in keys} for c in cards], ensure_ascii=False)
    return Markup(payload.replace("<", "\\u003c"))  # never let data close the <script> tag


def _has_sample(session: Session) -> bool:
    return latest_brief(session, SAMPLE_BOOKLET) is not None


# --- render functions ------------------------------------------------------------

def render_home(session: Session, today: date, lang: str = "en", static_files: bool = False) -> str:
    """The home / about page. Always public-only: it is the first page visitors see."""
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
            # Same numbers as the matches page header (verdict bands).
            "bid": sum(1 for r in results if verdict_key(r.match) == "verdict_bid"),
            "consider": sum(1 for r in results if verdict_key(r.match) == "verdict_consider"),
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
    stats = {
        "bid": sum(1 for c in cards if c["verdict"] == "verdict_bid"),
        "consider": sum(1 for c in cards if c["verdict"] == "verdict_consider"),
        "filtered": len(filtered),
        "closing": sum(1 for c in cards if c["soon"]),
    }
    # The list is grouped by verdict, in the order of the score bands; empty groups are left out.
    groups = []
    for key in ("verdict_bid", "verdict_consider", "verdict_skip", None):
        members = [c for c in cards if c["verdict"] == key]
        if members:
            groups.append({"key": key or "unscored", "label": i18n.t(lang, key or "group_unscored"), "cards": members})
    return templates.get_template("dashboard.html").render(
        profile=profile,
        name=company_name(profile, lang),
        cards=cards,
        groups=groups,
        filtered=filtered_cards,
        faint=[(c["x"], c["y"]) for c in filtered_cards],
        agencies=agencies,
        stats=stats,
        data=_radar_json(cards),
        **_ctx(lang, links, today, has_sample_brief=_has_sample(session)),
    )


def score_parts(match: MatchResult | None, lang: str) -> dict | None:
    """The AI's fit / ability / risk for the tender page, in `lang`; None for older scores without parts."""
    if match is None or match.status != "scored" or match.parts is None:
        return None
    p = match.parts
    rows = [
        {"key": key, "value": getattr(p, key), "weight": round(WEIGHTS[key] * 100), "text": getattr(p, f"{key}_{lang}")}
        for key in ("fit", "ability", "risk")
    ]
    blocker = p.blocker_text(lang)
    if blocker is None and p.has_blocker:  # the AI wrote the blocker in the other language only
        blocker = i18n.t(lang, "blocker_unnamed")
    return {
        "rows": rows,
        "blocker": blocker,
        "prepare": p.prepare_en if lang == "en" else p.prepare_ar,
    }


def verdict_key(match: MatchResult | None) -> str | None:
    """The plain-words call for a tender, using the same bands as the score colours (80+, 50+)."""
    if match is None or match.status == "unscored":
        return None
    if match.status == "filtered_out" or match.score is None or match.score < 50:
        return "verdict_skip"
    return "verdict_bid" if match.score >= 80 else "verdict_consider"


def _tr(lang: str, key: str, **parts) -> Markup:
    """Like i18n.t, but the inserted parts may be Markup (e.g. an "original" span); plain parts are escaped."""
    return Markup(escape(i18n.STRINGS[lang][key])).format(**parts)


def profile_check(tender: Tender, profile: CompanyProfile, today: date, lang: str) -> list[dict]:
    """Every free rule's result for this tender, as page rows: {"status": pass|fail|unknown, "text"}."""
    def sar(value: float) -> str:
        return i18n.fmt_sar(lang, value)

    rows = []
    for c in check_rules(tender, profile, today):
        state = {True: "ok", False: "bad", None: "unknown"}[c.passed]
        parts: dict = {}
        if c.name == "value" and c.passed is not None:
            low, high = c.detail["min"], c.detail["max"]
            parts["value"] = sar(c.detail["value"])
            if low is None and high is None:
                state = "any"
            elif low is not None and high is not None:
                parts["range"] = i18n.t(lang, "range_both", min=sar(low), max=sar(high))
            elif low is not None:
                parts["range"] = i18n.t(lang, "range_min", min=sar(low))
            else:
                parts["range"] = i18n.t(lang, "range_max", max=sar(high))
        elif c.name == "region" and c.passed is not None:
            if c.detail["region"] is None:
                state = "all"
            else:
                parts["region"] = _orig(*i18n.vocab(lang, c.detail["region"]), lang, tag=False)
        elif c.name == "keywords" and c.passed:
            # One chip per term: no commas, so mixed Arabic/English terms never reorder each other.
            terms = [_orig(term, (lang == "en") != term.isascii(), lang, tag=False) for term in c.detail["terms"]]
            parts["terms"] = Markup(" ").join(Markup('<span class="term">{}</span>').format(x) for x in terms)
        rows.append({
            "status": {True: "pass", False: "fail", None: "unknown"}[c.passed],
            "text": _tr(lang, f"check_{c.name}_{state}", **parts),
        })
    return rows


def tender_timeline(tender: Tender, today: date, lang: str) -> dict | None:
    """Published → questions close → deadline on one bar, with today's position (all in % of the bar)."""
    if tender.deadline is None:
        return None
    start = min(d for d in (tender.published_on, today) if d is not None)
    end = max(tender.deadline, today)
    span = max((end - start).days, 1)

    def pct(d: date) -> float:
        return round(100 * (d - start).days / span, 1)

    dates = [("tl_published", tender.published_on), ("tl_inquiries", tender.inquiry_deadline), ("tl_deadline", tender.deadline)]
    points = [
        {"key": key, "pct": pct(d), "past": d < today, "date": i18n.fmt_date(lang, d)}
        for key, d in dates if d is not None
    ]
    return {"points": points, "today": pct(today)}


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
        verdict=verdict_key(match),
        parts=score_parts(match, lang),
        checks=profile_check(tender, profile, today, lang),
        timeline=tender_timeline(tender, today, lang),
        **_ctx(lang, links, today, has_sample_brief=_has_sample(session)),
    )


def score_formula(parts: ScoreParts) -> str:
    """The score sum written out with real numbers, e.g. "0.5 × 95 + 0.3 × 90 + 0.2 × (100 − 35) = 87.5 → 88"."""
    w = {k: f"{v:g}" for k, v in WEIGHTS.items()}
    exact = sum(round(WEIGHTS[k] * 10) * v for k, v in  # in tenths, like total_score
                (("fit", parts.fit), ("ability", parts.ability), ("risk", 100 - parts.risk)))
    return (f"{w['fit']} × {parts.fit} + {w['ability']} × {parts.ability} + {w['risk']} × (100 − {parts.risk})"
            f" = {exact // 10}.{exact % 10} → {total_score(parts)}")


def pipeline_story(session: Session, today: date, lang: str) -> dict | None:
    """Real numbers for the "How it works" page, and the best public tender traced step by step.

    The numbers are for the company of the traced tender (the free rules depend on the
    company's bidding profile). Only public seed tenders count, like every read-only view.
    """
    profiles = list_profiles(session)
    if not profiles:
        return None
    candidates = []  # (score, reference, profile, tender, match)
    for profile in profiles:
        for m in list_matches(session, profile.id):
            if m.status != "scored" or m.parts is None:
                continue
            tender = get_tender(session, m.tender_reference)
            closed = tender is not None and tender.deadline is not None and tender.deadline < today
            if tender is not None and is_public(tender) and not closed:  # a closed tender is no example
                candidates.append((-m.score, m.tender_reference, profile.id, profile, tender, m))
    candidates.sort(key=lambda c: c[:3])
    best = candidates[0] if candidates else None
    profile = best[3] if best else profiles[0]

    results, filtered = _rows(session, profile, today, public_only=True)
    scores = sorted((r.match.score for r in results if r.match and r.match.status == "scored"), reverse=True)
    counts = {
        "tenders": len(results) + len(filtered),
        "filtered": len(filtered),
        "scored": len(scores),
        "unscored": sum(1 for r in results if r.match and r.match.status == "unscored"),
        "top": scores[:3],
    }
    trace = None
    if best:
        _, ref, _, _, tender, match = best
        title, title_orig = tender_text(tender, "title", lang)
        trace = {
            "ref": ref,
            "profile_id": profile.id,
            "title": title,
            "title_orig": title_orig,
            "checks": profile_check(tender, profile, today, lang),
            "parts": score_parts(match, lang),
            # Only when today's formula gives the stored score (scores are not redone when WEIGHTS change).
            "formula": score_formula(match.parts) if total_score(match.parts) == match.score else None,
            "score": match.score,
            "verdict": verdict_key(match),
        }
    return {"company": company_name(profile, lang), "profile_id": profile.id, "counts": counts, "trace": trace}


# The "Built with" list on the How it works page (tool names stay in English on both pages).
BUILT_WITH = ["Python", "FastAPI", "Jinja", "SQLite", "SQLAlchemy", "Pydantic", "Gemini", "PyMuPDF", "GitHub Actions", "GitHub Pages"]


def render_how(session: Session, today: date, read_only: bool, static_files: bool = False, lang: str = "en") -> str:
    """The "How it works" page: the pipeline with real numbers and one traced tender (public data only)."""
    story = pipeline_story(session, today, lang)
    company = story["profile_id"] if story else None
    links = _links(lang, read_only, static_files, ("how",), company, session)
    # The company name may be in the other language (no Arabic name yet): mark it, like other originals.
    numbers_for = _tr(lang, "numbers_for", company=_orig(*story["company"], lang, tag=False)) if story else None
    return templates.get_template("how.html").render(
        story=story, numbers_for=numbers_for, built_with=BUILT_WITH, agreement=EVAL_AGREEMENT,
        **_ctx(lang, links, today, has_sample_brief=_has_sample(session)),
    )


def _lines(text: str) -> list[str]:
    """Textarea → list: one item per line, blanks dropped."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _number(text: str) -> float | None:
    text = text.strip().replace(",", "")
    return float(text) if text else None


PROFILE_FIELDS = (
    "name", "name_ar", "activities", "keywords", "certifications", "regions",
    "excluded_agencies", "min_value_sar", "max_value_sar",
)


def profile_from_form(profile_id: str, form: dict, lang: str) -> tuple[CompanyProfile | None, str | None]:
    """Profile form text -> (profile, None), or (None, error message in the page language)."""
    if not form.get("name", "").strip():
        return None, i18n.t(lang, "err_name")
    try:
        profile = CompanyProfile(
            id=profile_id, name=form["name"].strip(), name_ar=form.get("name_ar", "").strip() or None,
            activities=_lines(form.get("activities", "")), keywords=_lines(form.get("keywords", "")),
            certifications=_lines(form.get("certifications", "")), regions=_lines(form.get("regions", "")),
            excluded_agencies=_lines(form.get("excluded_agencies", "")),
            min_value_sar=_number(form.get("min_value_sar", "")), max_value_sar=_number(form.get("max_value_sar", "")),
        )
    except ValidationError:  # checked first: Pydantic's ValidationError is also a ValueError
        return None, i18n.t(lang, "err_value_range")
    except ValueError:
        return None, i18n.t(lang, "err_numbers")
    return profile, None


def render_add_company(
    session: Session,
    today: date,
    read_only: bool,
    static_files: bool = False,
    lang: str = "en",
    values: dict | None = None,
    error: str | None = None,
    prefilled: bool = False,
) -> str:
    """"Add your company": upload a profile PDF or type the details. Read-only = disabled preview."""
    links = _links(lang, read_only, static_files, ("add_company",), session=session)
    return templates.get_template("company_new.html").render(
        values=values or {f: "" for f in PROFILE_FIELDS}, error=error, prefilled=prefilled,
        max_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
        **_ctx(lang, links, today, has_sample_brief=_has_sample(session)),
    )


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

    @app.get("/{lang}/companies/new", response_class=HTMLResponse)
    def add_company_page(lang: str) -> str:
        # Shown in read-only mode too, as a disabled preview (the POST routes below are live-only).
        check_lang(lang)
        with session_scope(engine) as s:
            return render_add_company(s, current_day(), read_only, lang=lang)

    @app.get("/{lang}/how", response_class=HTMLResponse)
    def how_page(lang: str) -> str:
        check_lang(lang)
        with session_scope(engine) as s:
            return render_how(s, current_day(), read_only, lang=lang)

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

    @app.get("/{lang}/calendar/{reference}.ics")
    def tender_calendar(lang: str, reference: str) -> Response:
        """The tender's key dates as a calendar file ("Add to calendar")."""
        check_lang(lang)
        with session_scope(engine) as s:
            tender = get_tender(s, reference)
        if tender is None or tender.deadline is None or (read_only and not is_public(tender)):
            raise HTTPException(404, "No calendar for this tender")
        return Response(
            tender_ics(tender, lang), media_type="text/calendar; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="tender-{tender_slug(reference)}.ics"'},
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

        def read_pdf_upload(file: UploadFile) -> tuple[list[str] | None, tuple[str, int, dict] | None]:
            """Uploaded PDF -> (page texts, None), or (None, (error key, HTTP status, format values))."""
            content = file.file.read(MAX_UPLOAD_BYTES + 1)
            if not content:
                return None, ("err_empty_file", 400, {})
            if len(content) > MAX_UPLOAD_BYTES:
                return None, ("err_too_big", 413, {"mb": MAX_UPLOAD_BYTES // (1024 * 1024)})
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "upload.pdf"
                path.write_bytes(content)
                try:
                    return extract_pages(path), None
                except UnreadablePDF as exc:
                    return None, (exc.code, 400, {})

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
            pages, problem = read_pdf_upload(file)
            if problem is not None:
                key, status, fmt = problem
                return reader_error(lang, key, status, **fmt)
            filename = Path(file.filename or "booklet.pdf").name
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
                updated, error = profile_from_form(current.id, form, lang)
                if updated is None:
                    return HTMLResponse(render_profile_form(current, form, error, lang, s), status_code=422)
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

        @app.post("/{lang}/companies/new/extract", response_class=HTMLResponse)
        def add_company_extract(lang: str, file: UploadFile = File(...)):
            """Read a company-profile PDF and show the form pre-filled. Nothing is saved here."""
            check_lang(lang)

            def page(status: int, values: dict | None = None, error: str | None = None) -> HTMLResponse:
                with session_scope(engine) as s:
                    html = render_add_company(s, current_day(), False, lang=lang, values=values, error=error,
                                              prefilled=values is not None)
                return HTMLResponse(html, status_code=status)

            pages, problem = read_pdf_upload(file)
            if problem is not None:
                key, status, fmt = problem
                return page(status, error=i18n.t(lang, key, **fmt))
            try:
                draft = extract_profile(pages, get_ai())
            except (AIError, ValidationError, ValueError):  # AI down, bad answer, or AI not configured
                return page(502, error=i18n.t(lang, "err_extract_ai"))
            return page(200, values=draft.form_values())

        @app.post("/{lang}/companies/new")
        def add_company_save(
            lang: str,
            name: str = Form(""),
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
                new_id = new_profile_id(name, [p.id for p in list_profiles(s)])
                created, error = profile_from_form(new_id, form, lang)
                if created is None:
                    html = render_add_company(s, current_day(), False, lang=lang, values=form, error=error)
                    return HTMLResponse(html, status_code=422)
                save_profile(s, created)
            try:
                ai = get_ai()
            except ValueError:
                ai = None  # saved anyway; the company's matches fill in once AI is configured
            if ai is not None:
                with session_scope(engine) as s:
                    run_matching(s, created, ai, current_day())
            return RedirectResponse(f"/{lang}/c/{created.id}/", status_code=303)

    app.state.engine = engine
    app.state.settings = settings
    app.state.read_only = read_only
    app.state.current_day = current_day
    app.state.with_profile = with_profile
    return app
