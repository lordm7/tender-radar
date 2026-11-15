# Tender Radar — Core (Plan 1 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working Tender Radar on seeded tender data: a company profile, a rule filter plus AI scoring, a dashboard, a booklet reader, and a static read-only export of the demo.

**Architecture:**
- One Python package, `tender_radar`, with a FastAPI app. It uses server-rendered Jinja2 pages and stores data in SQLite through SQLAlchemy.
- AI calls go through one small provider interface. Tests use `FakeProvider`; real runs use `GeminiProvider` (free tier).
- The same templates are rendered to a static `site/` folder for the free public demo.
- Live Etimad collection, the daily job, hosting and the digest email are Plan 2. The README, video and stretch features are Plan 3.

**Tech Stack:** Python ≥3.12 (the machine has 3.14), FastAPI, Jinja2, SQLAlchemy 2, Pydantic 2, PyMuPDF, google-genai, pytest, httpx (TestClient), Tailwind via CDN, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-11-15-tender-radar-design.md`

## Global Constraints
- Python ≥3.12. Dependencies are declared in `pyproject.toml` (`pip install -e .[dev]`).
- **Zero running cost.** No paid APIs. Tests never call a real AI provider: they use `FakeProvider` only.
- AI results are stored and never recomputed for the same (tender reference, profile version).
- Arabic-first content: every element showing Arabic text gets `dir="auto"`. The interface is labelled in English with Arabic subtitles.
- Readable code for a Python learner. Every module opens with a 2–4 line docstring saying what it does and why. Avoid clever one-liners.
- No employer (AMMN) data and no personal data. All seed data is synthetic and labelled synthetic.
- Deviations from the design's stack calls, decided in planning:
  - SQLite instead of PostgreSQL. The connection is configured by the `TR_DATABASE_URL` setting, so PostgreSQL can be swapped in later.
  - Filters use vanilla JS instead of HTMX, so the static demo and the live app behave the same.
- Git commits happen only after the user agrees to committing during execution (user rule).

## Review Focus
1. **Arabic spelling variants:** أ/إ/آ vs ا, ة vs ه, ى vs ي, diacritics and Arabic-Indic digits (٠-٩) in titles or keywords. Keyword matching must still match. *Test in Task 3.*
2. **Bad AI output:** malformed JSON, a score outside 0–100, or a free-tier rate-limit error (429). The tender is stored as `status="unscored"` and the run continues. *Tests in Task 5.*
3. **Missing or past deadline:** a deadline in the past is filtered out with the reason "deadline passed". A missing deadline passes the filter and is shown as "غير محدد / not stated". It never crashes. *Tests in Tasks 3 and 7.*
4. **Unreadable PDF:** a scanned PDF with no text layer, or an empty or corrupt file, gives a clear message and makes no AI call. A very long booklet is cut to the input budget, and the brief says so. *Tests in Task 9.*
5. **Re-imported reference:** a tender reference number seen again with changed fields updates the existing row rather than creating a duplicate. If the content changed, its old match is invalidated. *Test in Task 2.*

---

## File Structure
```
pyproject.toml
src/tender_radar/
  __init__.py
  __main__.py          # CLI entry (Task 6)
  settings.py          # env-based settings (Task 1)
  models.py            # Pydantic data shapes (Task 1)
  arabic.py            # Arabic text normalisation (Task 3)
  db.py                # SQLAlchemy tables + session (Task 2)
  repository.py        # read/write helpers (Task 2)
  matching/rules.py    # cheap rule filter (Task 3)
  matching/scorer.py   # AI scoring + caching run (Task 5)
  ai/provider.py       # LLMProvider protocol, FakeProvider, get_provider (Task 4)
  ai/gemini.py         # GeminiProvider (Task 4)
  prompts/score_tender.md, prompts/booklet_brief.md
  reader/pdf_text.py   # PDF → page texts (Task 9)
  reader/brief.py      # pages → BookletBrief (Task 9)
  web/app.py           # FastAPI routes (Tasks 7, 8, 10)
  web/templates/*.html, web/static/app.js
  export/static_site.py  # render site/ (Task 11)
data/seed/tenders.json, data/seed/profile_it_services.json, data/seed/sample_booklet.pdf
data/eval/labels.json  # 20 hand labels (Task 5)
scripts/ai_smoke_test.py, scripts/eval_matching.py
tests/...
.github/workflows/ci.yml
```

---

### Task 1: Skeleton, settings, data models, seed data

**Files:**
- Create: `pyproject.toml`, `src/tender_radar/__init__.py`, `settings.py`, `models.py`, `data/seed/tenders.json`, `data/seed/profile_it_services.json`, `.gitignore` (venv, `*.db`, `site/`, `.env`), `tests/test_models.py`
- Run `git init` here.

**Interfaces:**
- Produces:
  - `class Tender(BaseModel)`, with fields:
    - `reference: str`, `title: str`, `agency: str`
    - `tender_type: str`, `activity: str`
    - `region: str | None`
    - `published_on: date | None`, `deadline: date | None`
    - `estimated_value_sar: float | None`
    - `description: str = ""`, `source: str = "seed"`
  - `class CompanyProfile(BaseModel)`, with fields:
    - `id: str`, `name: str`
    - `activities: list[str]`, `keywords: list[str]`
    - `certifications: list[str]`
    - `min_value_sar: float | None`, `max_value_sar: float | None`
    - `regions: list[str]`, `excluded_agencies: list[str]`
    - property `version: str`: the first 12 hex characters of the sha256 of `model_dump_json(exclude={"id","name"})`
  - `class MatchResult(BaseModel)`, with fields:
    - `tender_reference: str`, `profile_id: str`, `profile_version: str`
    - `status: Literal["filtered_out","scored","unscored"]`
    - `score: int | None` (between 0 and 100)
    - `reasons_en: list[str]`, `reasons_ar: list[str]`
  - `class AIScore(BaseModel)`, with fields: `score: int` (`Field(ge=0, le=100)`), `reasons_en: list[str]`, `reasons_ar: list[str]`
  - `class BookletBrief(BaseModel)`, with fields:
    - `scope: str`, `deliverables: list[str]`, `key_dates: list[str]`
    - `eligibility: list[str]`, `required_documents: list[str]`, `evaluation_criteria: list[str]`
    - `risks: list[str]`, `go_no_go: list[ChecklistItem]`
    - `truncated: bool = False`
  - `class ChecklistItem(BaseModel)`, with fields: `item: str`, `status: Literal["meets","gap","check"]`, `note: str`
  - `load_seed_tenders(path: Path) -> list[Tender]` and `load_profile(path: Path) -> CompanyProfile`, both in `models.py`
  - `Settings` in `settings.py`: `database_url` (env `TR_DATABASE_URL`, default `sqlite:///tender_radar.db`), `ai_provider` (env `TR_AI_PROVIDER`, default `"fake"`), `gemini_model` (env `TR_GEMINI_MODEL`), `gemini_api_key` (env `GEMINI_API_KEY`). Read with `os.environ`; no extra dependency.

**Seed data:**
- About 30 synthetic tenders:
  - About 12 IT tenders (software, cloud, cybersecurity, AI, IT support).
  - About 18 others (construction, cleaning, catering, medical supplies).
- Titles and descriptions are in Arabic, with realistic agencies and regions.
- 3 have past deadlines, 2 have no deadline, and 2 use Arabic-Indic digits or spelling variants in the title.
- The profile is "Najd Digital Solutions (synthetic)", a Riyadh IT-services firm. Its keywords are in Arabic and English, for example "برمجيات", "أمن سيبراني", "حوسبة سحابية", "ذكاء اصطناعي", "software", "cloud".
- Each file has a top-level `"_note": "synthetic demo data"`. The loaders ignore this key.

- [ ] **Step 1: Write the failing tests** in `tests/test_models.py`
  - `test_seed_tenders_load`: `len(tenders) >= 30`, and all references are unique.
  - `test_profile_version_changes_when_keywords_change`: after `p2 = p.model_copy(update={"keywords": p.keywords + ["x"]})`, `p2.version != p.version`.
  - `test_profile_version_ignores_name`: changing the name leaves the version the same.
  - `test_ai_score_rejects_out_of_range`: `AIScore(score=101, …)` raises `ValidationError`.
- [ ] **Step 2: Run** `pytest tests/test_models.py -v` → FAIL (import error).
- [ ] **Step 3: Implement.** Write the models, loaders, settings and seed files, plus `pyproject.toml` (src layout, `[project.optional-dependencies] dev = ["pytest","httpx"]`).
- [ ] **Step 4: Run** `python -m venv .venv && .venv/Scripts/pip install -e .[dev] && .venv/Scripts/pytest -v` → PASS.
- [ ] **Step 5: Commit** `feat: project skeleton, data models and synthetic seed data`.

### Task 2: Database and repository

**Files:** Create `src/tender_radar/db.py`, `src/tender_radar/repository.py`, `tests/test_repository.py`

**Interfaces:**
- Consumes: the models from Task 1 and `Settings.database_url`.
- Produces:
  - `make_engine(url: str) -> Engine`, `init_db(engine) -> None`, `session_scope(engine) -> ContextManager[Session]`
  - Tables:
    - `tenders`: primary key `reference`, the Tender fields, `content_hash`, `updated_at`
    - `profiles`: `id`, `json`
    - `matches`: primary key (`tender_reference`, `profile_id`), plus `profile_version`, `content_hash`, `status`, `score`, `reasons_en` (JSON), `reasons_ar` (JSON), `scored_at`
    - `briefs`: `id`, `filename`, `json`, `created_at`
  - `upsert_tenders(session, tenders: list[Tender]) -> UpsertStats`. `UpsertStats` is a dataclass with `inserted`, `updated` and `unchanged`. When `content_hash` changes, delete that tender's `matches` rows.
  - `list_tenders(session) -> list[Tender]`, `get_tender(session, ref) -> Tender | None`
  - `save_profile(session, p)`, `get_profile(session, id) -> CompanyProfile | None`
  - `get_match(session, ref, profile_id) -> MatchResult | None`, `save_match(session, m: MatchResult, content_hash: str)`, `list_matches(session, profile_id) -> list[MatchResult]`
  - `save_brief(session, filename, brief) -> int`, `get_brief(session, id) -> BookletBrief | None`, `latest_brief(session, filename: str | None = None) -> tuple[str, BookletBrief] | None` (newest overall, or newest with that filename)
  - `tender_content_hash(t: Tender) -> str`
- Matches store the content hash so that Task 5 can tell when a cached match is stale.

- [ ] **Step 1: Write the failing tests.** Use an in-memory `sqlite://` engine.
  - `test_upsert_inserts_then_unchanged`: stats are `(30,0,0)`, then `(0,0,30)`.
  - `test_upsert_changed_title_updates_and_drops_match`: save a match, change the title, upsert → `updated == 1`, `get_match(...) is None`, and the tender count is unchanged. *(Review Focus 5)*
  - `test_profile_roundtrip`
  - `test_brief_roundtrip_latest`
- [ ] **Step 2: Run** `pytest tests/test_repository.py -v` → FAIL.
- [ ] **Step 3: Implement** with SQLAlchemy 2 declarative models. JSON columns hold the lists.
- [ ] **Step 4: Run** `pytest -v` → PASS.
- [ ] **Step 5: Commit** `feat: SQLite storage with dedupe-by-reference upsert`.

### Task 3: Arabic normalisation and rule filter

**Files:** Create `src/tender_radar/arabic.py`, `src/tender_radar/matching/__init__.py`, `src/tender_radar/matching/rules.py`, `tests/test_rules.py`

**Interfaces:**
- Produces:
  - `normalize(text: str) -> str`. It lowercases, removes diacritics and tatweel (ـ), maps أإآ→ا, ة→ه and ى→ي, maps Arabic-Indic digits to 0-9, and collapses whitespace.
  - `RuleResult(passed: bool, reasons: list[str])`, a dataclass.
  - `prefilter(tender: Tender, profile: CompanyProfile, today: date) -> RuleResult`

**Rules, in order** (the first failure decides; reasons are English):
1. The agency is in `excluded_agencies` → "excluded agency".
2. The deadline is before `today` → "deadline passed". A missing deadline passes.
3. A known value outside the min/max range → "value outside range".
4. If `regions` is non-empty and the tender has a region, the region must be in the list → "region not covered".
5. At least one normalised keyword or activity appears in the normalised `title + " " + activity + " " + description` → otherwise "no keyword match".
- When a tender passes, the reasons list the keywords that matched.

- [ ] **Step 1: Write the failing tests.**
  - `test_normalize_variants`: `normalize("الأمن السيبرانيّ") == normalize("الامن السيبراني")` and `normalize("مشروع ٢٠٢٦") == "مشروع 2026"`. *(Review Focus 1)*
  - `test_keyword_match_across_hamza_variants`: keyword "أمن سيبراني" matches the title "خدمات امن سيبراني".
  - `test_past_deadline_filtered`: reasons == ["deadline passed"]. *(Review Focus 3)*
  - `test_missing_deadline_passes`
  - `test_excluded_agency`, `test_value_out_of_range`, `test_non_it_tender_filtered`: a cleaning tender fails with "no keyword match".
  - `test_seed_data_split`: with `today=date(2026,11,15)`, between 8 and 14 seed tenders pass. This guards the demo against being empty or full of noise.
- [ ] **Step 2: Run** `pytest tests/test_rules.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest -v` → PASS. Adjust the seed data, not the rules, if the split test fails.
- [ ] **Step 5: Commit** `feat: Arabic-aware rule prefilter`.

### Task 4: AI provider layer

**Files:** Create `src/tender_radar/ai/__init__.py`, `ai/provider.py`, `ai/gemini.py`, `scripts/ai_smoke_test.py`, `tests/test_provider.py`

**Interfaces:**
- Produces:
  - `class LLMProvider(Protocol)`: `def generate_json(self, prompt: str, schema: type[T]) -> T` (T bound to `BaseModel`).
  - `class AIError(Exception)`, and `class RateLimited(AIError)`.
  - `class FakeProvider`:
    - `__init__(self, responses: list[dict | Exception] | None = None)`
    - It returns `schema.model_validate(next response)`. An `Exception` in the list is raised instead.
    - With no responses, it returns a deterministic default per schema: `AIScore(score=70, reasons_en=["fake"], reasons_ar=["تجريبي"])`, or a minimal `BookletBrief`.
    - `calls: list[str]` records the prompts it received.
  - `class GeminiProvider`:
    - `__init__(self, api_key: str, model: str)`
    - Uses `google.genai` with `response_mime_type="application/json"` and `response_schema=schema`.
    - Maps HTTP 429 to `RateLimited` and other SDK or validation errors to `AIError`.
  - `get_provider(settings: Settings) -> LLMProvider`: `"fake"` → `FakeProvider()`, `"gemini"` → `GeminiProvider`. An unknown name raises `ValueError`.
- `scripts/ai_smoke_test.py` is manual and never runs in CI. It scores 3 seed tenders and summarises a short Arabic paragraph with the real provider, then prints the results. The user runs it once to judge the Arabic quality and choose `TR_GEMINI_MODEL`, after checking Google's current free-tier model list.

- [ ] **Step 1: Write the failing tests.**
  - `test_fake_returns_queued_then_default`
  - `test_fake_raises_queued_exception`
  - `test_get_provider_unknown_raises`
  - `test_get_provider_fake_default`
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Add `google-genai` to the dependencies. Gemini is constructed lazily, so importing the module without a key works.
- [ ] **Step 4: Run** `pytest -v` → PASS.
- [ ] **Step 5: Manual** (only with the user's API key): `TR_AI_PROVIDER=gemini python scripts/ai_smoke_test.py` → readable Arabic reasons and valid JSON. Record the chosen model in `.env.example`.
- [ ] **Step 6: Commit** `feat: pluggable AI provider with fake and Gemini`.

### Task 5: AI scoring and matching run with caching

**Files:** Create `src/tender_radar/prompts/score_tender.md`, `src/tender_radar/matching/scorer.py`, `data/eval/labels.json`, `scripts/eval_matching.py`, `tests/test_scorer.py`

**Interfaces:**
- Consumes: `prefilter`, `LLMProvider`, `AIScore`, and the repository functions (`get_match`, `save_match`, `tender_content_hash`).
- Produces:
  - `build_score_prompt(tender: Tender, profile: CompanyProfile) -> str`. It fills `score_tender.md` (placeholders `{profile_json}`, `{tender_json}`).
  - `run_matching(session, profile: CompanyProfile, provider: LLMProvider, today: date, max_retries: int = 2, sleep: Callable[[float], None] = time.sleep) -> RunStats`.
    - `RunStats(filtered_out, scored, unscored, cached)` is a dataclass.

**Behaviour, per tender:**
- If a cached match has the same `profile_version` and `content_hash` → count it as `cached` and skip it.
- If `prefilter` fails → save `filtered_out` with the rule reasons as `reasons_en`.
- Otherwise call the provider.
  - On `RateLimited`, retry up to `max_retries` times with a backoff of `sleep(2**attempt)`.
  - On `AIError`, a `ValidationError`, or retries running out → save `unscored` with reason "AI unavailable – will retry next run" and continue.
- `unscored` matches are not cached; the next run retries them.

**The prompt:** it asks for a fit score for this company and 2–3 short reasons in English and in Saudi-business Arabic. It states the scale: 80+ means a strong fit, 50–79 a partial fit, under 50 a weak fit.

- [ ] **Step 1: Write the failing tests** (FakeProvider, in-memory DB, the seed data, `today=date(2026,11,15)`, `sleep=lambda s: None`).
  - `test_run_scores_only_prefiltered`: `stats.scored == number passing prefilter`, and `len(fake.calls) == stats.scored`.
  - `test_second_run_is_fully_cached`: second-run `len(fake.calls) == 0` and `stats.cached == 30`.
  - `test_profile_change_rescores`
  - `test_malformed_json_marks_unscored_and_continues`: a queued response of `{"score": "high"}` for the first tender → that tender is `unscored`, and the others are `scored`. *(Review Focus 2)*
  - `test_rate_limit_retries_then_succeeds`: queue `[RateLimited(), valid]` → `scored`.
  - `test_rate_limit_exhausted_unscored_and_retried_next_run` *(Review Focus 2)*
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest -v` → PASS.
- [ ] **Step 5: Eval harness** (manual, real provider).
  - `data/eval/labels.json` holds 20 references with `fit: true|false`. **The user labels these by hand**; the agent prepares the list for them to fill in.
  - `scripts/eval_matching.py` runs the matching and treats a score of 60 or more as a fit. It prints the agreement percentage and exits with code 1 below 80%.
- [ ] **Step 6: Commit** `feat: cached AI scoring run with retry and graceful failure`.

### Task 6: CLI

**Files:** Create `src/tender_radar/__main__.py`, `tests/test_cli.py`

**Interfaces:**
- Produces `main(argv: list[str] | None = None) -> int`, built with argparse. Subcommands:
  - `seed`: init the DB, upsert the seed tenders, save the seed profile, print the stats.
  - `match [--today YYYY-MM-DD]`: run matching with `get_provider(Settings())`.
  - `brief PATH`: Task 9.
  - `export [--out site]`: Task 11.
- Subcommands added in later tasks register themselves here.

- [ ] **Step 1: Write the failing test.** `test_seed_then_match_with_fake`: set `TR_DATABASE_URL` to a tmp file and `TR_AI_PROVIDER=fake`; `main(["seed"]) == 0`; `main(["match","--today","2026-11-15"]) == 0`; the DB holds 30 matches.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: command line for seed and match`.

### Task 7: Dashboard and tender detail pages

**Files:** Create `src/tender_radar/web/__init__.py`, `web/app.py`, `web/templates/base.html`, `dashboard.html`, `tender.html`, `web/static/app.js`, `tests/test_web_dashboard.py`

**Interfaces:**
- Consumes: the repository functions and `Settings`.
- Produces:
  - `create_app(settings: Settings | None = None, today: date | None = None, read_only: bool = False) -> FastAPI`
  - `GET /`: the dashboard.
  - `GET /tenders/{reference}`: the detail page (404 if unknown).
  - `render_dashboard(session, profile, today, read_only) -> str` and `render_tender(session, ref, profile, today, read_only) -> str`. These are pure render functions, which Task 11 reuses.
  - Template context helpers: `deadline_label(deadline: date | None, today) -> str` → "12 days left" / "Closes today" / "غير محدد / not stated". (Past deadlines are already filtered out.)

**Dashboard:**
- A header with the profile name and a "Synthetic demo data" badge.
- Score cards: green for 80 and up, amber for 50–79, grey below 50.
- Each card shows the Arabic title (`dir="auto"`), agency, deadline label and reasons (EN plus AR).
- Sorting: `scored` by score descending, then `unscored`. `filtered_out` items go in a collapsed "Filtered out (N)" section with their reasons.
- `app.js` filters client-side on `data-score`, `data-agency` and `data-days-left`. There are no server round-trips, so the static export behaves the same.
- In read-only mode, links to `/profile` and `/reader` upload are hidden. Detail links use relative `.html` paths when `read_only` (for static hosting).

- [ ] **Step 1: Write the failing tests** (TestClient; DB seeded and matched with FakeProvider).
  - `test_dashboard_lists_scored_first`: the first card's reference is the highest-scored one.
  - `test_dashboard_shows_filtered_section_with_reasons`
  - `test_missing_deadline_label` *(Review Focus 3)*
  - `test_arabic_title_has_dir_auto`
  - `test_unknown_tender_404`
  - `test_read_only_hides_profile_link`
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Manual check:** `uvicorn tender_radar.web.app:create_app --factory` → open http://127.0.0.1:8000. Arabic shows right-to-left, and the filters work.
- [ ] **Step 6: Commit** `feat: dashboard and tender detail pages`.

### Task 8: Profile editor

**Files:** Modify `web/app.py`. Create `web/templates/profile.html`, `tests/test_web_profile.py`.

**Interfaces:**
- Produces:
  - `GET /profile`: a form. List fields are textareas with one item per line.
  - `POST /profile`: validate, save, run `run_matching` with the configured provider, then redirect 303 to `/`.
  - The route is absent when `read_only=True`.
- Form parsing uses `python-multipart` (added to the dependencies).

- [ ] **Step 1: Write the failing tests.**
  - `test_profile_edit_saves_and_rescores`: add the keyword "صيانة". The profile version changes, and the FakeProvider gets new calls.
  - `test_profile_rejects_min_greater_than_max`: returns 422 and shows the error message on the form.
  - `test_profile_route_absent_in_read_only`: 404.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** Add a model validator on `CompanyProfile` for min ≤ max. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: editable company profile with rescoring`.

### Task 9: Booklet reader core

**Files:** Create `src/tender_radar/reader/__init__.py`, `reader/pdf_text.py`, `reader/brief.py`, `prompts/booklet_brief.md`, `data/seed/sample_booklet.pdf`, `tests/test_reader.py`, `tests/fixtures/` (a small text PDF, a scanned image-only PDF and a corrupt file, all generated in the test setup with PyMuPDF where possible)

**Interfaces:**
- Produces:
  - `extract_pages(path: Path) -> list[str]`. It raises `UnreadablePDF(message)` when the file can't be opened, or when the total stripped text is under 200 characters ("This PDF looks scanned (no text layer). OCR is not supported yet.").
  - `MAX_INPUT_CHARS = 60_000`
  - `build_brief(pages: list[str], profile: CompanyProfile, provider: LLMProvider) -> BookletBrief`. It joins the pages with `[page N]` markers and cuts the input at `MAX_INPUT_CHARS`, setting `truncated=True` when it does. It then fills `booklet_brief.md` (placeholders `{profile_json}`, `{booklet_text}`) and calls the provider with `BookletBrief`.
  - The CLI subcommand `brief PATH` prints the brief as JSON and saves it with `save_brief`.

**The prompt** asks for the BookletBrief fields in Arabic, and for `go_no_go` items scored against the profile. Each item's status is `meets` (the profile clearly satisfies it), `gap` (clearly doesn't) or `check` (unclear).

**The sample booklet** is a synthetic Arabic RFP of about 4 pages for "منصة رقمية لإدارة المواعيد" from a fictional municipality. It is generated by a script, `scripts/make_sample_booklet.py`, with PyMuPDF and an Arabic-capable font, and the first page carries the label "نموذج تجريبي – Synthetic sample". The executor first spends at most 30 minutes looking for a freely published agency RFP; if one is found and its terms allow sharing, use that instead and record its URL.

- [ ] **Step 1: Write the failing tests.**
  - `test_extract_text_pdf`
  - `test_scanned_pdf_raises_unreadable_and_no_ai_call` *(Review Focus 4)*
  - `test_corrupt_file_raises_unreadable` *(Review Focus 4)*
  - `test_long_booklet_truncated_flag`: pages totalling 100k characters → `brief.truncated is True`, and the prompt is under `MAX_INPUT_CHARS` + 5,000. *(Review Focus 4)*
  - `test_brief_uses_provider_schema`
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** Add `pymupdf` to the dependencies. **Step 4: Run** → PASS.
- [ ] **Step 5: Manual** (real provider): `python -m tender_radar brief data/seed/sample_booklet.pdf` → a sensible Arabic brief.
- [ ] **Step 6: Commit** `feat: tender booklet reader with brief and go/no-go checklist`.

### Task 10: Reader web pages

**Files:** Modify `web/app.py`. Create `web/templates/reader.html`, `brief.html`, `tests/test_web_reader.py`.

**Interfaces:**
- Produces:
  - `GET /reader`: the upload form. It's hidden when `read_only`.
  - `POST /reader`: upload a PDF (maximum 15 MB; anything else gets 413 with a message). It runs `extract_pages` and `build_brief`, saves the brief, then redirects to `/briefs/{id}`.
  - `GET /briefs/{id}`: the brief page. Sections are cards, with go/no-go shown as ✅ meets, ❌ gap, ⚠️ check. When `truncated`, a banner says "Long booklet: only the first part was analysed."
  - `GET /briefs/sample`: shows `latest_brief(session, "sample_booklet.pdf")`. It's linked from the dashboard header as "See a booklet brief".
  - `render_brief(brief, filename, read_only) -> str`, for Task 11.

- [ ] **Step 1: Write the failing tests.**
  - `test_upload_pdf_shows_brief`
  - `test_upload_scanned_pdf_shows_friendly_error`: status 400, the message is shown, and there are 0 provider calls. *(Review Focus 4)*
  - `test_oversize_upload_413`
  - `test_brief_truncated_banner`
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: booklet upload and brief pages`.

### Task 11: Static demo export and CI

**Files:** Create `src/tender_radar/export/__init__.py`, `export/static_site.py`, `.github/workflows/ci.yml`, `tests/test_export.py`

**Interfaces:**
- Consumes: `render_dashboard`, `render_tender` and `render_brief` with `read_only=True`.
- Produces:
  - `export_site(session, profile, today: date, out_dir: Path) -> list[Path]`. It writes:
    - `index.html`
    - `tenders/<slug>.html` for every non-filtered tender (`slug` = reference with any character other than `[A-Za-z0-9-]` replaced by `-`)
    - `briefs/sample.html` if a sample brief exists
    - `static/app.js`
    - a footer: "Synthetic demo data · scores precomputed on <today> · built with Python + AI"
  - The CLI subcommand `export --out site`.
- `ci.yml`: on push and PR, Python 3.12, `pip install -e .[dev]`, `pytest -q`. It never uses AI keys.

- [ ] **Step 1: Write the failing tests.**
  - `test_export_writes_index_and_detail_pages`
  - `test_exported_links_are_relative`: no `href="/` anywhere in the output.
  - `test_export_has_no_upload_or_profile_forms`: no `<form` and no `/profile` in the output.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `pytest -v` → all PASS.
- [ ] **Step 5: Manual end-to-end:**
  1. `python -m tender_radar seed`
  2. `python -m tender_radar match`
  3. `python -m tender_radar brief data/seed/sample_booklet.pdf`
  4. `python -m tender_radar export --out site`
  5. `python -m http.server -d site 8080`
  6. Open http://localhost:8080 and check that the dashboard, a detail page and the sample brief all work offline with no server code.
- [ ] **Step 6: Commit** `feat: static read-only demo export and CI`.

---

## Next plans (not in this plan)
- **Plan 2:**
  - Etimad recon: terms, robots.txt, open data and the developer portal.
  - The collector, with recorded-page tests and the snapshot fallback.
  - The daily GitHub Actions pipeline (collect → match → export).
  - GitHub Pages deploy and the digest email to the user's own address.
- **Plan 3:** README with the architecture diagram and a "what I did / what AI did" note, the 2-minute video, "Ask the booklet" (stretch), and reusing the reader core for the father's door BOQ project.
