---
type: note
date: 2026-11-16
project: tender-radar
status: active
tags: [demo, video, showcase]
---

# 2-minute demo video: script

Goal: a recruiter or hiring manager understands the problem, sees it work, and hears one engineering decision, all in 2 minutes. Record the screen at 1080p with the voice-over. Don't use a webcam unless you want to.

## Before you record
1. `python -m tender_radar seed --rolling`, then `python -m tender_radar match` (with the Gemini key, so real reasons show)
2. `python -m tender_radar brief data/seed/sample_booklet.pdf --profile najd-digital`
3. `uvicorn tender_radar.web.app:create_app --factory`, then open http://127.0.0.1:8000
4. Have `data/seed/sample_booklet.pdf` ready to upload, and the README open in another tab
5. Browser zoom at 125%, notifications off

## Script (about 280 words)

| Time | Screen | Say |
|---|---|---|
| 0:00–0:15 | Company chooser | "Saudi government agencies publish thousands of tenders on Etimad. A small bid team can't read them all, so good tenders are missed and time goes into bad ones. Tender Radar fixes that for a company." |
| 0:15–0:40 | Najd Digital dashboard: scroll, then filter by region | "Every morning it takes the new tenders and runs free rules first: field, deadline, value, region. Most tenders stop there at no cost. The rest are scored by an AI from 0 to 100, with reasons in Arabic and English." |
| 0:40–0:55 | Open a tender with a high score, then 000000001005 (computer and printer maintenance, low score) | "It doesn't just match keywords. This one passes the IT keyword rules, but it's hardware maintenance, not what this company sells, so the AI marks it as a weak fit and explains why." |
| 0:55–1:20 | Reader: upload the sample booklet, open the brief | "When a tender looks good, you upload its booklet. In one step you get the scope, key dates, eligibility and a go/no-go checklist against the company's certificates." |
| 1:20–1:40 | "Ask the booklet": type "ما هي غرامة التأخير؟", then an English question | "You can also ask the booklet questions in Arabic or English. Every answer cites its page, and if the booklet doesn't say, it says so instead of guessing." |
| 1:40–1:55 | README: the evaluation table | "I measured it. On 26 labelled tenders, including 6 traps that pass every keyword rule, it matched human bid decisions on all 26, and the table shows what the AI adds." |
| 1:55–2:00 | GitHub repo | "It runs free on GitHub Actions and Pages, with Python, FastAPI and Gemini. The link is below." |

## Tips
- Say it in your own words: the table is a guide, not something to read word for word.
- If Gemini is slow during the upload, cut the wait in editing.
- Keep the real Etimad imports out of the video (the privacy rule). Use only the synthetic data.
