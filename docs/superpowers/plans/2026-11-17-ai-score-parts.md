# AI Score in Three Parts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gemini judges fit, ability and risk (0–100, one reason each, plus blocker and "prepare"); Python computes the final score; the tender page shows the parts.

**Architecture:** `AIScore` (the AI's JSON) becomes the three parts plus texts; `ScoreParts` is the stored subset, kept on `MatchResult.parts` and in a new nullable JSON column `matches.parts`. `matching/scorer.py` owns the formula (`total_score`). The prompt `score_tender.md` is rewritten; its fingerprint change re-scores everything automatically.

**Tech Stack:** Python 3.12+, Pydantic 2, SQLAlchemy 2 (SQLite), Jinja2, pytest with FakeProvider.

**Spec:** `docs/superpowers/specs/2026-11-17-ai-score-parts-design.md`

## Global Constraints
- Final score = `round(0.5 × fit + 0.3 × ability + 0.2 × (100 − risk))`; with a blocker, `min(that, 40)`.
- fit, ability, risk are integers 0–100; risk: higher = riskier.
- Still exactly one AI call per tender. Tests never call a real AI (FakeProvider only).
- Verdict bands stay 80+ / 50+; free rules unchanged.
- One language per page: English pages show the `_en` texts, Arabic pages the `_ar` texts.
- Old databases keep working: `init_db` adds the nullable `parts` column; matches without parts still render.
- Module docstrings stay plain-words (project convention).

## Review Focus
- Blocker returned as `""` or whitespace → treated as no blocker (no cap, not shown). Test in Task 1.
- Blocker present with high parts → total capped at 40, blocker shown first in the reasons. Test in Task 1.
- A match stored before this change (no `parts`) → tender page falls back to the old reason list. Test in Task 3.
- Gemini returns a part outside 0–100 → validation fails → tender stays "unscored" (retried next run). Test in Task 1.
- `prepare_en` and `prepare_ar` of different lengths → each page shows its own list. Test in Task 3.

---

### Task 1: Score parts model, formula and storage

**Files:**
- Modify: `src/tender_radar/models.py` (AIScore, new ScoreParts, MatchResult.parts)
- Modify: `src/tender_radar/db.py` (MatchRow.parts), `src/tender_radar/repository.py` (save/load parts)
- Modify: `src/tender_radar/matching/scorer.py` (formula, store parts)
- Modify: `src/tender_radar/ai/provider.py` (FakeProvider default)
- Modify tests that build the old shape: `tests/conftest.py`, `tests/test_scorer.py`, `tests/test_provider.py`, `tests/test_models.py`
- Test: `tests/test_score_parts.py`

**Interfaces:**
- Produces:
  - `class ScoreParts(BaseModel)`: `fit`, `ability`, `risk: int = Field(ge=0, le=100)`; `fit_en`, `fit_ar`, `ability_en`, `ability_ar`, `risk_en`, `risk_ar: str`; `blocker_en`, `blocker_ar: str | None = None`; `prepare_en`, `prepare_ar: list[str] = []`; property `has_blocker -> bool` (true only when `blocker_en` or `blocker_ar` has non-space text).
  - `class AIScore(ScoreParts)`: adds `title_en`, `agency_en: str | None = None`.
  - `MatchResult.parts: ScoreParts | None = None`
  - `scorer.WEIGHTS = {"fit": 0.5, "ability": 0.3, "risk": 0.2}`, `scorer.BLOCKER_CAP = 40`
  - `scorer.total_score(parts: ScoreParts) -> int`
  - `scorer.readable_reasons(parts: ScoreParts, lang: str) -> list[str]`: blocker (if any), then fit, ability, risk reasons in `lang`. Stored as `reasons_en` / `reasons_ar`.
  - FakeProvider default `AIScore`: fit 80, ability 70, risk 30, reasons "fake fit"/"fake ability"/"fake risk" (ar: "تجريبي"), → total 75.

- [ ] **Step 1: Write the failing tests** in `tests/test_score_parts.py`:
```python
def parts(**kw):  # helper: valid ScoreParts with overrides
    base = dict(fit=80, ability=70, risk=30, fit_en="f", fit_ar="ف", ability_en="a", ability_ar="ق",
                risk_en="r", risk_ar="خ")
    return ScoreParts(**{**base, **kw})

def test_total_uses_weights(): assert total_score(parts()) == 75          # 40 + 21 + 14
def test_total_extremes(): assert total_score(parts(fit=100, ability=100, risk=0)) == 100
def test_blocker_caps_at_40(): assert total_score(parts(fit=100, ability=100, risk=0, blocker_en="No CR licence")) == 40
def test_blank_blocker_is_no_blocker():
    p = parts(blocker_en="  ", blocker_ar="")
    assert not p.has_blocker and total_score(p) == 75
def test_reasons_order(): assert readable_reasons(parts(blocker_en="B"), "en") == ["B", "f", "a", "r"]
def test_part_out_of_range_is_invalid(): with pytest.raises(ValidationError): parts(risk=120)
def test_run_matching_stores_parts_and_total(...)   # FakeProvider([{...fit 90, ability 80, risk 20...}]) on one rule-passing tender
    # -> match.status == "scored", match.score == 85, match.parts.fit == 90, match.reasons_en[0] == fit_en
def test_parts_survive_the_database(...)            # save_match + get_match round-trips parts; a match saved with parts=None loads parts None
def test_out_of_range_answer_leaves_tender_unscored(...)  # FakeProvider([{... "risk": 150 ...}]) -> status "unscored"
```
Update `tests/conftest.py` so `SCORES` still decide the order: each fake answer is `fit=s, ability=s, risk=100-s` (total = s), reasons `f"reason {s}"` / `f"سبب {s}"` in all three parts. Update `test_scorer.VALID`, `test_provider` and `test_models` to the new shape (same meaning: valid answer / default answer / range check).

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest -q tests/test_score_parts.py` — Expected: FAIL (ImportError on ScoreParts / total_score).

- [ ] **Step 3: Implement** the Interfaces above. In `run_matching`, a scored match is saved with `score=total_score(ai)`, `parts=ScoreParts(**ai.model_dump(exclude={"title_en", "agency_en"}))`, `reasons_en/ar=readable_reasons(ai, "en"/"ar")`. `MatchRow.parts`: `Mapped[dict | None] = mapped_column(JSON, nullable=True)`; repository stores `m.parts.model_dump() if m.parts else None` and loads `ScoreParts.model_validate(row.parts) if row.parts else None`.

- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q` — Expected: all pass (dashboard order still 1004 first).

- [ ] **Step 5: Commit** `feat: AI score in three parts with a Python-computed total`

### Task 2: Rewrite the scoring prompt

**Files:**
- Modify: `src/tender_radar/prompts/score_tender.md`
- Test: `tests/test_scorer.py` (add one test)

**Interfaces:**
- Consumes: the `AIScore` field names from Task 1 (the prompt's JSON example must use exactly them).

- [ ] **Step 1: Write the failing test** `test_prompt_asks_for_parts_not_a_total`:
```python
prompt = build_score_prompt(tender, profile)
for key in ("fit", "ability", "risk", "fit_en", "fit_ar", "blocker_en", "prepare_en", "title_en", "agency_en"):
    assert f'"{key}"' in prompt
assert '"score"' not in prompt
```
- [ ] **Step 2: Run it** — Expected: FAIL (`"fit"` missing / `"score"` present).
- [ ] **Step 3: Rewrite the prompt.** Keep the opening (bid manager's assistant; the keyword filter already let it through). Then:
  - fit: is the MAIN deliverable what the company sells? Goods-only supply, construction, legal work, manpower are weak fits even with IT words. Scale guide: 90+ core business, 60–89 related, below 60 non-core.
  - ability: compare only requirements the tender STATES (licences, classification, certificates, experience) with the profile, plus the value against the range. If the tender states no requirement, say so; never claim the company meets an unstated one.
  - risk (higher = riskier): short timeline, penalties, value near the top of the range, vague scope, limited/invitation-only tender, unusual demands. Low risk is normal for a clear, mid-size tender.
  - blocker: only a stated requirement the company clearly lacks, or non-core main work; else null.
  - prepare: 1–3 concrete things to get ready (documents, partners, questions for the agency).
  - Each reason one sentence, specific to this tender. Do NOT restate rule checks already done (value inside the range, region covered, deadline still open) unless they change the judgement.
  - Use precise numbers; different tenders should not get identical parts.
  - Arabic texts in clear Saudi business Arabic; English and Arabic say the same thing.
  - Keep the title_en / agency_en translation paragraph.
  - End with the exact JSON shape listing every field from Task 1.
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: scoring prompt asks for fit, ability, risk, blocker, prepare`

### Task 3: Show the parts on the tender page

**Files:**
- Modify: `src/tender_radar/web/templates/tender.html` (replace the AI reasons panel when `match.parts` exists)
- Modify: `src/tender_radar/web/app.py` (`render_tender`: pass `parts` rows), `src/tender_radar/web/i18n.py`, `src/tender_radar/web/static/app.css`
- Test: `tests/test_web_tender_page.py`

**Interfaces:**
- Consumes: `MatchResult.parts`, `ScoreParts.has_blocker`, `scorer.WEIGHTS`.
- Produces: `score_parts(match: MatchResult | None, lang: str) -> dict | None` in `web/app.py`: `None` when no parts; else `{"rows": [{"key": "fit"|"ability"|"risk", "value": int, "weight": 50|30|20, "text": str}], "blocker": str | None, "prepare": list[str]}` in `lang`.
- New i18n keys (en / ar): `part_fit` "Fit" / "الملاءمة", `part_ability` "Ability" / "القدرة", `part_risk` "Risk" / "المخاطر", `parts_title` "How the AI scored it" / "كيف قيّمها الذكاء الاصطناعي", `parts_formula` "Score = 50% fit + 30% ability + 20% low risk" / "الدرجة = 50٪ ملاءمة + 30٪ قدرة + 20٪ انخفاض المخاطر", `blocker` "Blocker" / "عائق", `prepare` "Prepare before bidding" / "جهّز قبل التقديم".

- [ ] **Step 1: Write the failing tests** (conftest answers give fit=ability=95, risk=5 for 1004):
```python
def test_tender_page_shows_three_parts(client):
    html = page(client, "000000001004")
    assert "How the AI scored it" in html and "Score = 50% fit + 30% ability + 20% low risk" in html
    assert html.count('class="part ') == 3 and "Ability" in html and "reason 95" in html
def test_parts_in_arabic(client):  # "كيف قيّمها الذكاء الاصطناعي" and "سبب 95" present, "reason 95" absent
def test_blocker_and_prepare_shown(db_settings):  # store a match with blocker_en="No ISO 27001", prepare_en=["Get CR copy"], prepare_ar=["أ","ب"]
    # en page: "Blocker" and "No ISO 27001" and "Get CR copy"; ar page shows both Arabic prepare items
def test_old_match_without_parts_falls_back(db_settings):  # save_match with parts=None, reasons_en=["old reason"]
    # page shows "old reason" and no "How the AI scored it"
```
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest -q tests/test_web_tender_page.py` — Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** The panel shows, per part: label, weight (e.g. "50%"), a bar (`--v: value`; risk bar uses the warn colour and reads "higher = riskier" via its label), the number, the reason. Blocker as an `alert-error` line at the top of the panel; "prepare" as a bullet list under the parts; the formula as a small muted line. Without parts, keep today's reasons list.
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q` — Expected: all pass, including the export one-language test.
- [ ] **Step 5: Commit** `feat: tender page shows how the AI scored it`

### Task 4: Live check with Gemini and project memory

**Files:**
- Modify: `CLAUDE.md` (Decisions: scoring formula; Pending), `src/tender_radar/web/app.py` `EVAL_AGREEMENT` only if the result changes

- [ ] **Step 1:** Run `PYTHONIOENCODING=utf-8 .venv/Scripts/python -m tender_radar match` (twice if any 503 leaves tenders unscored). Expected: every rule-passing tender scored; scores no longer bunched (report them).
- [ ] **Step 2:** Run `PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/eval_matching.py`. Expected: 26/26 (traps 6/6). If lower: adjust the prompt (Task 2) or `WEIGHTS`, re-run, and report the real numbers either way.
- [ ] **Step 3:** Screenshot the 1004 tender page (en + ar) with headless Edge and check the parts panel reads well.
- [ ] **Step 4:** Update `CLAUDE.md` (formula, where weights live, eval result) and commit `docs: project memory - three-part AI score`.
