# "How it works" Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/{lang}/how` page that walks through the real pipeline with real numbers and one traced tender.

**Architecture:** A data function `pipeline_story()` in `web/app.py` builds everything from the database with the existing helpers; `render_how()` renders `templates/how.html`; a route, a `Links.how()` entry, a nav link and the static export expose it.

**Tech Stack:** FastAPI, Jinja2, pytest (FakeProvider data from conftest).

**Spec:** `docs/superpowers/specs/2026-11-17-how-it-works-page-design.md`

## Global Constraints
- One language per page; Latin tool names and file paths on Arabic pages carry `lang="en" dir="ltr"` (enforced by `tests/test_export.py::test_one_language_per_exported_page`).
- Only public (seed) tenders, like every read-only view.
- Numbers come from the same helpers as the matches page (`_rows`, `profile_check`, `score_parts`, `total_score`, `verdict_key`).
- No new AI calls.

## Review Focus
- No scored tender with parts (fresh database, or only old scores) → page renders, section 2 hidden. Test in Task 1.
- Imported (private) tenders in the database → never counted or traced. Test in Task 1.
- Two tenders tie on the top score → the trace picks the lowest reference, stable across runs. Test in Task 1.
- Weights changed → the formula text follows `WEIGHTS`. Covered by building the text from `WEIGHTS` (Task 1 test asserts the formula for conftest data).
- Arabic page → no stray Latin outside `lang="en"` spans. Test in Task 2 (export test).

---

### Task 1: `pipeline_story` data

**Files:** Modify `src/tender_radar/web/app.py`. Test: `tests/test_how_page.py`.

**Interfaces:**
- Produces `pipeline_story(session: Session, today: date, lang: str) -> dict | None` (None when there is no company):
  - `company`: display name (`company_name(profile, lang)[0]`)
  - `counts`: `{"tenders": int, "filtered": int, "scored": int, "unscored": int, "top": list[int]}` for the trace company, public tenders only; `top` = up to 3 best scores, descending.
  - `trace`: `None` or `{"ref", "title", "title_orig", "url_ref", "checks": profile_check(...), "parts": score_parts(...), "formula": str, "score": int, "verdict": str}` where `formula` = e.g. `"0.5 × 95 + 0.3 × 95 + 0.2 × (100 − 5) = 95.0 → 95"` (`exact` with one decimal, built from `WEIGHTS`).
  - Trace company = company of the traced tender; with no trace, the first company by id.

- [ ] **Step 1: Failing tests** in `tests/test_how_page.py` (conftest: Najd scores; 1004 = 95 with fit 95/ability 95/risk 5):
  - `test_story_traces_best_tender`: `story["trace"]["ref"] == "000000001004"`, `story["trace"]["score"] == 95`, `story["trace"]["formula"] == "0.5 × 95 + 0.3 × 95 + 0.2 × (100 − 5) = 95.0 → 95"`, `story["counts"] == {"tenders": 30, "filtered": 21, "scored": 9, "unscored": 0, "top": [95, 82, 75]}`.
  - `test_story_ignores_private_tenders`: add an `etimad-import` copy of 1004 with a 99-score match → trace still 1004, tenders still 30.
  - `test_story_tie_picks_lowest_reference`: give 1002 the same 95 match with parts → trace ref `000000001002`.
  - `test_story_without_parts_has_no_trace`: rewrite every match with `parts=None` → `trace is None`, counts still filled.
- [ ] **Step 2:** Run `.venv/Scripts/python -m pytest -q tests/test_how_page.py` — Expected: FAIL (ImportError).
- [ ] **Step 3:** Implement `pipeline_story` with the existing helpers.
- [ ] **Step 4:** Run the full suite — Expected: all pass.

### Task 2: Page, route, links, export

**Files:** Create `src/tender_radar/web/templates/how.html`. Modify `web/app.py` (`_page_path` "how": `how` / `how.html`; `Links.how()`; `render_how(session, today, read_only, static_files=False, lang="en") -> str`; GET `/{lang}/how` available in read-only too), `templates/base.html` (nav link on every page; on home it replaces the `#how` anchor), `templates/home.html` (a "See the full pipeline" link under the steps), `web/i18n.py`, `static/app.css`, `export/static_site.py` (`{lang}/how.html`). Tests: `tests/test_how_page.py`, `tests/test_export.py`.

New i18n keys (en / ar): `how_page_title` "How Tender Radar works" / "كيف يعمل رادار المنافسات"; `how_intro`; `pipeline`; five step titles + one-sentence texts (`hw_import`, `hw_rules`, `hw_ai`, `hw_rank`, `hw_brief` and `_text`); `count_tenders` "{n} tenders", `count_filtered` "{n} removed by rules", `count_scored` "{n} scored by AI", `count_top` "best: {scores}", `count_brief` "PDF → one-page brief"; `trace_title` "One tender, step by step"; `trace_rules`, `trace_ai`, `trace_formula`; `built_with`; `how_good`; `how_good_text` "{agreement} agreement with human bid decisions on a labelled test set, including 6 look-alike traps the keyword rules let through."; `full_pipeline` "See the full pipeline"; `numbers_for` "Numbers for {company}".

- [ ] **Step 1: Failing tests:** `test_how_page_in_both_languages` (200; en contains "How Tender Radar works", "One tender, step by step", the formula, `src/tender_radar/matching/rules.py`; ar contains "كيف يعمل رادار المنافسات" and `lang="en"` around "Gemini"), `test_how_page_read_only` (200 with `read_only=True`), `test_nav_links_to_how` (dashboard and home contain `href="/en/how"`), export test `test_export_has_how_page` (`{lang}/how.html` exists; home links `../{lang}/how.html`). The existing one-language and link-resolution export tests must stay green.
- [ ] **Step 2:** Run them — Expected: FAIL.
- [ ] **Step 3:** Implement. Layout: pipeline as 5 connected cards in a row (stacked on phones, arrows flip in RTL via logical properties); trace as two columns (rule checks | AI parts) above a formula line; built-with as pill chips; how-good as one stat.
- [ ] **Step 4:** Run the full suite — Expected: all pass.

### Task 3: Check and record
- [ ] Headless Edge screenshots of `/en/how` and `/ar/how` on the real database; fix anything that reads badly.
- [ ] Add the route to CLAUDE.md (Routes + export list).
- [ ] Final review by a fresh reviewer; fix Critical/Important test-first.
