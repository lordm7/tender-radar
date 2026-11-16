"""Command line: `python -m tender_radar <command>`.

Commands:
  seed    create the database and load the synthetic tenders and every demo company profile
  match   run the rule filter + AI scoring (all companies, or --profile ID)
  brief   summarise a tender booklet PDF into a bid brief
  ask     ask questions about a booklet; answers cite the booklet page
  export  write the read-only static demo site (for GitHub Pages)
  digest  email today's best matches to yourself (or save a preview without SMTP)
  daily   the whole daily pipeline: fresh demo dates, match, sample brief, export, digest
  import  read tenders from Etimad list text/HTML that a person copied or saved (kept private)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from tender_radar.ai.provider import AIError, get_provider
from tender_radar.db import init_db, make_engine, session_scope
from tender_radar.matching.scorer import run_matching
from tender_radar.models import SEED_ANCHOR, load_profile, load_seed_tenders, shift_dates
from tender_radar.reader.ask import answer_question
from tender_radar.reader.brief import build_brief
from tender_radar.reader.pdf_text import UnreadablePDF, extract_pages
from tender_radar.models import CompanyProfile
from tender_radar.repository import (
    first_profile, get_profile, latest_brief_id, list_profiles, save_answer, save_brief, save_profile, upsert_tenders,
)
from tender_radar.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = ROOT / "data" / "seed"
SAMPLE_BOOKLET_PROFILE = "najd-digital"  # the sample booklet is an IT tender; judge it as the IT firm
# Asked about the sample booklet every day, so the public demo shows "Ask the booklet"
# working. One list per language: each demo page shows only its own language's questions.
SAMPLE_QUESTIONS = {
    "en": [
        "What is the late-delivery penalty, and what is its maximum?",
        "Is an ISO 27001 certificate required?",
        "What is the minimum technical score needed to pass?",
    ],
    "ar": [
        "ما هي غرامة التأخير وما حدها الأقصى؟",
        "هل يشترط الحصول على شهادة ISO 27001؟",
        "ما الحد الأدنى للنجاح الفني؟",
    ],
}


def _cmd_seed(args: argparse.Namespace, settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    init_db(engine)
    with session_scope(engine) as s:
        tenders = load_seed_tenders(SEED_DIR / "tenders.json")
        if args.rolling:  # keep the public demo current: move every date forward to today
            tenders = shift_dates(tenders, anchor=SEED_ANCHOR, today=args.today)
        stats = upsert_tenders(s, tenders)
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
        brief_id = save_brief(s, path.name, brief, pages=pages)
    engine.dispose()
    print(json.dumps(brief.model_dump(), ensure_ascii=False, indent=2))
    print(f"Saved as brief #{brief_id}")
    return 0


def _cmd_ask(args: argparse.Namespace, settings: Settings) -> int:
    """Answer questions about a booklet; store them on its newest brief, if there is one."""
    path = Path(args.path)
    try:
        pages = extract_pages(path)
    except UnreadablePDF as exc:
        print(f"Cannot read {path.name}: {exc}")
        return 1
    provider = get_provider(settings)
    engine = make_engine(settings.database_url)
    init_db(engine)
    failed = 0
    for question in args.questions:
        try:
            answer = answer_question(question, pages, provider)
        except (AIError, ValidationError) as exc:
            print(f"Q: {question}")
            print(f"The AI could not answer right now ({exc}).")
            failed += 1
            continue
        pages_note = ", ".join(f"p. {n}" for n in answer.citations) or "no page cited"
        print(f"Q: {question}")
        print(f"A: {answer.answer}")
        print(f"   [{pages_note}]")
        lang = args.lang or ("ar" if any(0x0600 <= ord(ch) <= 0x06FF for ch in question) else "en")  # Arabic letters?
        with session_scope(engine) as s:
            brief_id = latest_brief_id(s, path.name)
            if brief_id is not None:
                save_answer(s, brief_id, question, answer, lang=lang)
    engine.dispose()
    return 1 if failed == len(args.questions) else 0


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
        for warning in result.warnings:
            print(f"  warning {warning}")
    engine.dispose()
    print("Imported tenders are never published in the exported demo. Note: `match` sends their title, agency")
    print("and activity to your AI provider for scoring, and `digest` emails them to you. Next: python -m tender_radar match")
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


def _cmd_digest(args: argparse.Namespace, settings: Settings) -> int:
    from tender_radar.digest import build_digest, send_digest

    engine = make_engine(settings.database_url)
    init_db(engine)
    out = Path(args.out)
    with session_scope(engine) as s:
        profiles = _pick_profiles(s, args.profile, default_all=True)
        if profiles is None:
            return 1
        digests = [(p, build_digest(s, p, args.today)) for p in profiles]
    engine.dispose()
    for profile, digest in digests:
        if digest.count == 0:
            print(f"{profile.name}: nothing new worth emailing today")
            continue
        if args.dry_run or not settings.smtp_configured:
            out.mkdir(parents=True, exist_ok=True)
            preview = out / f"{profile.id}.html"
            preview.write_text(digest.html, encoding="utf-8")
            why = "dry run" if args.dry_run else "SMTP not configured"
            print(f"{profile.name}: {digest.count} matches, not sent ({why}); preview saved to {preview}")
            continue
        try:
            send_digest(digest, settings)
        except OSError as exc:  # smtplib errors are OSErrors too
            print(f"{profile.name}: sending failed ({exc.__class__.__name__}: {exc})")
            return 1
        print(f"{profile.name}: {digest.count} matches sent to {settings.digest_to}")
    return 0


def _cmd_daily(args: argparse.Namespace, settings: Settings) -> int:
    """Run every daily step. AI or email problems are reported but never stop the
    export: the public demo must always be rebuilt (tenders show "not scored")."""
    today = args.today.isoformat()
    steps = [
        ("seed", ["seed", "--rolling", "--today", today], True),
        ("match", ["match", "--today", today], False),
        ("brief", ["brief", str(SEED_DIR / "sample_booklet.pdf"), "--profile", SAMPLE_BOOKLET_PROFILE], False),
        *[
            (f"ask ({lang})", ["ask", str(SEED_DIR / "sample_booklet.pdf"), *questions, "--lang", lang], False)
            for lang, questions in SAMPLE_QUESTIONS.items()
        ],
        ("export", ["export", "--out", args.out, "--today", today], True),
    ]
    if settings.smtp_configured:
        steps.append(("digest", ["digest", "--today", today], False))
    for name, argv, required in steps:
        print(f"== {name}")
        try:
            code = main(argv)
        except Exception as exc:  # e.g. the AI is selected but has no key
            print(f"{exc.__class__.__name__}: {exc}")
            code = 1
        if code != 0:
            if required:
                print(f"{name} step failed; stopping")
                return 1
            print(f"{name} step failed (continuing; the demo is still built)")
    _report_status(settings)
    return 0


def _report_status(settings: Settings) -> None:
    """Tell GitHub Actions how many tenders got a real score, so the deploy step can
    keep yesterday's demo online instead of publishing an all-"not scored" one."""
    from tender_radar.repository import list_matches

    engine = make_engine(settings.database_url)
    with session_scope(engine) as s:
        scored = sum(m.status == "scored" for p in list_profiles(s) for m in list_matches(s, p.id))
    engine.dispose()
    print(f"scored_total={scored}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"scored_total={scored}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tender_radar", description="Tender Radar command line")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="load synthetic demo data")
    seed.add_argument("--rolling", action="store_true", help="shift demo dates so they stay current")
    seed.add_argument("--today", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD (with --rolling)")
    seed.set_defaults(handler=_cmd_seed)

    match = sub.add_parser("match", help="score tenders against the company profile")
    match.add_argument("--today", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")
    match.add_argument("--profile", help="company id (default: every company)")
    match.set_defaults(handler=_cmd_match)

    brief = sub.add_parser("brief", help="summarise a tender booklet PDF with AI")
    brief.add_argument("path", help="path to the booklet PDF")
    brief.add_argument("--profile", help="company to check eligibility for (default: the first)")
    brief.set_defaults(handler=_cmd_brief)

    ask = sub.add_parser("ask", help="ask questions about a booklet PDF (answers cite pages)")
    ask.add_argument("path", help="path to the booklet PDF")
    ask.add_argument("questions", nargs="+", help="one or more questions, in Arabic or English")
    ask.add_argument("--lang", choices=["en", "ar"], help="page language to show the answers on (default: guessed from the question)")
    ask.set_defaults(handler=_cmd_ask)

    export = sub.add_parser("export", help="write the read-only static demo site")
    export.add_argument("--out", default="site", help="output folder (default: site)")
    export.add_argument("--today", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")
    export.add_argument("--profile", help="export one company only (default: every company)")
    export.set_defaults(handler=_cmd_export)

    digest = sub.add_parser("digest", help="email today's best matches to yourself")
    digest.add_argument("--profile", help="company id (default: every company)")
    digest.add_argument("--dry-run", action="store_true", help="never send; only save a preview")
    digest.add_argument("--out", default="digests", help="folder for previews (default: digests)")
    digest.add_argument("--today", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")
    digest.set_defaults(handler=_cmd_digest)

    daily = sub.add_parser("daily", help="run the whole daily pipeline (used by GitHub Actions)")
    daily.add_argument("--out", default="site", help="output folder for the demo (default: site)")
    daily.add_argument("--today", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")
    daily.set_defaults(handler=_cmd_daily)

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
