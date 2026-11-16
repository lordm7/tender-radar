# Tender Radar Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Tender Radar the approved dark, calm, professional look, with one language per page (`/en/…`, `/ar/…`, Arabic fully RTL), a new home/about page and a radar matches page, in both the live app and the static demo.

**Architecture:**
- Keep FastAPI + Jinja + vanilla JS.
- A new `web/i18n.py` holds every UI string in both languages plus a lookup table for the fixed Etimad vocabulary.
- Every page route gets a `{lang}` prefix. The `Links` object knows the language and the current page, so it can build the "same page in the other language" link for the live app and the static files alike.
- English tender text comes from the seed data (hand-written) or from the existing scoring call (real imports). Briefs gain an optional English copy produced in the same AI call.

**Tech Stack:** Python 3.12+, FastAPI, Jinja2, SQLAlchemy 2, Pydantic 2, one hand-written CSS file, vanilla JS, inline SVG.

**Spec:** `docs/superpowers/specs/2026-11-15-tender-radar-redesign-design.md` (mockups in `docs/superpowers/specs/mockups/`)

## Global Constraints
- **No front-end framework.** No React and no JS build step. The radar uses no large libraries.
- **Zero running cost.** Tests never call a real AI (`FakeProvider`).
- **One language per page.** In English mode every visible word is English; in Arabic mode every visible word is Arabic and the page has `<html lang="ar" dir="rtl">`. Only two exceptions:
  - text without a translation, shown as the original inside `<span class="orig" lang="ar">…</span>` with an "Arabic original" tag
  - the values inside the Bidding profile form fields
- **Privacy:** `is_public()` still decides read-only and exported pages in both languages. The home page is always public-only, even in the live app.
- **Rename:** "Company profile" → "Bidding profile" / "ملف المنافسة".
- **Footer, verbatim:**
  - "Built by Mohammed Alzalam · AI & Automation Engineer, Riyadh"
  - GitHub link `https://github.com/lordm7/tender-radar`
  - LinkedIn: a placeholder until the user gives the URL
  - "Demo data is synthetic and shaped like public Etimad listings. Tender Radar is not affiliated with Etimad."
- **Hero copy, verbatim:**
  - eyebrow "Tender intelligence for Saudi B2B"
  - headline "Know which government tenders are worth bidding on."
- **Design tokens** come from the mockups: background `#070d18`, panels `#0b1424`, lines `#162033`/`#1d2b40`, text `#cbd5e1`, headings `#f8fafc`, muted `#8a96aa`, accent `#10b981`/`#34d399`, warning `#fbbf24`. Fonts: Inter + IBM Plex Sans Arabic (Google Fonts).
- **CSS uses logical properties** (`margin-inline-start`, `padding-inline`, `inset-inline-start`), so RTL mirrors automatically.
- **Old databases keep working.** `init_db` adds missing nullable columns (there are no migrations otherwise).

## Review Focus
1. **Endless re-scoring.** Writing `title_en`/`agency_en` back onto a tender must not change its content hash. Test: score twice, and the second run is fully cached.
2. **Old links.** Old bookmarks and README links (`/c/najd-digital/`, `/reader`, `/briefs/sample`) must still work. Test: they 307-redirect to `/en/…`, and POSTs survive.
3. **An existing `tender_radar.db` from before the redesign** (no new columns) must open without crashing. Test: create the old schema with raw SQL, run `init_db`, read tenders.
4. **Mixed languages on a page.** Ask-the-booklet Q&A in the wrong language and English rule reasons in Arabic mode both break the rule. Test: the language-rule scan over every exported page.
5. **The static demo's language switch and relative links** at every folder depth. Test: every `href` in every exported page resolves to an exported file.

---

### Task 1: Bilingual data, schema top-up, safe hashing

**Files:**
- Modify: `src/tender_radar/models.py`, `db.py`, `repository.py`
- Modify: `data/seed/tenders.json`, `data/seed/profile_*.json`
- Test: `tests/test_bilingual_data.py`

