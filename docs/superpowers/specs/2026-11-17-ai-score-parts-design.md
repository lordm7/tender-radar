---
type: decision
date: 2026-11-17
project: tender-radar
status: active
tags: [ai, scoring, prompt, explainability]
---

# AI score in three parts (fit, ability, risk)

## Why
Tender Radar is a portfolio project. In an interview the owner must explain
"how does your AI pick the best tender for a company?" Today Gemini returns
one number (0–100) and 2–3 reasons. Looking at a real Gemini run (2026-11-17):
- most reasons repeat what the free rules already checked (value in range, region covered);
- some reasons guess facts the AI never saw ("holds all required certificates");
- scores bunch together (three tenders at 92), and an AI tender for an AI company
  got 75 mainly for being a "limited tender".

Goal: a score that is more useful, more honest and easy to explain.

## Goals
- The AI judges three things, each 0–100 with one short reason (English + Arabic):
  - **fit**: is the main deliverable the company's kind of work?
  - **ability**: can the company deliver it (size against its range, stated certificates and licences, experience)?
  - **risk**: what could go wrong (tight timeline, penalties, near the top of the value range, unclear scope, limited tender)? Higher = riskier.
- **blocker**: one sentence (en + ar) when there is a hard reason the company cannot bid, else empty.
- **prepare**: 1–3 short things to get ready before bidding (en + ar).
- **Python computes the final score**:
  `round(0.5 × fit + 0.3 × ability + 0.2 × (100 − risk))`, capped at 40 when there is a blocker.
  The weights live in one constant in `matching/scorer.py`.
- The tender page shows the three parts (bar + reason each), the blocker (if any) and "prepare",
  replacing the plain "Why, according to the AI" list.

## Non-goals
- No change to the free rules, the verdict bands (80+/50+), the matches page layout
  (that is part 3) or the "How it works" page (part 2).
- No new AI calls: still one call per tender.

## Anti-goals
- The AI must not repeat rule checks (value in range, region covered, deadline open)
  as reasons; those are already shown in "Profile check".
- The AI must not claim the company meets a requirement the tender does not state.
- Accuracy on the labelled eval set must not drop (today 26/26 with Gemini).

## Approaches
- **A. AI scores the parts, Python computes the total (chosen by the owner).**
  Consistent totals, weights are tunable in code, and the clearest interview story.
- B. AI returns the total and the parts. Simpler, but the parts and the total can disagree.
- C. Keep one number and only improve the reasons. Smallest, but keeps the ties and the weaker story.

## Decided by the owner
- Approach A.

## Builder's calls (stated, can be corrected)
- The AI answer stays flat JSON (easier for Gemini to follow): `fit`, `ability`, `risk`,
  `fit_en/ar`, `ability_en/ar`, `risk_en/ar`, `blocker_en/ar` (nullable), `prepare_en/ar` (lists),
  plus the existing `title_en`, `agency_en`.
- Storage: a new nullable JSON column `parts` on the `matches` table (added automatically
  by `init_db`, no re-seed). `MatchResult` gets an optional `parts`. `reasons_en/ar` keep
  holding the readable reasons (blocker first, then fit, ability, risk), so the digest and
  any old data keep working.
- The prompt changes, so its fingerprint changes and every tender is re-scored on the next
  `match` run (about 13 free Gemini calls for the demo data).
- FakeProvider's default answer gets the new shape (fit 80, ability 70, risk 30 → 75).
- After building, re-run `scripts/eval_matching.py` with Gemini. If agreement drops below
  26/26, tune the prompt or weights and report the numbers honestly.
- The study guide (`notes/study-guide.html`) and README get the new explanation later,
  together with part 2.
