# Matches Page Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Honest verdict numbers, AI parts in the selected panel, a grouped and richer list, and a sticky two-column layout.

**Architecture:** `_tender_card` gains `verdict`, `value`, `parts`; `render_dashboard` builds verdict stats and groups; `dashboard.html` renders them; `app.js` updates the selected panel's verdict/parts and hides empty groups; CSS for the layout.

**Spec:** `docs/superpowers/specs/2026-11-17-matches-page-polish-design.md`

## Global Constraints
- One language per page (export test). Embedded JSON escapes `<`. JS uses textContent only.
- Only public seed tenders in read-only views (unchanged `_rows`).

## Review Focus
- A filter that hides every row of a group → that group's heading hides too (app.js; checked in the browser).
- Selecting a tender scored before parts existed → the panel shows its reason, no empty bars. Test in Task 1.
- An unscored tender (AI failed) → "Not scored yet" group, no verdict. Test in Task 1.
- Arabic page → group headings and meta line are Arabic; untranslated agency marked `lang="ar"` on English pages. Export test.
- Phone width → one column, no sticky. Screenshot.

### Task 1: Data and page
**Files:** `web/app.py`, `templates/dashboard.html`, `web/i18n.py`, `static/app.css`, `static/app.js`; test `tests/test_web_dashboard.py`.
Conftest scores: 95, 82 → bid (2); 75, 71, 66, 60, 58, 50 → consider (6); 40 → skip (1).
- [ ] Failing tests: `test_header_counts_by_verdict` (`<b>2</b> worth bidding`, `<b>6</b> worth a closer look`, no "worth a look");
  `test_list_grouped_by_verdict` (headings "Worth bidding (2)", "Worth a closer look (6)", "Probably skip (1)" in that order);
  `test_row_shows_agency_value_and_days` (1004's row has "2,200,000 SAR" and its English agency);
  `test_selected_panel_shows_parts` (`id="sel-parts"` with 3 `class="part `, `id="sel-verdict"` "Worth bidding");
  `test_selected_panel_without_parts_shows_reason`; `test_unscored_tender_in_its_own_group`; Arabic headings test.
- [ ] Run → FAIL. Implement. Full suite → PASS.
### Task 2: Check, README, study guide
- [ ] Screenshots en/ar/phone; click-through of selection and filters in a browser.
- [ ] README + `notes/study-guide.html` (+ republish the online copy) + CLAUDE.md.
- [ ] Final review by a fresh reviewer; fix Critical/Important test-first.
