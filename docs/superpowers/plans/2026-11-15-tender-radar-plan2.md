# Tender Radar — Plan 2: Real-shaped data, multi-company, daily pipeline

> **For agentic workers:** execute with superpowers:executing-plans (native). TDD for every task. Ledger: `.superpowers/sdd/2026-11-15-tender-radar-plan2/progress.md`.

**Goal:**
- Make Tender Radar ready for real Etimad data: Etimad-shaped records, a private importer, and region inference.
- Serve several companies.
- Keep a public demo that is fresh every day and runs automatically.
- Send a daily email digest.

**Spec:**
- `docs/superpowers/specs/2026-11-15-tender-radar-design.md`
- The decisions in `CLAUDE.md` (data source section)
- The user's 2026-11-15 instruction: "finish the whole project; design changes come later"

The user opted out of further questions, so all choices below are the implementer's calls. They are recorded in the ledger.

## Global constraints (in addition to Plan 1's)
- **Real Etimad data is private.**
  - Tenders with `source != "seed"` are never written by `export`.
  - Files in `data/imports/` are git-ignored.
  - Test fixtures use fictional values only.
- **No automated access to Etimad.** No scraping, no CAPTCHA handling. The importer reads only files a person saved or copied.
- **Zero running cost.**
  - Daily CI uses the Gemini free tier.
  - If the AI fails, tenders show as "unscored". The pipeline itself never fails because of the AI.
- **No secrets in the repo.**
  - SMTP and Gemini settings come from env/.env or GitHub Actions secrets.

## Review Focus
1. **A mangled or partial Etimad copy:**
   - missing fields
   - title cut off with "..."
   - booklet price "مجانا", a number, or missing
   - deadline with or without a time
   - Arabic-Indic digits

   The importer imports what it can and reports the skipped cards. It never crashes. *(Task 3)*
2. **Real imported tenders leaking into the public export:** this must be impossible. *(Task 3, Task 4)*
3. **Region inference on an agency name that mentions no region, or two regions:** `None` and the first match respectively. A tender with `None` passes the region rule. *(Task 2)*
4. **Running the digest with no new matches, or with SMTP not configured:** a clear message, exit 0, nothing sent. *(Task 6)*
5. **The daily pipeline when Gemini is down:** the export still succeeds and the tenders show "not scored". *(Task 7)*

---

### Task 1: Etimad-shaped tender fields and seed data
- **`Tender` gets new fields:**
  - `inquiry_deadline: date | None`
  - `deadline_time: str | None` ("HH:MM")
  - `booklet_price_sar: float | None` (0 = free)
  - `source_url: str | None`
