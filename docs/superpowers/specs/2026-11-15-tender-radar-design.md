---
type: decision
date: 2026-11-15
project: tender-radar
status: active
tags: [design, ai-automation, portfolio, etimad, python]
---

# Tender Radar — Design

## Context / why
- The user is a 2026 CS graduate in Riyadh (Syrian, so a non-Saudi candidate). They are moving from systems/network administration to **AI & Automation Engineer** roles.
- **The goal of this project is interviews.** A Riyadh HR screener should look at the CV line and demo link and want to call them. A technical interviewer should then find every part defensible.
- Honest framing (standing rule): the user designs the system and directs AI coding agents. They must be able to **explain every component** in plain words. They know Java and are **learning Python through this project**, so code stays readable and every module gets a short plain explanation.
- Saudi relevance is deliberate: government procurement (the Etimad portal) is a big, real pain point for Saudi B2B companies.
- Parked idea (comes back later): a door-pricing "BOQ → Quote" assistant for the user's father's company, a door manufacturer selling to real-estate developers. The questions for the father are in the appendix. The document-reading core built here should be reusable for it.

## What it is
A web app for a **Riyadh IT / tech-services company**. Every day it finds new government tenders that fit the company, explains why each one fits, and turns a tender booklet into a one-page bid brief and a go/no-go checklist.

Demo persona: the bid/business-development manager at a mid-size Riyadh IT services firm.

## Goals (MVP)
1. **Collector.** A daily scheduled job pulls new public tender listings from Etimad: reference number, title, agency, type, activity, status, dates and deadlines. It removes duplicates by reference number, stores the raw data and a cleaned version, and makes polite, rate-limited requests.
   - **Fallback (required).** If live collection is blocked or breaks, the app runs on a stored snapshot and seeded data, so the demo never breaks.
2. **Company profile.** Activities, Arabic and English keywords, certifications and classification, contract-value range, regions and excluded agencies. One demo profile ("IT services firm") is preloaded and editable.
3. **AI matching.** First a cheap rule filter (keywords, activity, deadline still open). Then an AI model scores each remaining tender from 0 to 100 and gives short reasons in Arabic and English. Scores and reasons are stored and never recomputed for the same tender and profile.
4. **Dashboard.** Matched tenders sorted by score, with a deadline countdown, filters (score, agency, deadline) and a tender detail page. Arabic text displays right-to-left correctly.
5. **Daily digest email.** The top matches for that day.
6. **Tender reader.** The user uploads a tender booklet PDF (usually Arabic) → the app extracts the text → AI produces a structured brief: scope, deliverables, key dates, eligibility, required documents, evaluation criteria and risks → plus a go/no-go checklist scored against the company profile. A sample booklet is preloaded for the demo.
7. **Showcase.** A public live demo URL, a README with an architecture diagram and a "what I did / what AI did" note, and a 2-minute demo video.

## Stretch (after MVP)
- "Ask the booklet": question-and-answer over an uploaded booklet, with answers that cite the booklet page. This is the agent/RAG keyword feature.
- A WhatsApp digest.
- An n8n workflow wrapping the API, for the n8n keyword in job ads.
- Reusing the reader core for the father's door BOQ project.

## Non-goals
- Logging into Etimad, buying booklets or submitting bids.
- Multi-company SaaS, user accounts or payments. There is a single demo profile, and the public demo is read-only.
- Mobile app.

## Anti-goals (it fails if…)
- The live demo breaks or is empty when HR or an interviewer clicks it.
- The README or CV claims something the user can't explain.
- Collection breaks Etimad's terms or hammers the site.
- Any employer (AMMN) data or personal data gets used.

