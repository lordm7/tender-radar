# Tender Radar

## Approach
A portfolio project to win interviews for AI & Automation Engineer roles in Riyadh. It's a web app for a Riyadh IT-services company that does three things:
- finds Saudi government tenders (Etimad) that fit the company
- scores each one with AI and gives reasons in Arabic and English
- turns tender booklet PDFs into a bid brief with a go/no-go checklist

The owner designs the system and directs AI coding agents, and must be able to explain every part. Keep the code readable for a Python learner who knows Java. Zero running cost: no paid hosting and no paid AI.

## Stack & Key Commands
- **Language / framework:** Python ≥3.12 (the machine has 3.14), FastAPI, Jinja2 + Tailwind CDN + vanilla JS, SQLAlchemy 2 + SQLite, Pydantic 2, PyMuPDF, google-genai (Gemini free tier)
- **Install:** `python -m venv .venv && .venv/Scripts/pip install -e .[dev]`
- **Load demo data:** `python -m tender_radar seed [--rolling]` (loads every `data/seed/profile_*.json`)
- **Run matching:** `python -m tender_radar match [--profile ID] [--today YYYY-MM-DD]`
- **Read a booklet:** `python -m tender_radar brief data/seed/sample_booklet.pdf [--profile ID]`
- **Ask the booklet:** `python -m tender_radar ask BOOKLET.pdf "question" ["question" ...] [--lang en|ar]` (stored on that file's newest brief; language guessed from the question)
- **Import real tenders (private):** `python -m tender_radar import FILE.txt|FILE.html`
- **Export the static demo:** `python -m tender_radar export --out site` (seed tenders only)
- **Email digest:** `python -m tender_radar digest [--dry-run]` (previews go to git-ignored `digests/`)
- **Whole daily pipeline:** `python -m tender_radar daily --out site` (what `.github/workflows/daily.yml` runs)
- **Run the dev server:** `python -m uvicorn tender_radar.web.app:create_app --factory` → http://127.0.0.1:8000/en/ (the `.venv/Scripts/uvicorn` exe is blocked under Git Bash; use `python -m`)
- **Test:** `.venv/Scripts/python -m pytest -q` (uses the fake AI only, no keys)
- **CI:** `.github/workflows/ci.yml` (pytest on Python 3.12); `daily.yml` (03:00 UTC, deploys Pages only if repo public + Gemini key + scored_total > 0)

## Key Paths
- GitHub: https://github.com/lordm7/tender-radar (PRIVATE for now; make public once the README and real AI results are ready). Commits use the GitHub noreply email.
- Design: `docs/superpowers/specs/2026-11-15-tender-radar-design.md`
- Redesign spec (parked): `docs/superpowers/specs/2026-11-15-tender-radar-redesign-design.md`; approved mockups in `docs/superpowers/specs/mockups/` (home, matches, language-modes); all-pages draft in `.superpowers/brainstorm/1586-1794759980/content/all-pages.html` (git-ignored)
- Plans: `docs/superpowers/plans/` (Plan 1 = core, done; Plan 2 = live Etimad data + deploy; Plan 3 = showcase)
- Package: `src/tender_radar/`
  - `models.py`: data shapes
  - `db.py`, `repository.py`: storage
  - `matching/`: `rules.py` (free filter), `scorer.py` (AI scoring + cache)
  - `ai/`: the provider interface, FakeProvider and Gemini
  - `reader/`: PDF → brief; `reader/ask.py` = Ask the booklet (keyword page retrieval + cited answer)
  - `web/`: FastAPI app (`app.py`: routes, `Links`, render_* functions), templates, `static/app.css` + `app.js`, `i18n.py` (every UI string en/ar, VOCAB, dates, money, rule reasons)
  - `export/`: static site (clears only folders holding its `.tender-radar-export` marker)
  - `importer/`: Etimad copied text / saved HTML → tenders (source="etimad-import")
  - `regions.py`: region inferred from the agency name
  - `digest.py`: daily email
  - `prompts/`: versioned prompt templates
- Seed data (synthetic): `data/seed/` — tenders.json, profile_it_services.json, sample_booklet.pdf
- Interview study guide (personal, git-ignored): `notes/study-guide.html`; online copy https://claude.ai/artifact/CCRbWiLMsFRJmoe93uRsyf (republish from that file if the stack changes)
- Eval labels (the user fills them in): `data/eval/labels.json`; run with `scripts/eval_matching.py`. Eval-only tricky tenders (pass the rules, still no-bid): `data/eval/tricky_tenders.json` (refs `00000000900x`, never in the demo)
- Settings come from environment variables: `TR_DATABASE_URL`, `TR_AI_PROVIDER` (fake|gemini), `GEMINI_API_KEY`, `TR_GEMINI_MODEL` (see `.env.example`)

## Conventions
- TDD: write the failing test first. Tests never call a real AI; they use `FakeProvider`.
- Every module starts with a 2–4 line docstring explaining what it does and why, in plain words.
- Arabic text gets `dir="auto"`. Match text through `arabic.normalize()`. PDF text goes through NFKC (`clean_text`).
- All seed data is synthetic, uses fictional agencies and is labelled synthetic. No employer (AMMN) data and no personal data.
- Git identity for this repo (local config): Mohammed Alzalam with the personal Gmail address, never the work address. Local commits are OK; push only when the user asks.

## Decisions
- SQLite instead of PostgreSQL (swappable via `TR_DATABASE_URL`). Vanilla JS filters instead of HTMX, so the static demo behaves like the live app.
- Free deployment: a GitHub Actions daily job plus a static demo on GitHub Pages. The full app (uploads, profile editing) runs locally.
- **Data source (2026-11-15 recon):**
  - Etimad's public tender pages show a CAPTCHA to automated clients. NEVER bypass or solve it.
  - The Etimad developer API has no tender list, and its terms forbid storing the data.
  - **Decision: human import + automation.** The user exports or saves the public list in a normal browser; everything after that (parse, dedupe, AI score, email, demo) is automatic.
  - open.data.gov.sa and LCGPA are still unchecked (they need a browser).
- AI model: `gemini-3.5-flash-lite` (free tier, ~5s per call). gemini-2.5-* is closed to new users, and gemini-3.8-flash is often overloaded (503). Every call has a 60s timeout. The key lives in the git-ignored `.env`. Never send real company documents through the free tier (Google may use free-tier data).
- AI results are cached per (tender content hash, profile version + prompt fingerprint) — editing `score_tender.md` re-scores everything. "unscored" results are retried on the next run.
- **Ask the booklet:** booklet pages are stored with the brief (`booklet_pages` table); a short booklet (≤20k chars) goes to the AI whole, a long one is ranked by Arabic-aware keyword IDF. Citations of pages the AI wasn't shown are dropped; a "found" answer with no valid citation is downgraded to not-found. The daily job asks 3 fixed sample questions (`SAMPLE_QUESTIONS` in `__main__.py`) so the static demo shows answers.
- **Privacy rule (Plan 2):** only `source == "seed"` tenders appear in read-only views or the export (`is_public()` in web/app.py). Seed references start `00000000` so they never clash with real Etimad numbers.
- **Routes (redesign, 2026-11-16):** every page is `/{lang}/…` with lang en|ar: `/{lang}/` home, `/{lang}/companies` (307 to the dashboard when only one company), `/{lang}/companies/new` (add a company; POST saves, POST `…/new/extract` = AI pre-fill from a PDF, never saves), `/{lang}/how` (How it works), `/{lang}/c/<id>/` matches, `…/tenders/<ref>`, `…/profile`, `/{lang}/reader`, `/{lang}/briefs/<id>|sample`. `/` redirects to the `tr_lang` cookie language (else en). Old `/c/…`, `/reader`, `/briefs/…` 307 to `/en/…`. Static export: `index.html` (meta refresh to en/), `{lang}/index.html`, `{lang}/companies.html`, `{lang}/companies/new.html` (disabled preview, no `<form>`), `{lang}/how.html`, `{lang}/c/<id>/…`, `{lang}/briefs/sample.html`, shared `static/`.
- The daily sample brief is always judged as `najd-digital` (the booklet is an IT tender).
- **Redesign (built 2026-11-16 on `feat/redesign`, not merged):** dark, calm style with a radar brand mark; FastAPI + Jinja + vanilla JS; one language per page (Arabic = full RTL); "Bidding profile" (ملف المنافسة); home/about page (always public-only; its preview shows the first company by id); own `app.css` replaces Tailwind.
  - **Bilingual data:** tenders carry `title_en/agency_en/description_en` (`ENGLISH_FIELDS`), excluded from the content hash so translating never re-scores. The scoring call also returns the English title/agency (`set_tender_english`). Briefs carry an `en` copy (`BookletBrief.in_lang`); old Arabic-only briefs show the Arabic original marked `lang="ar"` with an "Arabic original" tag. Profiles have `name_ar` (not part of the version).
  - **One-language rule:** English pages show no Arabic and Arabic pages no Latin, except elements marked with the other `lang` (originals, the author name, GitHub/LinkedIn, EN switch) and ISO/PDF/iOS/Android/ERP. `tests/test_export.py` enforces it on every exported page.
  - **Q&A per language:** answers are stored with `lang`; the daily job asks 3 English + 3 Arabic `SAMPLE_QUESTIONS` (a dict per language).
  - **Old databases:** `init_db` adds missing nullable columns (ALTER TABLE), so no re-seed is needed after this schema change.
  - **Constants to keep current:** `LINKEDIN_URL` (placeholder) and `EVAL_AGREEMENT = "26 / 26"` in `web/app.py`.
- **Add your company (2026-11-17):** upload a company-profile PDF → `reader/profile_extract.py` (`extract_profile` → `ProfileDraft`, prompt `extract_profile.md`) pre-fills the form, or type it by hand; the person always reviews before saving. New ids come from `new_profile_id` (slug, `-2` on clash, `company-N` for Arabic-only names). Form parsing is shared: `profile_from_form` in web/app.py; fields are the `profile_fields` macro in `_macros.html`. The upload page warns not to send confidential docs (free Gemini tier).
- **No "open source" claim (2026-11-17):** the hero's second button is "Add your company", not "View source"; hero tags say "Made for Etimad tenders". The footer GitHub link stays. Revisit if the repo goes public with a LICENSE.
- **Tender page (2026-11-17):** decision strip (verdict from the score bands 80+/50+ = "Worth bidding / Worth a closer look / Probably skip", value, deadline), actions (Brief the booklet, Add to calendar, View on Etimad), timeline bar, AI reasons + "Profile check". The profile check comes from `check_rules()` in `matching/rules.py`, which `prefilter()` now uses too (one source of truth; prefilter = first failed check). Calendar files: `calendar_ics.py` (`tender_ics`, Riyadh time → UTC, CRLF, folded lines); live route `/{lang}/calendar/<ref>.ics`, export writes `{lang}/calendar/<slug>.ics` (the exporter writes files with `newline=""` so CRLF survives on Windows).
- **AI score in three parts (2026-11-17, spec `docs/superpowers/specs/2026-11-17-ai-score-parts-design.md`):** Gemini returns fit, ability, risk (0-100, higher risk = worse) with one en/ar reason each, plus `blocker_en/ar` and `prepare_en/ar`. Python computes the score: `0.5·fit + 0.3·ability + 0.2·(100 − risk)`, rounded half up, capped at 40 with a blocker (`WEIGHTS`, `BLOCKER_CAP`, `total_score` in `matching/scorer.py`). Stored in `MatchResult.parts` / `matches.parts` (JSON); `reasons_en/ar` keep the readable list (blocker first). The prompt tells the AI not to repeat rule checks and not to claim unstated certificates. Tender page panel "How the AI scored it". Eval with Gemini after the change: 26/26, traps 6/6 (narrow: 1005 = 57, 1007 = 63 near the 60 line). Lesson: a broad "work inside listed activities is related" line in the prompt let resident-support staffing (1005) through; keep the weak-fit list concrete.
- **How it works page (2026-11-17, spec `docs/superpowers/specs/2026-11-17-how-it-works-page-design.md`):** the interview page. `pipeline_story()` in web/app.py builds live numbers (public seed tenders only) for the company of the traced tender: the best public scored tender with parts, ties → lowest reference. `score_formula()` writes the sum from `WEIGHTS`. Linked from every nav and the home "How it works" section. Tool names/paths are `<span class="code" lang="en" dir="ltr">` so Arabic pages pass the one-language test.
- **AI retries:** one-off calls (brief, ask) go through `call_with_retry` (waits 20s, 40s on 429/503). Tests patch `tender_radar.ai.provider._sleep` in conftest so they never wait.

## Gotchas (Windows machine)
- Windows Application Control blocks SQLAlchemy's compiled `.pyd`. Install it pure-Python: `DISABLE_SQLALCHEMY_CEXT=1 pip install --force-reinstall --no-deps --no-binary sqlalchemy sqlalchemy==2.1.8`
- Under Git Bash, `TR_DATABASE_URL` must use a relative or `C:/` path (`sqlite:///.superpowers/dev.db`), not `/c/...`.
- The Windows console isn't UTF-8. The CLI reconfigures stdout; for ad-hoc scripts, set `PYTHONIOENCODING=utf-8`.
- After schema changes, delete old `*.db` files and re-seed (no migrations). A pre-Plan-2 `site/` folder has no export marker, so delete it before `export --out site`.
- Bash heredocs mangle backslashes in Python code (`\b`, `\n`, Unicode escapes). Write code that contains backslashes with the Write/Edit tools only. Even the Edit tool turns `\u0600`-style escapes into the literal characters: compare code points (`0x0600 <= ord(ch)`) instead.
- Headless screenshots: `"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new --window-size=1280,900 --screenshot=OUT.png URL` (the Chrome extension window can't be widened).
- Headless Edge has a minimum window width (~500px): a `--window-size=400,…` screenshot looks cut off on the right even for correct pages. Don't treat that as a layout bug.
- Checking JS changes in Chrome: the browser keeps a cached `app.js` even with a new page URL. Run `await fetch('<path>/static/app.js', {cache: 'reload'})` in the page, then reload, before testing.
- `scripts/make_sample_booklet.py` needs Windows Arial (`C:/Windows/Fonts`) to render Arabic correctly.

## Pending
- [x] Final whole-branch review of Plan 1: 4 fixes made (expired tenders, locked PDFs, AI quota backoff, profile save without AI); 64 tests pass
- [ ] Deferred minors from the review (see `.superpowers/sdd/.../progress.md`): Arabic NFKC/Persian digits, word-boundary Latin keywords, blocking upload route, auth on write routes before public hosting, slug collisions, stale export files
- [x] Plan 1 merged to main (PR #1, 2026-11-15). Gemini key set (`gemini-3.5-flash-lite`).
- [x] Eval: 19/20 = 95% agreement with the user's labels. CAVEAT: the fake AI (always 70) also scores 95%, so the set mostly tests the rule filter. CV wording: "pipeline matched human bid decisions on 19/20", NOT "AI is 95% accurate".
- [x] 6 tricky eval tenders added (2026-11-16). Labels marked `"proposed": true` — the user must confirm them.
- [x] Calibrated scoring prompt (2026-11-16, one Gemini run): 26/26, tricky 6/6, fit scores spread 62–92. Old prompt: 25/26, tricky 6/6, every fit = 90. Fake AI: 19/26 (tricky 0/6). CV wording: "on a 26-tender labelled set the pipeline matched human bid decisions 26/26, including 6 look-alike no-bid traps the keyword rules let through".
- [x] Plan 2 built on branch feat/plan2 (2026-11-15): Etimad-shaped data, smarter rules, private importer, two companies, rolling demo, digest, daily workflow, README. 134 tests. Final review fixes done; deferred minors are in the Plan 2 ledger.
- [x] Redesign built on `feat/redesign` (2026-11-16, plan `docs/superpowers/plans/2026-11-16-tender-radar-redesign.md`), final review fixes done, 200 tests. NOT merged/pushed: the user reviews it, gives the LinkedIn URL, then merges.
- [ ] NEXT (user, 2026-11-17): more redesign changes are coming first; the LinkedIn URL arrives once the project is finished. Don't merge `feat/redesign` until the user says so.
- [ ] Redesign deferred minors (ledger `.superpowers/sdd/2026-11-16-tender-radar-redesign/progress.md`): orig tag lost in JS select, filter hides selected tender, brief lang switch on old sample briefs, `_orig` isascii guess, profile form `date.today()`, Arabic words in English AI reasons
- [ ] User decisions: make repo public (for Pages), Gmail app password for the digest, OK to store GEMINI_API_KEY as a GitHub secret, send the Etimad letter
- [x] Plan 3 built on branch `feat/plan3` (2026-11-16): Ask the booklet, calibrated eval, README update, video script (`docs/demo-video-script.md`). 154 tests. Merged into main and pushed 2026-11-16 (3aa51df), CI green.
- [ ] Record the 2-minute video (the user does it, following the script)
- [ ] Parked: door-pricing BOQ → Quote assistant (waiting on the father's answers; the questions are in the design appendix)
