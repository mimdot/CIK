"""db.init — engine creation, table creation, and seeding from the crawler's
JSON output (migration Phase 3, Track C2).

``init_db`` creates the engine and all 7 tables; ``seed_from_json`` reads the
current ``phd_positions.json`` (the pipeline's OUTPUT_FIELDS records) and
inserts them into ``opportunities`` idempotently (upsert on source+url).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from db.models import Base, Opportunity

log = logging.getLogger("phd_aggregator")

DEFAULT_DB_URL = "sqlite:///phd_data.db"


def resolve_db_url() -> str:
    """The effective DB URL: ``DATABASE_URL`` env var or the sqlite default."""
    return os.environ.get("DATABASE_URL", "").strip() or DEFAULT_DB_URL


def _parse_iso_date(value) -> datetime | None:
    """Best-effort parse of ISO-8601 date/datetime to a naive datetime."""
    if not value:
        return None
    v = str(value).strip()
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    # Normalize timezone-aware strings to naive UTC before storing.
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _ensure_foreign_keys(dbapi_conn, _record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine_and_base(db_url: str = DEFAULT_DB_URL) -> Engine:
    """Create a SQLAlchemy engine for SQLite or PostgreSQL.

    PostgreSQL gets a bounded ``QueuePool``; SQLite keeps its default
    (SQLAlchemy uses SingletonThreadPool/NullPool there, which is correct).
    """
    kwargs: dict = {"future": True}
    if db_url.startswith(("postgresql://", "postgres://")):
        kwargs.update(poolclass=QueuePool, pool_size=5, max_overflow=10,
                      pool_timeout=30, pool_recycle=1800)
    engine = create_engine(db_url, **kwargs)
    if db_url.startswith("sqlite"):
        event.listen(engine, "connect", _ensure_foreign_keys)
    return engine


def init_db(db_url: str = DEFAULT_DB_URL) -> Engine:
    """Create engine + all tables. Returns the engine."""
    engine = create_engine_and_base(db_url)
    Base.metadata.create_all(engine)
    return engine


# --- seeding -----------------------------------------------------------------
def _opportunity_values(r: dict) -> dict:
    """Map a pipeline JSON record onto Opportunity column values (no id)."""
    def _json_list(value):
        return json.dumps(value, ensure_ascii=False) if isinstance(value, list) else None

    return {
        "source": str(r.get("source") or "unknown"),
        "source_raw": str(r.get("url") or ""),
        "title": str(r.get("title") or "(untitled)"),
        "institution": r.get("institution"),
        "country": r.get("country"),
        "url": r.get("url"),
        "deadline": _parse_iso_date(r.get("deadline")),
        "posted_date": _parse_iso_date(r.get("posted_date")),
        "effective_date": _parse_iso_date(r.get("effective_date")),
        "age_days": r.get("age_days"),
        "freshness": r.get("freshness"),
        "relevance_score": r.get("relevance_score"),
        "matched_anchors": _json_list(r.get("matched_anchors")),
        "matched_keywords": _json_list(r.get("matched_keywords")),
        "short_description": r.get("short_description"),
        "position_type": r.get("position_type"),
        "is_new": bool(r.get("is_new", True)),
    }


def _record_to_opportunity(r: dict) -> Opportunity:
    return Opportunity(**_opportunity_values(r))


def _upsert_opportunity(session: Session, r: dict) -> None:
    """Insert or update an opportunity by (source, source_raw)."""
    src = str(r.get("source") or "unknown")
    url = str(r.get("url") or "")
    existing = session.scalar(
        select(Opportunity).where(
            Opportunity.source == src, Opportunity.source_raw == url))
    if existing is None:
        session.add(_record_to_opportunity(r))
    else:
        values = _opportunity_values(r)
        for col, new_val in values.items():
            if new_val is not None:
                setattr(existing, col, new_val)


def seed_from_json(session: Session, json_path: str | Path) -> int:
    """Seed ``opportunities`` from the pipeline's JSON output (idempotent).
    Returns the number of records read from the file."""
    path = Path(json_path)
    if not path.exists():
        log.warning("seed source %s not found — nothing seeded", path)
        return 0
    with open(path, "r", encoding="utf-8") as fh:
        records = json.load(fh)
    if not isinstance(records, list):
        records = [records]
    for r in records:
        if isinstance(r, dict) and r.get("title"):
            _upsert_opportunity(session, r)
    session.commit()
    log.info("seeded %d opportunity record(s) from %s", len(records), path)
    return len(records)


def count_opportunities(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Opportunity)) or 0
