"""Command line: `python -m tender_radar <command>`.

Commands:
  seed    create the database and load the synthetic tenders and every demo company profile
  match   run the rule filter + AI scoring (all companies, or --profile ID)
  brief   summarise a tender booklet PDF into a bid brief
  export  write the read-only static demo site (for GitHub Pages)
  import  read tenders from Etimad list text/HTML that a person copied or saved (kept private)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from tender_radar.ai.provider import AIError, get_provider
from tender_radar.db import init_db, make_engine, session_scope
from tender_radar.matching.scorer import run_matching
from tender_radar.models import load_profile, load_seed_tenders
from tender_radar.reader.brief import build_brief
from tender_radar.reader.pdf_text import UnreadablePDF, extract_pages
from tender_radar.models import CompanyProfile
from tender_radar.repository import first_profile, get_profile, list_profiles, save_brief, save_profile, upsert_tenders
from tender_radar.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = ROOT / "data" / "seed"


def _cmd_seed(args: argparse.Namespace, settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    init_db(engine)
    with session_scope(engine) as s:
        stats = upsert_tenders(s, load_seed_tenders(SEED_DIR / "tenders.json"))
        profiles = [load_profile(path) for path in sorted(SEED_DIR.glob("profile_*.json"))]
        for profile in profiles:
            save_profile(s, profile)
    engine.dispose()
    print(f"Tenders: {stats.inserted} new, {stats.updated} updated, {stats.unchanged} unchanged")
    print(f"Companies: {', '.join(p.name for p in profiles)}")
    return 0


def _pick_profiles(session, wanted: str | None, default_all: bool) -> list[CompanyProfile] | None:
    """The profiles a command should use; prints a message and returns None if there are none."""
    if wanted:
        profile = get_profile(session, wanted)
        if profile is None:
            print(f"No company profile '{wanted}'. Known: {', '.join(p.id for p in list_profiles(session)) or 'none'}")
            return None
        return [profile]
    profiles = list_profiles(session) if default_all else [p for p in [first_profile(session)] if p]
    if not profiles:
        print("No company profile yet. Run: python -m tender_radar seed")
        return None
    return profiles


def _cmd_match(args: argparse.Namespace, settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    init_db(engine)
    provider = get_provider(settings)
    with session_scope(engine) as s:
        profiles = _pick_profiles(s, args.profile, default_all=True)
        if profiles is None:
            return 1
        for profile in profiles:
            stats = run_matching(s, profile, provider, args.today)
            print(f"{profile.name}: scored {stats.scored}, filtered out {stats.filtered_out}, "
                  f"unscored {stats.unscored}, cached {stats.cached}")
    engine.dispose()
    return 0


def _cmd_brief(args: argparse.Namespace, settings: Settings) -> int:
    path = Path(args.path)
    try:
        pages = extract_pages(path)
    except UnreadablePDF as exc:
        print(f"Cannot read {path.name}: {exc}")
        return 1
    engine = make_engine(settings.database_url)
    init_db(engine)
    with session_scope(engine) as s:
        profiles = _pick_profiles(s, args.profile, default_all=False)
        if profiles is None:
            return 1
        profile = profiles[0]
        try:
            brief = build_brief(pages, profile, get_provider(settings))
        except (AIError, ValidationError) as exc:
            print(f"The AI could not read this booklet right now ({exc}). Please try again later.")
            return 1
        brief_id = save_brief(s, path.name, brief)
    engine.dispose()
    print(json.dumps(brief.model_dump(), ensure_ascii=False, indent=2))
    print(f"Saved as brief #{brief_id}")
    return 0


def _read_import_file(path: Path) -> str:
    """Saved pages are usually UTF-8; older Arabic Windows tools save as cp1256."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1256", errors="replace")
    if path.suffix.lower() in (".html", ".htm"):
        from tender_radar.importer.etimad_html import html_to_text

        text = html_to_text(text)
    return text


def _cmd_import(args: argparse.Namespace, settings: Settings) -> int:
    from tender_radar.importer.etimad_text import parse_etimad_text

    paths = [Path(p) for p in args.paths]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        print(f"File not found: {', '.join(missing)}")
        return 1
    engine = make_engine(settings.database_url)
    init_db(engine)
    for path in paths:
        result = parse_etimad_text(_read_import_file(path))
        with session_scope(engine) as s:
            stats = upsert_tenders(s, result.tenders)
        print(f"{path.name}: {stats.inserted} new, {stats.updated} updated, {stats.unchanged} unchanged, {len(result.skipped)} skipped")
        for reason in result.skipped:
            print(f"  skipped {reason}")
    engine.dispose()
    print("Imported tenders are private: they never appear in the exported demo. Next: python -m tender_radar match")
    return 0


def _cmd_export(args: argparse.Namespace, settings: Settings) -> int:
    from tender_radar.export.static_site import ExportError, export_site

    engine = make_engine(settings.database_url)
    init_db(engine)
    with session_scope(engine) as s:
        profiles = _pick_profiles(s, args.profile, default_all=True)
        if profiles is None:
            return 1
        try:
            written = export_site(s, profiles, args.today, Path(args.out))
        except ExportError as exc:
            print(f"Export stopped: {exc}")
            return 1
    engine.dispose()
    print(f"Wrote {len(written)} files to {args.out}/ (open {args.out}/index.html)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tender_radar", description="Tender Radar command line")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="load synthetic demo data").set_defaults(handler=_cmd_seed)

    match = sub.add_parser("match", help="score tenders against the company profile")
    match.add_argument("--today", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")
    match.add_argument("--profile", help="company id (default: every company)")
    match.set_defaults(handler=_cmd_match)

    brief = sub.add_parser("brief", help="summarise a tender booklet PDF with AI")
    brief.add_argument("path", help="path to the booklet PDF")
    brief.add_argument("--profile", help="company to check eligibility for (default: the first)")
    brief.set_defaults(handler=_cmd_brief)

    export = sub.add_parser("export", help="write the read-only static demo site")
    export.add_argument("--out", default="site", help="output folder (default: site)")
    export.add_argument("--today", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")
    export.add_argument("--profile", help="export one company only (default: every company)")
    export.set_defaults(handler=_cmd_export)

    imp = sub.add_parser("import", help="import Etimad list text/HTML you copied or saved (private)")
    imp.add_argument("paths", nargs="+", help=".txt (copied text) or .html (saved page) files")
    imp.set_defaults(handler=_cmd_import)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a non-Arabic code page
    args = build_parser().parse_args(argv)
    return args.handler(args, Settings())


if __name__ == "__main__":
    raise SystemExit(main())
