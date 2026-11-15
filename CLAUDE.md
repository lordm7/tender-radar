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
- **Load demo data:** `python -m tender_radar seed`
- **Run matching:** `python -m tender_radar match [--today YYYY-MM-DD]`
- **Read a booklet:** `python -m tender_radar brief data/seed/sample_booklet.pdf`
- **Export the static demo:** `python -m tender_radar export --out site`
- **Run the dev server:** `uvicorn tender_radar.web.app:create_app --factory`
- **Test:** `.venv/Scripts/python -m pytest -q` (uses the fake AI only, no keys)
- **CI:** `.github/workflows/ci.yml` (pytest on Python 3.12)

## Key Paths
- Design: `docs/superpowers/specs/2026-11-15-tender-radar-design.md`
- Plans: `docs/superpowers/plans/` (Plan 1 = core, done; Plan 2 = live Etimad data + deploy; Plan 3 = showcase)
- Package: `src/tender_radar/`
  - `models.py`: data shapes
  - `db.py`, `repository.py`: storage
  - `matching/`: `rules.py` (free filter), `scorer.py` (AI scoring + cache)
  - `ai/`: the provider interface, FakeProvider and Gemini
  - `reader/`: PDF → brief
  - `web/`: FastAPI app and templates
  - `export/`: static site
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
- AI results are cached per (tender content hash, profile version). "unscored" results are retried on the next run.

## Gotchas (Windows machine)
- Windows Application Control blocks SQLAlchemy's compiled `.pyd`. Install it pure-Python: `DISABLE_SQLALCHEMY_CEXT=1 pip install --force-reinstall --no-deps --no-binary sqlalchemy sqlalchemy==2.1.8`
- Under Git Bash, `TR_DATABASE_URL` must use a relative or `C:/` path (`sqlite:///.superpowers/dev.db`), not `/c/...`.
- The Windows console isn't UTF-8. The CLI reconfigures stdout; for ad-hoc scripts, set `PYTHONIOENCODING=utf-8`.
- `scripts/make_sample_booklet.py` needs Windows Arial (`C:/Windows/Fonts`) to render Arabic correctly.

## Pending
- [x] Final whole-branch review of Plan 1: 4 fixes made (expired tenders, locked PDFs, AI quota backoff, profile save without AI); 64 tests pass
- [ ] Deferred minors from the review (see `.superpowers/sdd/.../progress.md`): Arabic NFKC/Persian digits, word-boundary Latin keywords, blocking upload route, auth on write routes before public hosting, slug collisions, stale export files
- [ ] The user: get a free Gemini API key, run `scripts/ai_smoke_test.py`, and pick `TR_GEMINI_MODEL`
- [ ] The user: label the 20 tenders in `data/eval/labels.json`, then run `scripts/eval_matching.py` (bar: 80%)
- [ ] Plan 2: Etimad recon (terms, robots.txt, open data), the collector, the daily GitHub Actions job, the Pages deploy and the digest email
- [ ] Plan 3: README with an architecture diagram and "what I did / what AI did", the 2-minute video, "Ask the booklet"
- [ ] Parked: door-pricing BOQ → Quote assistant (waiting on the father's answers; the questions are in the design appendix)