- **Keep:** `region` and `estimated_value_sar` stay optional (real cards don't have them).
- **DB:** add the matching columns. SQLite dev DBs get recreated: `seed` drops nothing, so document deleting old `.db` files.
- **Reshape `data/seed/tenders.json`:**
  - 12-digit-style references (`2611390XXXXX`)
  - inquiry deadlines and times
  - booklet prices (mostly free, some 500/1000)
  - mostly `region: null` and `estimated_value_sar: null`, as on real cards
  - region kept in the agency name where natural (e.g. "… بمنطقة الرياض")
  - same IT vs non-IT balance
  - `_note` marks the data as synthetic
- **Templates:** show the inquiry deadline, the closing time, booklet price ("مجانا / Free"), and "View on Etimad" only when `source_url` is set.
- **Tests:**
  - the models round-trip the new fields
  - seed loads with ≥30 tenders and unique references
  - the existing rule-split test is updated to the new seed (8–14 pass)

### Task 2: Smarter rules
- **`arabic.normalize`:**
  - starts with NFKC
  - strips the wider diacritic ranges (`ؐ-ًؚ-ٰٟۖ-ۭ`)
  - maps ٱ→ا and Persian digits ۰-۹→0-9
- **`regions.infer_region(agency: str) -> str | None`:**
  - covers the 13 administrative regions plus major cities (جدة/الطائف→مكة المكرمة, الدمام/الخبر/الأحساء→المنطقة الشرقية, أبها→عسير, …)
  - the first match in the text wins
- **`prefilter`:**
  - uses `tender.region or infer_region(tender.agency)`
  - Latin keywords match on word boundaries; Arabic keywords keep substring matching
- **Tests:** ة/ه, ى/ي, decomposed hamza, ٱ, Persian digits, "AI" not matching "maintenance", inferred region filtering, no-region passes.

### Task 3: Private Etimad importer
- **`importer/etimad_text.py`:**
  - `parse_etimad_text(text: str) -> ImportResult(tenders: list[Tender], skipped: list[str])`
  - parses the visitor-list text as it appears when the page is copied (Ctrl+A, Ctrl+C) or saved
  - splits cards on `تاريخ النشر`
  - labels used: الرقم المرجعي, النشاط الأساسي, آخر موعد لإستلام الإستفسارات, آخر موعد لتقديم العروض, قيمة وثائق المنافسة, and the tender type line
  - title = the first long line after the type; agency = the next line
- **`importer/etimad_html.py`:** `html_to_text(html: str) -> str` (stdlib `html.parser`, block tags become newlines), then the same parser.
- **Imported tenders:** `source="etimad-import"`, with `source_url` = the Etimad visitor search URL for the reference.
- **CLI:** `import PATH...` for `.txt` and `.html`; prints imported / updated / skipped.
- **Tests:**
  - a fictional 4-card fixture: free and paid booklets, with and without a time, a truncated title, one broken card
  - the HTML path gives the same result
  - Arabic-Indic digits in dates
  - the export excludes imported tenders (Review Focus 2)

### Task 4: Multiple companies
- **Second seed profile:** `data/seed/profile_contracting.json`, "Al-Bunyan Contracting & Maintenance (synthetic)": construction, maintenance, cleaning, Riyadh plus the Eastern Province.
- **`seed`** loads every `data/seed/profile_*.json`.
- **CLI:**
  - `match` and `export` take `--profile ID` (default: all profiles for match)
  - `brief` takes `--profile` (default: the first)
- **Web:**
  - `/` lists companies when there is more than one; `/c/{profile_id}/` is the dashboard; `/c/{id}/tenders/{ref}` is the detail page
  - the profile editor moves to `/c/{id}/profile`
  - the reader picks a company
- **Export layout:**
  - `index.html` (company chooser)
  - `c/<id>/index.html`, `c/<id>/tenders/<slug>.html`, `briefs/sample.html`, `static/`
- **Implementation calls:**
  - `Links` is split into a `static_files` flag (link style) and a `read_only` flag (forms)
  - the slug gets a short hash suffix to avoid collisions
  - the export clears its output folder first
  - only `source == "seed"` tenders are exported
- **Tests:** two profiles get different matches; the chooser lists both; export paths are relative and contain no forms; imported tenders never appear; slug collision; stale files removed.

### Task 5: Always-fresh demo dates
- **`seed --rolling`:** shifts every seed date by `(today − 2026-11-15)` days, so the demo stays current.
- **`shift_dates(tenders, anchor: date, today: date) -> list[Tender]`.**
- **Tests:** the shift by N days; a None date stays None; the content hash changes, so matches re-run correctly.

### Task 6: Daily email digest
- **`digest.py`:**
  - `build_digest(session, profile, today, top_n=10) -> Digest(subject, text, html, count)`
  - the top scored, still-open tenders, newest first
  - `send_digest(digest, settings, sender=smtp_send)`
- **SMTP settings:** `TR_SMTP_HOST`, `TR_SMTP_PORT` (587), `TR_SMTP_USER`, `TR_SMTP_PASSWORD`, `TR_DIGEST_TO`.
- **CLI:** `digest [--profile ID] [--dry-run]`.
  - Dry-run or missing SMTP → write `digest.html` and print "not sent (SMTP not configured)", exit 0.
  - No matches → "nothing new", exit 0.
- **Tests:** with a fake sender — the content and Arabic subject, the no-SMTP path, the empty path; it never really sends.

### Task 7: Daily pipeline and Pages-ready deploy
- **`scripts/daily.sh`** (also used by CI): `seed --rolling` → `match` → `brief sample` (only if not cached) → `export --out site`.
- **`.github/workflows/daily.yml`:**
  - triggered by `schedule` (daily 03:00 UTC) and `workflow_dispatch`
  - uses the `GEMINI_API_KEY` and `TR_GEMINI_MODEL` secrets/vars; falls back to the fake AI when the key is missing
  - uploads `site/` as an artifact
  - a `deploy` job to GitHub Pages runs only when `github.event.repository.private == false`
  - the digest step runs only when SMTP secrets exist
- **Test:** a local run of the pipeline script with the fake AI produces `site/index.html`.

### Task 8: Remaining review minors
- **Upload route:** plain `def` (runs in a threadpool).
- **Logging:** log a warning with the reason when a tender ends up unscored.
- **Empty-PDF message:** "The PDF has no pages".
- **Missing tests:** a scorer-level out-of-range score; the web 502 branch; a 0-byte upload.

### Task 9: README
Covers:
- what it is and why
- screenshots
- a Mermaid architecture diagram
- how to run (install, seed, match, serve, export, import)
- the AI and cost design
- the honest evaluation numbers and caveat
- the data source and legal note (Etimad policy, private imports, the permission request)
- "what I did / what AI did"
- the roadmap

## Plan 3 (after this): "Ask the booklet" Q&A, the user's design changes, and the demo video.