**Interfaces:**
- **Produces:**
  - `Tender.title_en: str | None`, `Tender.agency_en: str | None`, `Tender.description_en: str | None` (all default `None`)
  - `CompanyProfile.name_ar: str | None = None`
  - `tender_content_hash(t)` ignores the three `*_en` fields
  - `set_tender_english(session, ref: str, title_en: str | None, agency_en: str | None) -> None` writes only into fields that are empty
  - `init_db(engine)` adds missing nullable columns to existing tables
  - `QuestionRow.lang: str` (default `"en"`); `save_answer(session, brief_id, question, answer, lang="en")`; `list_answers(session, brief_id, lang: str | None = None)`
- **Upsert rule:** if the incoming tender has no `*_en` and the stored row has one, keep the stored value. The hash ignores these fields, so this tender stays "unchanged".

- [ ] **Step 1: write the failing tests:**
  - `test_english_fields_do_not_change_the_hash`
  - `test_set_tender_english_only_fills_empty_fields`
  - `test_reimport_keeps_english_title`
  - `test_init_db_adds_missing_columns_to_an_old_database` (raw `CREATE TABLE tenders(...)` without `title_en`, then `init_db`, then `list_tenders` works)
  - `test_every_seed_tender_and_profile_has_english_and_arabic_names`
  - `test_answers_filtered_by_language`
- [ ] **Step 2:** run them and see them fail.
- [ ] **Step 3:** implement. Add hand-written fictional English `title_en`/`agency_en`/`description_en` for all 30 seed tenders, and `name_ar` for both profiles ("نجد للحلول الرقمية", "البنيان للمقاولات والصيانة").
- [ ] **Step 4:** the full suite passes. Commit.

### Task 2: English title and agency from the scoring call

**Files:**
- Modify: `models.py` (`AIScore.title_en: str | None = None`, `AIScore.agency_en: str | None = None`), `prompts/score_tender.md`, `matching/scorer.py`
- Test: `tests/test_scorer.py`

- [ ] Write `test_scoring_stores_english_title_once` and `test_second_run_after_english_title_is_cached`. Then implement: after a successful score, `set_tender_english(...)`. Commit.

### Task 3: Bilingual booklet brief

**Files:**
- Modify: `models.py`, `prompts/booklet_brief.md`, `ai/provider.py` (fake default includes `en`)
- Test: `tests/test_reader.py`

**Interfaces:**
- **Produces:**
  - `BriefText(scope: str, deliverables, key_dates, eligibility, required_documents, evaluation_criteria, risks: list[str], go_no_go: list[ChecklistItem])`
  - `BookletBrief.en: BriefText | None = None`. The Arabic fields stay as they are, so old stored briefs still load.
  - `BookletBrief.in_lang(lang) -> tuple[BriefText-like, bool]` returns (the text to show, is_original). English with `en is None` returns the Arabic text and `True`.
- [ ] Write the tests: an old brief JSON without `en` loads, and `in_lang("en")` falls back to Arabic with the original flag. Then implement. Commit.

### Task 4: i18n module

**Files:**
- Create: `src/tender_radar/web/i18n.py`
- Test: `tests/test_i18n.py`

**Interfaces:**
- **Produces:**
  - `LANGS = ("en", "ar")`, `other(lang) -> str`
  - `t(lang, key, **fmt) -> str`; a missing key raises `KeyError`
  - `vocab(lang, value) -> tuple[str, bool]` returns (text, is_original), for activities, regions, tender types and certifications
  - `days_label(lang, days: int | None) -> str`
  - `fmt_date(lang, d) -> str` ("5 Jan 2027" / "5 يناير 2027")
  - `fmt_sar(lang, value) -> str`
  - `rule_reason(lang, reason: str) -> str`, which translates "deadline passed", "value outside range", "region not covered", "no keyword match", "excluded agency" and "matched: X"
- [ ] Tests: the EN and AR dictionaries have the same keys, every value in the AR dictionary has no Latin letters except the allow-list, `vocab` falls back with `True`, and the day and date labels work. Implement. Commit.

