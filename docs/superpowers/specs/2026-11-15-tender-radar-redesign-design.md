---
type: decision
date: 2026-11-15
project: tender-radar
status: active
tags: [design, ui, i18n, portfolio]
---

# Tender Radar — Redesign (professional look, full EN/AR)

## Intent / why
- The user shows Tender Radar to recruiters, HR and potential customers. Their verdict on the current UI: "it's good, but it's so messy".
- Their specific complaints:
  - the buttons
  - there is no page that tells people what the product is and who made it
  - there is no English/Arabic switch
  - the "Company profile" button reads like "about us"
- **Goal:** someone opening the demo link thinks "wow, this is professional", understands the product in seconds, and sees who built it.
- **The user is the judge of design.** The mockups below were chosen by them over several rounds:
  - they picked a dark "radar" style
  - "more interesting" became a radar + mission-control mix
  - "less space" became a compact layout
  - "more professional" became the calm final version

## Approved mockups (the source of truth for the look)
- `docs/superpowers/specs/mockups/home.html`: the home / "about" page.
- `docs/superpowers/specs/mockups/matches.html`: the matches page (company dashboard).
- `docs/superpowers/specs/mockups/language-modes.html`: the same page in English mode and in Arabic mode.

These are hand-made HTML sketches with sample numbers. Build their structure and style, not their exact pixels or numbers.

## Goals
1. **New home page** (`/`, the "about" page). It doubles as the static demo's landing page. Sections, top to bottom:
   - **Nav:** logo (radar line icon + "Tender Radar"), Product / How it works / About, the EN·ع switch, and a "Live demo" button.
   - **Hero:**
     - eyebrow "Tender intelligence for Saudi B2B"
     - headline "Know which government tenders are worth bidding on."
     - one-paragraph pitch
     - buttons: "Open live demo" (goes to the company chooser or the dashboard) and "View source" (GitHub repo URL)
     - a product preview in a browser frame: the compact matches view with live data, not a static image
   - **Stats band**, built from live data:
     - tenders screened today
     - share filtered by rules without AI cost
     - "19 / 20 agreement with human bid calls" (from `data/eval/labels.json` results; a constant is fine, labelled honestly)
     - "0 SAR monthly running cost"
   - **How it works:** three columns (Screen → Score → Decide) with thin line icons.
   - **Footer:**
     - "Built by Mohammed Alzalam · AI & Automation Engineer, Riyadh" with GitHub and LinkedIn links
     - "Demo data is synthetic and shaped like public Etimad listings. Tender Radar is not affiliated with Etimad."
