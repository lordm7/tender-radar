---
type: decision
date: 2026-11-17
project: tender-radar
status: active
tags: [explainability, interview, how-it-works, page]
---

# "How it works" page

## Why
In an interview the owner must answer "how does your AI use Etimad to find the best
tender for a company?". One page that walks through the real pipeline with real
numbers lets them answer by showing, and keeps them honest about what each part does.

## Goals
- A page `/{lang}/how` (en + ar, one language per page), in the static export as `{lang}/how.html`.
- Linked from the top menu on every page ("How it works") and from the home page's
  "How it works" section ("See the full pipeline").
- Three sections, every number computed from the database at render time:
  1. **Pipeline** (5 steps): Etimad list → free rules → AI score → best first → booklet brief.
     Each step: what it does (one sentence), the count for this step, the tool
     (Python import, rules, Gemini, sort, PyMuPDF + Gemini) and the source file.
  2. **One tender, step by step**: the best-scored public tender that has AI parts,
     traced: the rule checks (the existing Profile check rows), the three AI parts with
     their reasons, the formula with its real numbers
     (`0.5 × 95 + 0.3 × 90 + 0.2 × (100 − 35) = 87.5 → 88`) and the verdict.
  3. **Built with** (Python, FastAPI, Jinja, SQLite + SQLAlchemy, Gemini free tier,
     PyMuPDF, GitHub Actions + Pages) and **How good is it?** (`EVAL_AGREEMENT`, traps note).

## Non-goals
- No new AI calls, no new data. No change to the home page beyond one link.

## Anti-goals
- Numbers that don't match the matches page. (They come from the same functions.)
- Mixed languages on a page: tool names and file paths are Latin, so on Arabic pages
  they are marked `lang="en" dir="ltr"`.
- Showing private imported tenders: like every read-only view, only public (seed) tenders.

## Approaches
- **A. Dedicated page with live numbers and one traced tender (chosen by the owner).**
- B. A bigger section on the home page: makes the home page too long.
- C. A fixed picture without real numbers: goes stale, less convincing.

## Builder's calls
- The numbers are for one company: the company of the traced tender (the pipeline is per
  company, because the rules depend on the bidding profile). The page names it.
- Traced tender: highest score among public tenders with `parts`, across all companies;
  ties break by tender reference. With no such tender, section 2 is hidden.
- Formula text is built from `WEIGHTS`, so changing the weights updates the page.
- Reuse: `_rows`, `is_public`, `profile_check`, `score_parts`, `total_score`, `verdict_key`.
