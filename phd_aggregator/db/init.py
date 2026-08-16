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


def reconcile_columns(engine: Engine) -> list[str]:
    """Add columns the models declare but an existing table is missing.

    ``create_all`` creates missing TABLES; it never touches a table that
    already exists. So a model that gains a column leaves every pre-existing
    database one column short, and every write touching it fails with
    ``no such column``.

    That is not hypothetical: ``supervisors.fit_explanation`` was added to the
    model (and to an Alembic revision) but never reached databases created
    before it. The supervisor search then found real candidates, failed to
    upsert every single one, and still reported "completed, 0 records" — the
    user's "supervisor search returns nothing".

    The desktop app never runs Alembic (the shell just launches the sidecar),
    so this reconciliation is what keeps a long-lived local SQLite file usable
    across upgrades. Only NULLable columns can be added this way; anything else
    needs a real migration, and is reported rather than guessed at.

    Returns the list of ``table.column`` names added.
    """
    from sqlalchemy import inspect, text

    added: list[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all already made it, in full
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in have:
                continue
            if not column.nullable or column.primary_key:
                log.error("%s.%s is missing from the database and cannot be "
                          "added automatically (it is NOT NULL) — run the "
                          "Alembic migrations", table.name, column.name)
                continue
            ddl = column.type.compile(engine.dialect)
            with engine.begin() as conn:
                conn.execute(text(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}'))
            added.append(f"{table.name}.{column.name}")
    if added:
        log.warning("database schema was behind the models — added %s",
                    ", ".join(added))
    return added


def migrate_bookmarks_to_saved(engine: Engine) -> int:
    """Carry old ``bookmarks`` rows over to ``saved_items``.

    Bookmarks were keyed on ``opportunities.id`` and hung off ``profile_id``.
    Saved items are keyed on the record's own identity and hang off the user,
    so nothing survives the move automatically — the rows have to be rewritten.

    Idempotent (skips keys already saved) and best-effort: a bookmark whose
    opportunity has since been deleted is dropped, because there is nothing
    left to snapshot. Runs at startup because the desktop app never runs
    Alembic. Returns how many were carried over.
    """
    import json as _json

    from sqlalchemy import inspect as _inspect
    from sqlalchemy.orm import Session as _Session

    names = set(_inspect(engine).get_table_names())
    if not {"bookmarks", "saved_items", "user_profiles"} <= names:
        return 0

    from api.serializers import opportunity_out
    from core.saved_keys import key_for
    from db.models import Bookmark, Opportunity, SavedItem, UserProfileRow

    moved = 0
    with _Session(engine) as session:
        existing = {(s.user_id, s.kind, s.stable_key)
                    for s in session.scalars(select(SavedItem))}
        for bm in session.scalars(select(Bookmark)):
            prof = session.get(UserProfileRow, bm.profile_id)
            opp = session.get(Opportunity, bm.opportunity_id)
            if prof is None or opp is None:
                continue
            record = opportunity_out(opp)
            key = key_for("opportunity", record)
            ident = (prof.user_id, "opportunity", key)
            if ident in existing:
                continue
            session.add(SavedItem(user_id=prof.user_id, kind="opportunity",
                                  stable_key=key,
                                  snapshot=_json.dumps(record),
                                  status="interested",
                                  created_at=bm.created_at))
            existing.add(ident)
            moved += 1
        if moved:
            session.commit()
    if moved:
        log.info("migrated %d bookmark(s) to saved_items", moved)
    return moved


def init_db(db_url: str = DEFAULT_DB_URL) -> Engine:
    """Create engine + all tables, then bring existing tables up to date."""
    engine = create_engine_and_base(db_url)
    Base.metadata.create_all(engine)
    reconcile_columns(engine)
    try:
        migrate_bookmarks_to_saved(engine)
    except Exception:  # never let a data migration stop the app from starting
        log.exception("bookmark -> saved_items migration failed; skipping")
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
        # Which field profile this record was crawled and scored under. Without
        # it the table cannot tell an astronomy row from a chemistry one, so a
        # chemistry search still shows astronomy rows left over from an earlier
        # run — even once the crawl itself is field-scoped.
        "field": r.get("field"),
        "subfield": r.get("subfield"),
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

    Returns the number of records actually WRITTEN, not the number read: a
    record with no title is skipped, and a count that includes it would report
    rows that are not in the table — the kind of small lie this funnel exists
    to eliminate.
    """
    path = Path(json_path)
    if not path.exists():
        log.warning("seed source %s not found — nothing seeded", path)
        return 0
    with open(path, "r", encoding="utf-8") as fh:
        records = json.load(fh)
    if not isinstance(records, list):
        records = [records]
    written = 0
    for r in records:
        if isinstance(r, dict) and r.get("title"):
            _upsert_opportunity(session, r)
            written += 1
    session.commit()
    if written != len(records):
        log.warning("seeded %d of %d record(s) from %s — %d had no title",
                    written, len(records), path, len(records) - written)
    else:
        log.info("seeded %d opportunity record(s) from %s", written, path)
    return written


def count_opportunities(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Opportunity)) or 0
