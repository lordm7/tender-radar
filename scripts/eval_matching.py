"""Measure the AI matching against your own hand labels. Manual; not run in CI.

1. Open data/eval/labels.json and set each "fit" to true or false.
2. Run with the real provider:
       python scripts/eval_matching.py
It runs matching on the seed data plus the eval-only "tricky" tenders
(data/eval/tricky_tenders.json) in a temporary in-memory database, treats a
score of 60 or more as "fit", and prints the agreement overall and on the
tricky set alone (the part that really tests the AI, since those tenders all
pass the free rules). It exits with 1 when overall agreement is under 80%
(the quality bar in the design).
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from tender_radar.ai.provider import get_provider
from tender_radar.db import init_db, make_engine, session_scope
from tender_radar.matching.scorer import run_matching
from tender_radar.models import load_profile, load_seed_tenders
from tender_radar.repository import get_match, upsert_tenders
from tender_radar.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
FIT_THRESHOLD = 60
REQUIRED_AGREEMENT = 0.80
MAX_PASSES = 3


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    labels = json.loads((ROOT / "data/eval/labels.json").read_text(encoding="utf-8"))["labels"]
    labelled = [x for x in labels if x["fit"] is not None]
    if not labelled:
        print("No labels yet: set 'fit' to true/false in data/eval/labels.json first.")
        return 1

    engine = make_engine("sqlite://")
    init_db(engine)
    profile = load_profile(ROOT / "data/seed/profile_it_services.json")
    with session_scope(engine) as s:
        upsert_tenders(s, load_seed_tenders(ROOT / "data/seed/tenders.json"))
        upsert_tenders(s, load_seed_tenders(ROOT / "data/eval/tricky_tenders.json"))
        provider = get_provider(Settings())
        for _attempt in range(MAX_PASSES):  # AI outages (429/503) are retried, never counted as answers
            if run_matching(s, profile, provider, date.today()).unscored == 0:
                break

    tricky_refs = {t.reference for t in load_seed_tenders(ROOT / "data/eval/tricky_tenders.json")}
    agree, outages, tricky_agree, tricky_graded = 0, [], 0, 0
    with session_scope(engine) as s:
        for x in labelled:
            m = get_match(s, x["reference"], profile.id)
            if m is not None and m.status == "unscored":
                outages.append(x["reference"])
                print(f"SKIP {x['reference']} AI unavailable (not counted)")
                continue
            predicted = m is not None and m.status == "scored" and (m.score or 0) >= FIT_THRESHOLD
            ok = predicted == x["fit"]
            agree += ok
            if x["reference"] in tricky_refs:
                tricky_graded += 1
                tricky_agree += ok
            print(f"{'OK  ' if ok else 'MISS'} {x['reference']} you={x['fit']} ai={predicted} score={m.score if m else None}")
    graded = len(labelled) - len(outages)
    if graded == 0:
        print("The AI was unavailable for every tender; try again later.")
        return 1
    ratio = agree / graded
    print(f"\nAgreement: {agree}/{graded} = {ratio:.0%} (bar: {REQUIRED_AGREEMENT:.0%})")
    if tricky_graded:
        print(f"Tricky set (passes the rules, so it tests the AI): {tricky_agree}/{tricky_graded}")
    if outages:
        print(f"Not graded because the AI was unavailable: {', '.join(outages)}")
    return 0 if ratio >= REQUIRED_AGREEMENT else 1


if __name__ == "__main__":
    raise SystemExit(main())