2. **Matches page** (the company dashboard, today's `/c/<id>/`), compact:
   - **Same nav** across the app: Matches · Booklet reader · Bidding profile, a company picker, and the EN·ع switch.
   - **Header row:** company name, date, and four numbers: worth a look, filtered by rules, closing this week, regions.
   - **Three panels side by side:**
     - **Fit radar:** an SVG. Each tender that passed the rules is a dot; filtered ones are faint grey.
       - distance from the centre = 100 − score
       - gold = closes within 7 days
       - a slow, subtle sweep
       - clicking a dot selects that tender
     - **Selected tender:** a score ring, title, one-line AI reason, closing date with days left, booklet price, inquiry deadline, and buttons "Open tender" and "Brief the booklet" (to the reader or the sample brief).
     - **All matches list:** compact rows (score, title, days left), the filters (score / agency / deadline), and a collapsed "N filtered by rules" section with reasons.
   - Clicking a row or a dot updates the selected panel without a page reload (vanilla JS; the data comes embedded in the page as JSON).
3. **The other pages get the same style:** company chooser, tender detail, booklet brief, booklet reader (upload), bidding profile (form). There are no separate mockups; the user reviews them after the build.
4. **One language per page.** In English mode every visible word is English; in Arabic mode every visible word is Arabic and the whole page is right-to-left (layout mirrored, menus included). This covers:
   - UI text: menus, buttons, labels, messages, numbers' units, "days left", errors.
   - **Tender title and agency:**
     - Seed tenders get hand-written English `title_en` / `agency_en` in `data/seed/tenders.json`.
     - Imported (real) tenders get them from the existing AI scoring call: add `title_en` and `agency_en` to the score response. No extra AI calls.
     - A tender with no English text (a filtered-out import never sent to the AI) shows its Arabic title with a small "Arabic original" tag in English mode. This and the Bidding profile form fields (see My calls) are the only exceptions.
   - **AI reasons:** these are already `reasons_en` / `reasons_ar`; show only the page's language. The selected panel shows the first reason.
   - **Booklet brief:**
     - the AI produces both languages in one call (each text field in EN and AR, or two full briefs: builder's call)
     - existing stored briefs that only have Arabic show Arabic with the "Arabic original" tag in English mode
   - **Activity, region and tender type:** these come from a short fixed vocabulary (e.g. تقنية المعلومات, الرياض, منافسة عامة). Translate them with a lookup table; unknown values fall back to the original with the tag.
5. **Language switch:**
   - **URLs:** `/en/...` and `/ar/...` (e.g. `/ar/c/najd-digital/`). `/` redirects to the last chosen language (cookie), defaulting to English.
   - **The switch** keeps you on the same page in the other language.
   - **The static export** writes both trees (`en/…`, `ar/…`) plus a root `index.html` that sends visitors to `en/`. The switch therefore works on GitHub Pages without a server.
6. **Rename "Company profile" to "Bidding profile"** (Arabic: "ملف المنافسة" or the builder's better term). The "about" content lives on the home page.
7. **Own stylesheet instead of the Tailwind CDN:**
   - one hand-written CSS file with design tokens (colours, spacing, radius, type scale)
   - logical properties (`margin-inline-start` etc.) so RTL mirrors automatically
   - fonts: Inter + IBM Plex Sans Arabic (Google Fonts, as today)
   - no console warnings
8. **Accessibility basics:** keyboard focus styles; the radar dots also reachable through the list; text contrast at least WCAG AA on the dark background; `lang` and `dir` set on `<html>`.

## Non-goals
- No React or other front-end framework, and no JS build step.
- No change to matching, rules, importer, digest or pipeline behaviour, except adding `title_en`/`agency_en` to scoring and bilingual brief output.
- No user accounts or login.
- No mobile app. Pages must still be usable on a phone; the radar may stack above the list.
- The email digest keeps its current look. Restyling it is out of scope.

## Anti-goals (it fails if…)
- Any page mixes languages, apart from the single "Arabic original" exception.
- It looks playful (emoji icons, neon glow) rather than professional.
- The static GitHub Pages demo breaks, or loses the language switch.
- Real imported tenders become visible in public or read-only pages. The `is_public` rule from Plan 2 must keep holding in both languages.
- The page becomes slow or heavy: no large libraries for the radar.

## Constraints
- Python, FastAPI, Jinja2, vanilla JS (decided: Approach A below).
- Zero running cost.
- **Existing tests keep passing, adapted to new URLs and markup where needed.**
  - New tests cover the language rule (no Arabic letters in English-mode pages for seed data, and the reverse for UI strings), RTL attributes, and both export trees.
  - Tests still never call a real AI.
- Seed data stays synthetic; English names stay fictional.
- Windows dev machine. Arabic text must render correctly (NFKC rules from Plan 1 still apply).

## Approaches considered
- **A. Keep the FastAPI + Jinja app and rewrite templates, CSS and a little vanilla JS (chosen by the user).** Logic and tests stay; everything stays Python and explainable; the static demo keeps working.
- **B. A React/Next.js front end.** Rejected: a second language to defend, a full rewrite, and it breaks the free static-demo setup, with no visible gain.
- **C. HTMX/Alpine helpers.** Rejected: extra tools with no visible gain over A.

## Decided by the user
- The dark, calm, professional style of the approved mockups, with a small subtle radar as the brand mark.
- The matches page combines the radar with mission-control panels, in a compact layout.
- One language per page, translated as described (including AI-provided English titles for real tenders).
- Approach A. Plan 2 is merged to `main` first (done 2026-11-15); this work is on branch `feat/redesign`.

## My calls (the user can override)
- The name "Bidding profile" / "ملف المنافسة".
- **URL scheme:** `/en/` and `/ar/` prefixes, with the cookie used only for the `/` redirect.
- **"Live demo" target:** the company chooser when there are several companies, else the dashboard. The live app's chooser stays as a page; the home page is new.
- **Footer details:** the name and title "Mohammed Alzalam · AI & Automation Engineer, Riyadh" and the GitHub link `https://github.com/lordm7/tender-radar`. The LinkedIn URL is a placeholder until the user gives it.
- **Radar data:** only the current company's tenders; positions are deterministic, with the angle derived from the reference hash, so screenshots are stable.
- **Tender description:**
  - Seed tenders get a hand-written `description_en`.
  - Imported tenders have no description; the importer never fills one, so nothing needs translating.
  - If a description has no English text, English mode hides it and shows no tag.
- **Where the English title and agency are stored:**
  - On the tender row, shared by all companies, as `title_en` / `agency_en`.
  - Written by the scoring call only when they are empty, and kept when the same tender is imported again with unchanged Arabic text.
  - No cache invalidation: already-scored imports keep the "Arabic original" tag until they are naturally re-scored (content or profile change). The demo's seed tenders are hand-translated, so they are unaffected.
- **Company profile data:**
  - Each profile gets a `name_ar` (seed: hand-written; the form gets one more field).
  - Activities, regions and certifications shown outside the form (chooser cards, header) go through the lookup table; untranslatable ones are left out of those summaries.
  - **Inside the Bidding profile form**, the keywords and lists are shown exactly as stored, with every label and hint translated. They are the company's own matching terms: Arabic tenders need Arabic keywords, so translating them would break matching.
  - This is the second, deliberate exception to the one-language rule, and it applies only inside form fields.
- **Home page data:**
  - Always public-only (`is_public`), even in the live non-read-only app, because it is the recruiter-facing page. Real imports must never appear in it or in screenshots or videos of it.
  - The stats are totals across all companies' public data.
  - The product preview shows the first company in id order with its public matches.
  - A test enforces this.

## Left to the builder
- Template structure, the translation mechanism (a simple dict per language is fine), CSS file layout and the exact colour tokens (match the mockups).
- How the bilingual brief is shaped in `BookletBrief`, keeping old stored briefs readable.
- Whether to keep `/c/<id>/` as a redirect to `/en/c/<id>/`.
