# Tender Radar · رادار المنافسات

**Finds Saudi government tenders that fit a company, explains the fit with AI (Arabic + English), turns a tender booklet PDF into a one-page bid brief with a go/no-go checklist, and answers questions about the booklet with page citations.**

Built for Saudi B2B companies: thousands of tenders appear on [Etimad](https://tenders.etimad.sa/Tender/AllTendersForVisitor), and a small bid team can't read them all. Tender Radar reads the list, drops what clearly doesn't fit, asks an AI to score what's left, and emails the best matches every morning.

![Matches for an IT services company](docs/screenshots/dashboard.png)

> All data in the public demo is **synthetic**: fictional companies and agencies shaped like real Etimad listings. See [Data source and legal](#data-source-and-legal).

## What it does

| | |
|---|---|
| **Match** | A free rule filter (keywords, deadline, contract value, region, excluded agencies) runs first. An AI model then judges each remaining tender in three parts — **fit**, **ability** and **risk**, each 0–100 with a reason in English and Arabic, plus any hard blocker and what to prepare. Python turns the parts into one score (50% fit + 30% ability + 20% low risk, capped at 40 with a blocker), so the AI measures and the business rules decide. The matches page groups tenders by verdict: worth bidding, worth a closer look, probably skip. |
| **How it works page** | `/en/how` walks through the whole pipeline with live numbers from the data, and traces one tender from the rule checks to the AI parts to the score sum. |
| **Several companies** | The same tenders are matched against each company's profile. The demo has an IT services firm and a contracting & maintenance firm. |
| **Read a booklet** | Upload a tender booklet PDF (كراسة الشروط) and get the scope, deliverables, key dates, eligibility, required documents, evaluation criteria and risks. You also get a go/no-go checklist against the company's certifications. |
| **Ask the booklet** | Ask a question in Arabic or English ("What is the late-delivery penalty?") and get a short answer from the booklet itself, with the page it came from. If the booklet doesn't say, it says so instead of guessing. |
| **English or Arabic** | Every page exists in English (`/en/…`) and in Arabic (`/ar/…`, full right-to-left). The switch keeps you on the same page. Tender titles are translated by the same AI call that scores them, so translation costs nothing extra. |
| **Daily, hands-free** | A GitHub Actions job runs every morning: fresh demo dates → matching → booklet brief → sample booklet questions → static demo → email digest. |
| **Import real tenders (private)** | Copy or save the public Etimad list in your browser; `import` turns it into tenders. Imported tenders are never published: they stay in your local database, go to your AI provider only for scoring, and reach only your own inbox. |

| Arabic matches page | Tender detail | Booklet brief |
|---|---|---|
| ![](docs/screenshots/matches-ar.png) | ![](docs/screenshots/tender.png) | ![](docs/screenshots/brief.png) |

## Architecture

```mermaid
flowchart LR
    subgraph Sources
        S[Synthetic seed<br/>data/seed/*.json]
        I[Etimad list you copied/saved<br/>.txt / .html]
        P[Booklet PDF]
    end
    S -->|seed --rolling| DB[(SQLite<br/>tenders · profiles · matches<br/>briefs · booklet pages · Q&A)]
    I -->|import| DB
    DB --> R[Rule filter<br/>free, instant]
    R -->|passes| AI[AI scoring<br/>Gemini free tier]
    AI -->|score + reasons, cached| DB
    P -->|PyMuPDF text| B[AI booklet brief]
    B --> DB
    Q[Question] --> K[Pick pages<br/>whole booklet, or keyword<br/>ranking if it's long]
    DB -->|booklet pages| K
    K --> A[AI answer<br/>+ page citations, checked]
    A --> DB
    DB --> W[FastAPI app<br/>edit profiles, upload booklets]
    DB --> X[Static export<br/>seed data only]
    DB --> D[Email digest<br/>to the owner only]
    X --> GP[GitHub Pages demo]
```

- **Cheap before smart.** The rules reject roughly 70% of tenders for free. The AI only sees the plausible ones.
- **Never pay twice.** Each AI verdict is cached per (tender content, profile version, prompt version). A tender is re-scored only if it, the profile or the scoring prompt changes.
- **Answers you can check.** "Ask the booklet" is a small retrieval-augmented (RAG) step. A short booklet goes to the AI whole; a long one is ranked page by page with Arabic-aware keyword matching and only the best pages are sent. The AI must cite page numbers. Citations of pages it was never shown are dropped, and an answer with no valid citation is shown as "not stated", never as fact.
- **Fails soft.** If the AI is down (503) or rate-limited (429), the tender is stored as *not scored* and retried on the next run. After repeated rate limits the run stops calling the AI. One-off calls (brief, questions) wait 20s, then 40s, and try again. The demo is always rebuilt.
- **One page function, four outputs.** The live app and the static demo, in English and Arabic, render through the same functions. Every UI string lives in one dictionary (`web/i18n.py`); the export only switches links to relative `.html` files and removes forms. Tests check that every exported link resolves and that English pages contain no Arabic (and the reverse), apart from clearly marked Arabic originals.
- **Swappable AI.** One `LLMProvider` interface. `FakeProvider` is used by tests (no network, no keys); `GeminiProvider` returns schema-validated JSON with a 60-second timeout.

Code map: `src/tender_radar/`
- `models.py`: data shapes (Pydantic)
- `arabic.py`: Arabic spelling normalisation
- `regions.py`: region from an agency name
- `matching/`: rules and AI scoring
- `ai/`: providers
- `reader/`: PDF → brief, and Ask the booklet (`ask.py`)
- `importer/`: Etimad text/HTML
- `web/`: FastAPI app, templates, own stylesheet, and `i18n.py` (every UI string in English and Arabic)
- `export/`: static site
- `digest.py`: email
- `__main__.py`: CLI

## Run it

Needs Python 3.12+.

```bash
python -m venv .venv
.venv/Scripts/pip install -e .[dev]        # Windows; on macOS/Linux use .venv/bin/pip
python -m tender_radar seed                 # synthetic tenders + two demo companies
python -m tender_radar match                # rules + AI (the "fake" AI unless you add a key)
python -m tender_radar brief data/seed/sample_booklet.pdf
python -m tender_radar ask data/seed/sample_booklet.pdf "ما هي غرامة التأخير؟"
uvicorn tender_radar.web.app:create_app --factory   # http://127.0.0.1:8000/en/ (or /ar/)
```

| Command | What it does |
|---|---|
| `seed [--rolling]` | Load demo data. `--rolling` moves every date so the demo is always current. |
| `match [--profile ID]` | Score tenders for every company, or one. |
| `brief PDF [--profile ID]` | Summarise a booklet and check eligibility. |
| `ask PDF "question"... [--lang en\|ar]` | Answer questions from a booklet, citing pages. Saved on that booklet's newest brief and shown on the pages of that language (guessed from the question by default). |
| `import FILE...` | Import Etimad list text (`.txt`, copied with Ctrl+A, Ctrl+C) or a saved page (`.html`). |
| `export --out site` | Write the read-only demo (seed tenders only): `site/en/…` and `site/ar/…`, plus a root page that opens the English home. |
| `digest [--dry-run]` | Email today's best matches to yourself; without SMTP it saves an HTML preview. |
| `daily --out site` | Everything above, in order. This is what GitHub Actions runs. |

**Settings** (environment variables or a git-ignored `.env`, see `.env.example`):
- **AI:** `TR_AI_PROVIDER=gemini`, `GEMINI_API_KEY`, `TR_GEMINI_MODEL`. The free key is at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
- **Email:** `TR_SMTP_*` and `TR_DIGEST_TO`. For Gmail use an app password.
- **Database:** `TR_DATABASE_URL` (SQLite by default).

> Upgrading from an older checkout: an old database gets the new columns automatically. Delete any `site/` folder made by a version before the export marker, and run `seed` again. Old links (`/c/…`, `/reader`, `/briefs/…`) redirect to the English pages.

**Tests:** `pytest -q` (290 tests; they use the fake AI and never touch the network or send email).

## Cost: zero

- **AI:** Gemini free tier. About 15 scoring calls (each also returns the English title), 1 brief and 6 booklet questions (3 per language) per day for the demo, well under the free quota.
- **Hosting:** GitHub Actions and GitHub Pages (free for public repos).
- **Static demo:** precomputed, so visitors never trigger an AI call and the page is never "asleep".

## How good is the matching? (honest numbers)

- **Test set:** 26 synthetic tenders, each labelled "would this company bid?".
  - 20 are the demo tenders, labelled by hand.
  - 6 are **traps** (`data/eval/tricky_tenders.json`): tenders that look like IT work and pass every free rule, but the company shouldn't bid. Examples: hardware-only supply, legal consulting about software contracts, a data-centre building job, medical-device software that needs an SFDA licence.
- **Why the traps matter:** the first version of the set mostly tested the rule filter. A fake AI that always answers 70 scored 19/20 on it. On the full set the fake AI drops to 19/26 and catches 0 of the 6 traps, so the set now measures the AI itself.

| Setup | Agreement | Traps caught | Scores for good fits |
|---|---|---|---|
| Fake AI (always 70) | 19/26 | 0/6 | all 70 |
| Gemini, first prompt | 25/26 | 6/6 | almost all exactly 90 |
| Gemini, calibrated prompt | **26/26** | **6/6** | spread from 62 to 92 |
| Gemini, three-part score | **26/26** | **6/6** | 85–90 for clear fits; two hard cases near the line (57, 63) |

- **What changed in the prompt:** check the main deliverable first, then list every licence or certificate the tender requires and compare it with the profile. A missing one is a hard blocker that caps the score at 40. Use the whole 0–100 scale.
- **Limits:** one run with `gemini-3.5-flash-lite` on a small synthetic set. The trap labels were proposed during development and are waiting for my own review. Free-tier models also vary from run to run.

So the defensible claim is *"on a 26-tender labelled set, including 6 look-alike traps the keyword rules let through, the pipeline matched human bid decisions 26/26"*, not *"the AI is 100% accurate"*. Run it yourself with `python scripts/eval_matching.py`.

## Data source and legal

- **Recon (2026-11-15):**
  - Etimad's public tender pages show a CAPTCHA to automated clients, and this project never tries to bypass it.
  - Etimad's usage policy (clauses 3 and 10) forbids copying or republishing its content without written permission.
  - The developer API offers no tender list.
- **What this project does instead:**
  - **The public demo is synthetic.** The export refuses to include anything but seed data, and tests enforce that.
  - **Real tenders come only from a person.** They copy or save the public list in a normal browser, then run `import`. They are never published: they stay in the local database, their title, agency and activity are sent to the AI provider for scoring, and they appear only in the owner's own email digest. Imported files live in the git-ignored `data/imports/`.
  - **A written permission request** to NCGR, the operator of Etimad, has been drafted. Automatic collection or public use of real data waits for that answer, or for an official open-data source.
- **Booklets:** the sample booklet is synthetic. Don't upload confidential company documents while using the free AI tier: Google may use free-tier inputs to improve its models.

## What I did / what AI did

**Me:**
- chose the problem and the users (Saudi B2B bid teams)
- set the constraints: Python, free-only, no scraping, real data kept private
- approved the design and each plan
- checked Etimad's terms myself
- labelled the evaluation set (the 6 trap tenders were proposed by the AI agent; I review their labels)
- decided how to handle the data source

**AI coding agents (Claude Code):** wrote the code test-first from written specs and plans, under my direction. I can walk through every module and explain how and why it works.

## Roadmap

- [x] "Ask the booklet": questions answered from the booklet, with page citations
- [x] Calibrate scoring with harder evaluation cases
- [ ] Official data source once permission or open data is available
- [x] Visual design refresh: dark, calm style, a fit radar, separate English and Arabic pages
- [ ] A 2-minute demo video