## Constraints
- **Python** (user's choice). Windows development machine.
- **Zero running cost (the user's decision: free only).**
  - Visitors never trigger paid AI calls; all AI results are computed in advance.
  - The AI provider must have a free tier.
  - Hosting must be free and still load instantly for HR (no "sleeping" first page).
- No deadline (the user's decision). Work at an easy pace and aim for a "wow" result rather than speed. The build order is still demo-first, so something impressive exists early.
- Arabic-first content (right-to-left), with the interface in English and Arabic.
- Before building the collector, recon is required: check Etimad's terms and robots.txt, and check whether the developer portal or open-data portal can serve as an official source.

## Approaches considered
- **A. One Python app (chosen by the user).** FastAPI back-end, PostgreSQL, scheduled collector, AI scoring and booklet reading, dashboard, live deploy. Most to learn, strongest interview story.
- B. n8n workflows plus a small Python AI service. Faster and hits the n8n keyword, but less code to show. It stays possible later as a wrapper.
- C. A full AI agent with tools. Buzzword-friendly but unpredictable in a live demo. Its useful part comes back as the "Ask the booklet" stretch.

## Decided by the user
- Tender Radar first; the door project is parked until the father answers.
- Python, Approach A, IT/tech-services demo persona.

## My calls (the user can override)
- Stack: Python 3.12, FastAPI, SQLAlchemy + Alembic, PostgreSQL, scheduled jobs inside the app or via cron, pytest, GitHub Actions CI, Docker.
- UI: server-rendered pages (Jinja2 + HTMX + Tailwind) rather than a separate React front-end. It's simpler, all Python, and fast to build.
- **AI:** one small module that lets the AI provider be swapped.
  - Default: a provider with a free tier that handles Arabic well (e.g., the Google Gemini free tier). The exact provider is the builder's pick after a quick Arabic quality test.
  - It returns structured JSON output for scores and briefs.
  - The prompts live in versioned files.
- **Free, two-part deployment:**
  - **(a) Daily pipeline:** a GitHub Actions job runs once a day. It collects tenders, applies the rule filter and AI scoring, and writes the results.
  - **(b) Public demo:** a static snapshot of the dashboard, the tender pages and the sample booklet brief, rebuilt by that job and hosted on GitHub Pages. It is always fast and costs nothing.
  - **(c) Full FastAPI app:** includes the profile editor and booklet upload. It runs locally, and the 2-minute video shows it in action. A free host such as Render can also run it, labelled "may take ~1 min to wake".
- **Public GitHub repo** (unlike Last Mile, which is private), so recruiters can open it.
- Project folder: `C:\Users\mohap\Desktop\tender-radar`. This design doc gets copied to `docs/superpowers/specs/2026-11-15-tender-radar-design.md` there, then `/obsi-base` sets up project memory.
- Quality bar for matching: on 20 hand-labelled tenders, the AI's fit/no-fit verdict agrees with the user's at least 80% of the time. These labels become a small test set.

## Settled after the builder review (my calls)
- **If Etimad doesn't allow automated collection:** use an official open-data or developer-portal source if one exists. Otherwise run on a public snapshot that is refreshed by hand, keep the collector working against recorded pages, and state the gap plainly in the README. The CV claims only what actually runs.
- **Sample booklet:** prefer a tender or RFP that an agency publishes freely on its own website. Otherwise write a realistic synthetic Arabic booklet and label it synthetic in the app and README.
- **Visitors:** the public demo is read-only, with precomputed matches and the sample booklet brief. Uploads and profile edits exist only in the full app, which is shown in the video and runs locally or on the free host. That replaces the earlier "visitors edit a copy" goal.
- **Daily digest email:** sent only to the user's own address. There's no visitor sign-up, so no personal data is collected.

## Left to the builder
- How to collect the data (plain HTTP vs. headless browser), based on the recon.
- PDF text extraction library and whether OCR is needed for scanned booklets.
- Which free-tier AI provider and model to use (after a quick Arabic quality test), and the free database, if one is needed beyond files or SQLite in the pipeline.
- Exact database tables and page layouts, within the goals above.

## Success
- The live link shows fresh, sensible matches and a working booklet brief within 30 seconds of opening.
- New tenders arrive daily without anyone touching it, or the fallback kicks in visibly.
- README, video and CV line are done, and the user can walk through the architecture unaided.

---
## Appendix: questions for the father (door BOQ project, parked)
1. لما شركة عقارية تطلب أبواب لمشروع، وش يرسلون لكم بالضبط؟ (إكسل BOQ؟ جدول أبواب PDF؟ مخططات؟ إيميل؟)
2. مين يسعّر الطلب عندكم، وكيف؟ (إكسل؟ أوراكل؟ خبرة الموظف؟)
3. كم ياخذ تسعير مشروع واحد؟ وكم مشروع بالشهر؟
4. وش أكثر شي متعب أو يسبب أخطاء في التسعير؟
5. وش يأثر على سعر الباب؟ (المقاس، الخامة، مقاوم حريق، الإكسسوارات، التشطيب، التركيب…)
6. نموذج BOQ قديم + عرض السعر، بعد حذف البيانات الحساسة وبموافقة الشركة.
