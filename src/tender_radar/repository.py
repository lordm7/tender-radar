"""Read/write helpers that convert between database rows and Pydantic models.

The rest of the app never touches SQLAlchemy rows directly; it only sees the
models from models.py. That keeps the database swappable and the code simple.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tender_radar.db import BookletPagesRow, BriefRow, MatchRow, ProfileRow, QuestionRow, TenderRow, _now
from tender_radar.models import BookletAnswer, BookletBrief, CompanyProfile, MatchResult, Tender

_TENDER_FIELDS = list(Tender.model_fields)


@dataclass
class UpsertStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0


def tender_content_hash(t: Tender) -> str:
    """Fingerprint of a tender's content; it changes when any field changes."""
    return hashlib.sha256(t.model_dump_json().encode("utf-8")).hexdigest()[:16]


def _tender_from_row(row: TenderRow) -> Tender:
    return Tender.model_validate({f: getattr(row, f) for f in _TENDER_FIELDS})


def upsert_tenders(session: Session, tenders: list[Tender]) -> UpsertStats:
    """Insert new tenders and update changed ones, keyed by reference number.

    When a tender's content changes, its old AI verdicts are deleted so the
    next matching run scores the new version.
    """
    stats = UpsertStats()
    for t in tenders:
        new_hash = tender_content_hash(t)
        row = session.get(TenderRow, t.reference)
        if row is None:
            session.add(TenderRow(**t.model_dump(), content_hash=new_hash))
            stats.inserted += 1
        elif row.content_hash == new_hash:
            stats.unchanged += 1
        else:
            for f in _TENDER_FIELDS:
                setattr(row, f, getattr(t, f))
            row.content_hash = new_hash
            row.updated_at = _now()
            session.execute(delete(MatchRow).where(MatchRow.tender_reference == t.reference))
            stats.updated += 1
    session.flush()
    return stats


def list_tenders(session: Session) -> list[Tender]:
    rows = session.scalars(select(TenderRow).order_by(TenderRow.reference))
    return [_tender_from_row(r) for r in rows]


def get_tender(session: Session, ref: str) -> Tender | None:
    row = session.get(TenderRow, ref)
    return _tender_from_row(row) if row else None


def get_tender_hash(session: Session, ref: str) -> str | None:
    row = session.get(TenderRow, ref)
    return row.content_hash if row else None


def save_profile(session: Session, p: CompanyProfile) -> None:
    row = session.get(ProfileRow, p.id)
    if row is None:
        session.add(ProfileRow(id=p.id, json=p.model_dump_json()))
    else:
        row.json = p.model_dump_json()
    session.flush()


def get_profile(session: Session, id: str) -> CompanyProfile | None:
    row = session.get(ProfileRow, id)
    return CompanyProfile.model_validate_json(row.json) if row else None


def list_profiles(session: Session) -> list[CompanyProfile]:
    """Every company profile, ordered by id (stable order for pages and the export)."""
    rows = session.scalars(select(ProfileRow).order_by(ProfileRow.id))
    return [CompanyProfile.model_validate_json(row.json) for row in rows]


def first_profile(session: Session) -> CompanyProfile | None:
    row = session.scalars(select(ProfileRow).order_by(ProfileRow.id)).first()
    return CompanyProfile.model_validate_json(row.json) if row else None


def _match_from_row(row: MatchRow) -> MatchResult:
    return MatchResult(
        tender_reference=row.tender_reference, profile_id=row.profile_id,
        profile_version=row.profile_version, status=row.status, score=row.score,
        reasons_en=list(row.reasons_en or []), reasons_ar=list(row.reasons_ar or []),
    )


def get_match(session: Session, ref: str, profile_id: str) -> MatchResult | None:
    row = session.get(MatchRow, (ref, profile_id))
    return _match_from_row(row) if row else None


def get_match_hash(session: Session, ref: str, profile_id: str) -> str | None:
    row = session.get(MatchRow, (ref, profile_id))
    return row.content_hash if row else None


def save_match(session: Session, m: MatchResult, content_hash: str) -> None:
    """Store (or replace) the verdict for one tender and profile."""
    row = session.get(MatchRow, (m.tender_reference, m.profile_id))
    if row is None:
        row = MatchRow(tender_reference=m.tender_reference, profile_id=m.profile_id)
        session.add(row)
    row.profile_version = m.profile_version
    row.content_hash = content_hash
    row.status = m.status
    row.score = m.score
    row.reasons_en = list(m.reasons_en)
    row.reasons_ar = list(m.reasons_ar)
    row.scored_at = _now()
    session.flush()


def list_matches(session: Session, profile_id: str) -> list[MatchResult]:
    rows = session.scalars(select(MatchRow).where(MatchRow.profile_id == profile_id))
    return [_match_from_row(r) for r in rows]


def save_brief(session: Session, filename: str, brief: BookletBrief, pages: list[str] | None = None) -> int:
    """Store a brief; with `pages`, also keep the booklet text for later questions."""
    row = BriefRow(filename=filename, json=brief.model_dump_json())
    session.add(row)
    session.flush()
    if pages is not None:
        session.add(BookletPagesRow(brief_id=row.id, pages_json=json.dumps(pages, ensure_ascii=False)))
    return row.id


def get_pages(session: Session, brief_id: int) -> list[str] | None:
    row = session.get(BookletPagesRow, brief_id)
    return json.loads(row.pages_json) if row else None


def save_answer(session: Session, brief_id: int, question: str, answer: BookletAnswer) -> None:
    session.add(QuestionRow(brief_id=brief_id, question=question, json=answer.model_dump_json()))


def list_answers(session: Session, brief_id: int) -> list[tuple[str, BookletAnswer]]:
    """Questions asked about a brief and their answers, oldest first."""
    rows = session.scalars(select(QuestionRow).where(QuestionRow.brief_id == brief_id).order_by(QuestionRow.id))
    return [(r.question, BookletAnswer.model_validate_json(r.json)) for r in rows]


def latest_brief_id(session: Session, filename: str) -> int | None:
    """Id of the newest brief made from this file name."""
    query = select(BriefRow.id).where(BriefRow.filename == filename).order_by(BriefRow.id.desc())
    return session.scalars(query).first()


def get_brief(session: Session, id: int) -> BookletBrief | None:
    row = session.get(BriefRow, id)
    return BookletBrief.model_validate_json(row.json) if row else None


def latest_brief(session: Session, filename: str | None = None) -> tuple[str, BookletBrief] | None:
    """Newest brief overall, or newest for that filename."""
    query = select(BriefRow).order_by(BriefRow.id.desc())
    if filename is not None:
        query = query.where(BriefRow.filename == filename)
    row = session.scalars(query).first()
    return (row.filename, BookletBrief.model_validate_json(row.json)) if row else None


def latest_brief_filename(session: Session, id: int) -> str | None:
    """The original file name of a stored brief."""
    row = session.get(BriefRow, id)
    return row.filename if row else None
