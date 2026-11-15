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
- **Import real tenders (private):** `python -m tender_radar import FILE.txt|FILE.html`
- **Export the static demo:** `python -m tender_radar export --out site` (seed tenders only)
- **Email digest:** `python -m tender_radar digest [--dry-run]` (previews go to git-ignored `digests/`)
- **Whole daily pipeline:** `python -m tender_radar daily --out site` (what `.github/workflows/daily.yml` runs)
- **Run the dev server:** `uvicorn tender_radar.web.app:create_app --factory`
- **Test:** `.venv/Scripts/python -m pytest -q` (uses the fake AI only, no keys)
- **CI:** `.github/workflows/ci.yml` (pytest on Python 3.12); `daily.yml` (03:00 UTC, deploys Pages only if repo public + Gemini key + scored_total > 0)

## Key Paths
- GitHub: https://github.com/lordm7/tender-radar (PRIVATE for now; make public once the README and real AI results are ready). Commits use the GitHub noreply email.
- Design: `docs/superpowers/specs/2026-11-15-tender-radar-design.md`
- Plans: `docs/superpowers/plans/` (Plan 1 = core, done; Plan 2 = live Etimad data + deploy; Plan 3 = showcase)
- Package: `src/tender_radar/`
  - `models.py`: data shapes
  - `db.py`, `repository.py`: storage
  - `matching/`: `rules.py` (free filter), `scorer.py` (AI scoring + cache)
  - `ai/`: the provider interface, FakeProvider and Gemini
  - `reader/`: PDF → brief
  - `web/`: FastAPI app and templates
  - `export/`: static site (clears only folders holding its `.tender-radar-export` marker)
  - `importer/`: Etimad copied text / saved HTML → tenders (source="etimad-import")
  - `regions.py`: region inferred from the agency name
  - `digest.py`: daily email
  - `prompts/`: versioned prompt templates
- Seed data (synthetic): `data/seed/` — tenders.json, profile_it_services.json, sample_booklet.pdf
- Eval labels (the user fills them in): `data/eval/labels.json`; run with `scripts/eval_matching.py`
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
- AI results are cached per (tender content hash, profile version). "unscored" results are retried on the next run.
- **Privacy rule (Plan 2):** only `source == "seed"` tenders appear in read-only views or the export (`is_public()` in web/app.py). Seed references start `00000000` so they never clash with real Etimad numbers.
- **Routes:** each company lives under `/c/<id>/` (dashboard, `tenders/<ref>`, `profile`); `/` = company chooser (redirects when only one). Static export: `index.html`, `c/<id>/…`, `briefs/sample.html`.
- The daily sample brief is always judged as `najd-digital` (the booklet is an IT tender).

## Gotchas (Windows machine)
- Windows Application Control blocks SQLAlchemy's compiled `.pyd`. Install it pure-Python: `DISABLE_SQLALCHEMY_CEXT=1 pip install --force-reinstall --no-deps --no-binary sqlalchemy sqlalchemy==2.1.8`
- Under Git Bash, `TR_DATABASE_URL` must use a relative or `C:/` path (`sqlite:///.superpowers/dev.db`), not `/c/...`.
- The Windows console isn't UTF-8. The CLI reconfigures stdout; for ad-hoc scripts, set `PYTHONIOENCODING=utf-8`.
- After schema changes, delete old `*.db` files and re-seed (no migrations). A pre-Plan-2 `site/` folder has no export marker, so delete it before `export --out site`.
- `scripts/make_sample_booklet.py` needs Windows Arial (`C:/Windows/Fonts`) to render Arabic correctly.

## Pending
- [x] Final whole-branch review of Plan 1: 4 fixes made (expired tenders, locked PDFs, AI quota backoff, profile save without AI); 64 tests pass
- [ ] Deferred minors from the review (see `.superpowers/sdd/.../progress.md`): Arabic NFKC/Persian digits, word-boundary Latin keywords, blocking upload route, auth on write routes before public hosting, slug collisions, stale export files
- [x] Plan 1 merged to main (PR #1, 2026-11-15). Gemini key set (`gemini-3.5-flash-lite`).
- [x] Eval: 19/20 = 95% agreement with the user's labels. CAVEAT: the fake AI (always 70) also scores 95%, so the set mostly tests the rule filter. CV wording: "pipeline matched human bid decisions on 19/20", NOT "AI is 95% accurate".
- [ ] Add ~6 tricky eval tenders that pass the rules but shouldn't be bid on (hardware-only supply, missing certification, out-of-scope consulting) so the eval really tests the AI
- [x] Plan 2 built on branch feat/plan2 (2026-11-15): Etimad-shaped data, smarter rules, private importer, two companies, rolling demo, digest, daily workflow, README. 134 tests. Final review fixes done; deferred minors are in the Plan 2 ledger.
- [ ] User decisions: make repo public (for Pages), Gmail app password for the digest, OK to store GEMINI_API_KEY as a GitHub secret, send the Etimad letter
- [ ] Gemini flash-lite scores almost every plausible tender 85–90; calibrate with tricky eval cases
- [ ] Plan 3: README with an architecture diagram and "what I did / what AI did", the 2-minute video, "Ask the booklet"
- [ ] Parked: door-pricing BOQ → Quote assistant (waiting on the father's answers; the questions are in the design appendix)
