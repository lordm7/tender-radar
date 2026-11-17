---
type: decision
date: 2026-11-17
project: tender-radar
status: active
tags: [matches-page, ui, polish]
---

# Matches page polish

## Why
The matches page is the first thing an interviewer clicks. Today it says "9 worth a look" for tenders
the verdict calls "closer look", shows one AI sentence for the selected tender, cuts long titles, and
leaves a large empty area under the radar.

## Goals (approved by the owner, 2026-11-17)
- Header numbers by verdict: worth bidding · worth a closer look · filtered by rules · closes this week.
- Selected tender: verdict word, the three AI parts as bars (fit / ability / risk), the blocker if any,
  then the existing facts and actions. Old scores without parts keep the one-sentence reason.
- List grouped by verdict (Worth bidding / Worth a closer look / Probably skip / Not scored yet) with a
  count per group; each row shows the full title (up to 2 lines) and a meta line: agency · value · days left.
- Layout: two columns, the radar and the selected tender stacked on the left and kept in view while the
  list scrolls (sticky); stacked on phones.
- Same in Arabic (RTL), one language per page.
- Then: README and the interview study guide updated with parts 1-3.

## Non-goals
- No change to the tender page (redesigned earlier the same day) or to the home page preview.

## Approaches
- **A. Polish the existing page (chosen).** Same data, same JS approach (embedded JSON, works on GitHub Pages).
- B. A table view with sortable columns: denser, but loses the radar story.

## Builder's calls
- Group order follows the verdict bands; the score filter and agency/deadline filters keep working;
  a group heading hides when the filters hide all its rows.
- The parts bars in the selected panel are filled by app.js from the embedded JSON using textContent only.
