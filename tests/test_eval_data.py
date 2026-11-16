"""Checks on the evaluation data set (data/eval/).

The "tricky" tenders are meant to test the AI, not the rule filter: each one
looks like IT work, passes the free rules, and is still a no-bid for the
company. If a tricky tender stopped passing the rules, the eval would quietly
go back to measuring the rules only.
"""

import json
from datetime import date
from pathlib import Path

from tender_radar.matching.rules import prefilter
from tender_radar.models import load_seed_tenders

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "eval"
TODAY = date(2026, 11, 15)


def test_tricky_tenders_pass_the_rule_filter(profile):
    tricky = load_seed_tenders(EVAL / "tricky_tenders.json")
    assert len(tricky) >= 6
    for tender in tricky:
        assert prefilter(tender, profile, TODAY).passed, tender.reference


def test_tricky_tenders_are_synthetic_and_never_clash_with_seed(seed_tenders):
    tricky = load_seed_tenders(EVAL / "tricky_tenders.json")
    seed_refs = {t.reference for t in seed_tenders}
    for tender in tricky:
        assert tender.reference.startswith("0000"), tender.reference
        assert tender.reference not in seed_refs
        assert tender.source == "seed"


def test_every_tricky_tender_has_a_label():
    tricky = load_seed_tenders(EVAL / "tricky_tenders.json")
    labels = json.loads((EVAL / "labels.json").read_text(encoding="utf-8"))["labels"]
    labelled = {x["reference"]: x["fit"] for x in labels}
    for tender in tricky:
        assert tender.reference in labelled, tender.reference
