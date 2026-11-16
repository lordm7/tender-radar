"""Database tables and sessions (SQLAlchemy 2).

Tables: tenders, profiles, matches (the AI verdicts), briefs (booklet
summaries), booklet_pages (the booklet text, for "Ask the booklet") and
booklet_questions (questions asked and the AI's cited answers). SQLite by default; the same code runs on PostgreSQL by changing
TR_DATABASE_URL.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Iterator

from sqlalchemy import JSON, Date, DateTime, Engine, Float, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TenderRow(Base):
    __tablename__ = "tenders"
    reference: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    agency: Mapped[str] = mapped_column(String)
    tender_type: Mapped[str] = mapped_column(String)
    activity: Mapped[str] = mapped_column(String)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    published_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    inquiry_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline_time: Mapped[str | None] = mapped_column(String, nullable=True)
    booklet_price_sar: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    estimated_value_sar: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String, default="seed")
    title_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    agency_en: Mapped[str | None] = mapped_column(String, nullable=True)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ProfileRow(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    json: Mapped[str] = mapped_column(Text)


class MatchRow(Base):
    __tablename__ = "matches"
    tender_reference: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_version: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasons_en: Mapped[list] = mapped_column(JSON, default=list)
    reasons_ar: Mapped[list] = mapped_column(JSON, default=list)
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class BriefRow(Base):
    __tablename__ = "briefs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String)
    json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class BookletPagesRow(Base):
    """The page texts of a brief's booklet, kept so questions can be asked later."""

    __tablename__ = "booklet_pages"
    brief_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pages_json: Mapped[str] = mapped_column(Text)


class QuestionRow(Base):
    __tablename__ = "booklet_questions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brief_id: Mapped[int] = mapped_column(Integer, index=True)
    question: Mapped[str] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(String, nullable=True)  # the page language it was asked in
    json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def make_engine(url: str) -> Engine:
    """Create the engine. An in-memory SQLite DB ("sqlite://") is shared across sessions."""
    if url in ("sqlite://", "sqlite:///:memory:"):
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url)


def init_db(engine: Engine) -> None:
    """Create any missing tables, and add new nullable columns to old tables.

    There are no migrations; this small top-up lets a database made by an
    older version keep working after a release that only adds optional columns.
    """
    Base.metadata.create_all(engine)
    existing = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in existing.get_columns(table.name)}
            for column in table.columns:
                if column.name not in have and column.nullable:
                    kind = column.type.compile(engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {kind}'))


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Open a session, commit if the block succeeds, roll back if it fails."""
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
