"""Command line: `python -m tender_radar <command>`.

Commands:
  seed    create the database and load the synthetic tenders and demo profile
  match   run the rule filter + AI scoring for the stored profile
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from tender_radar.ai.provider import get_provider
from tender_radar.db import init_db, make_engine, session_scope
from tender_radar.matching.scorer import run_matching
from tender_radar.models import load_profile, load_seed_tenders
from tender_radar.repository import first_profile, save_profile, upsert_tenders
from tender_radar.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = ROOT / "data" / "seed"


def _cmd_seed(args: argparse.Namespace, settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    init_db(engine)
    with session_scope(engine) as s:
        stats = upsert_tenders(s, load_seed_tenders(SEED_DIR / "tenders.json"))
        save_profile(s, load_profile(SEED_DIR / "profile_it_services.json"))
    engine.dispose()
    print(f"Tenders: {stats.inserted} new, {stats.updated} updated, {stats.unchanged} unchanged")
    return 0


def _cmd_match(args: argparse.Namespace, settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    init_db(engine)
    with session_scope(engine) as s:
        profile = first_profile(s)
        if profile is None:
            print("No company profile yet. Run: python -m tender_radar seed")
            return 1
        stats = run_matching(s, profile, get_provider(settings), args.today)
    engine.dispose()
    print(f"Scored {stats.scored}, filtered out {stats.filtered_out}, unscored {stats.unscored}, cached {stats.cached}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tender_radar", description="Tender Radar command line")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="load synthetic demo data").set_defaults(handler=_cmd_seed)

    match = sub.add_parser("match", help="score tenders against the company profile")
    match.add_argument("--today", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")
    match.set_defaults(handler=_cmd_match)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a non-Arabic code page
    args = build_parser().parse_args(argv)
    return args.handler(args, Settings())


if __name__ == "__main__":
    raise SystemExit(main())