### Task 5: Language routes, Links, render functions, restyled pages

**Files:**
- Modify: `web/app.py`, `web/templates/*.html`
- Create: `web/templates/home.html`, `web/static/app.css`
- Test: `tests/test_web_*.py` (adapted), `tests/test_lang_routes.py`

**Interfaces:**
- **Produces:**
  - `Links(lang, static_files, read_only, company=None, page=("home",))` with methods `home()`, `companies()`, `demo()`, `dashboard_of(id)`, `tender(ref)`, `sample_brief()`, `brief(id)`, `ask(id)`, `reader()`, `profile()`, `static(name)` and `switch()`.
  - In static mode, `depth` comes from the page's file path (`en/index.html` = 1, `en/c/x/tenders/r.html` = 4).
  - Every `render_*` gets a `lang` parameter. New: `render_home(session, today, lang, static_files=False)`.
- **Routes:**
  - `/{lang}/`, `/{lang}/companies`, `/{lang}/c/{id}/`, `/{lang}/c/{id}/tenders/{ref}`, `/{lang}/c/{id}/profile` (GET/POST)
  - `/{lang}/reader` (GET/POST), `/{lang}/briefs/sample`, `/{lang}/briefs/{id}`, `/{lang}/briefs/{id}/ask` (POST)
  - An unknown language → 404.
  - `/` → 307 to `/{cookie tr_lang or en}/`.
  - Legacy `/c/{rest}`, `/reader`, `/briefs/{rest}` → 307 to `/en/…`.
  - A language page response sets the `tr_lang` cookie.
- [ ] Tests: the redirects (including a legacy POST), the cookie, `/ar/` has `dir="rtl"`, the switch link points to the same page, and the home page hides imported tenders even in the live app. Adapt the old tests to the new markup. Implement. Commit.

### Task 6: Matches page radar + selected panel + home preview

**Files:**
- Modify: `web/templates/dashboard.html`, `home.html`, `web/static/app.js`
- Test: `tests/test_web_dashboard.py`

**Interfaces:**
- **Radar geometry:** in `app.py`, `radar_point(reference: str, score: int | None) -> tuple[float, float]` on a 0–100 SVG viewBox.
  - radius = (100 − score) × 0.45 (filtered tenders: 46)
  - angle = int(sha256(ref)[:8], 16) mod 360
- **Embedded data:** the page embeds `<script type="application/json" id="tr-data">` with the page-language fields of each passed tender: `ref, score, title, reason, closes, days, booklet, inquiries, url`.
- **JS:** clicking a row or dot (or pressing Enter/Space on a dot) fills the selected panel without a reload. The filters work as before.
- [ ] Tests: `radar_point` is deterministic and a higher score sits closer to the centre, the JSON carries only page-language text, and the first tender is preselected in the HTML (so it works without JS). Implement. Commit.

### Task 7: Static export of both language trees

**Files:**
- Modify: `export/static_site.py`, `__main__.py` (SAMPLE_QUESTIONS per language, `ask --lang`)
- Test: `tests/test_export.py`, `tests/test_daily.py`

- **Layout:**
  - `index.html` (meta refresh + link to `en/index.html`)
  - `{lang}/index.html` (home), `{lang}/companies.html`, `{lang}/c/<id>/index.html`, `{lang}/c/<id>/tenders/<slug>.html`, `{lang}/briefs/sample.html`
  - `static/`
- [ ] Tests:
  - both trees exist
  - every relative `href`/`src` in every exported page resolves to a file
  - the language-rule scan passes on every page: an English page with `.orig` spans and `<head>` removed has no Arabic letters; an Arabic page's visible text has no Latin words outside the allow-list
  - no imported tender appears
- [ ] Implement, then commit.

### Task 8: Docs and visual check
- [ ] README (new URLs, screenshots if they can be taken), CLAUDE.md, the full suite, and a manual look at the pages in a browser. Commit.
