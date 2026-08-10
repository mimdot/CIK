"""cli — Track C command handlers (Sprint 03).

Keeps phd_aggregator.py lean: all C1-C4 logic lives here and is re-exported
through the monolith.

- C1 ``build_profile_cmd``:  LLM-extract a UserProfile from CV text and save
  it as the active profile in the DB.
- C2 ``seed_db_cmd``:        seed opportunities from the pipeline's JSON.
- C3 ``load_active_profile``: find the active profile for ``--run`` scoring.
- C4 ``show_profile_cmd``:   print the active profile from the DB.

The DB is SQLite (MVP). A file-backed URL only gets created/touched when the
file already exists, so a plain aggregation run never leaves a stray DB behind.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core.llm import LLMRouter
from core.profile import extract_profile
from core.profile_schema import UserProfile
from db.init import DEFAULT_DB_URL, count_opportunities, init_db, seed_from_json
from db.repositories import ProfileRepo

log = logging.getLogger("phd_aggregator")


def _session(db_url: str) -> Session:
    """Create an initialized SQLAlchemy session for ``db_url``."""
    engine = init_db(db_url)
    return Session(engine)


def db_available(db_url: str) -> bool:
    """True if the DB URL can be opened without a side effect.

    File-backed SQLite URLs are only considered available if the file already
    exists; in-memory/other backends are always considered available (the
    caller decides when to create them). The connection is verified with a
    trivial ``SELECT 1`` so a corrupt/unopenable store is reported as
    unavailable."""
    if db_url.startswith("sqlite:///"):
        path = db_url[len("sqlite:///"):]
        if not os.path.exists(path):
            return False
    try:
        engine = init_db(db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def load_active_profile(db_url: str = DEFAULT_DB_URL) -> Optional[UserProfile]:
    """Return the DB's active UserProfile, or None if there is none."""
    if not db_available(db_url):
        return None
    try:
        session = _session(db_url)
    except Exception as exc:
        log.debug("no usable DB at %s: %s", db_url, exc)
        return None
    with session:
        row = ProfileRepo(session).get_active()
        if row is None:
            return None
        return UserProfile(**row.to_profile())


# --- C1 ----------------------------------------------------------------------
def build_profile_cmd(raw_text: str, db_url: str = DEFAULT_DB_URL,
                      llm: Optional[LLMRouter] = None) -> int:
    """Extract a UserProfile from CV text via the LLM and store it as the
    active profile. Returns 0 on success, 1 if extraction failed."""
    llm = llm or LLMRouter()
    profile = extract_profile(raw_text, llm)
    if profile is None:
        log.error("--build-profile: could not extract a profile from the text "
                  "(install litellm and set an API key, or pass a stub LLM).")
        return 1
    session = _session(db_url)
    with session:
        repo = ProfileRepo(session)
        repo.deactivate_all()           # the new profile becomes active
        repo.create(profile.model_dump())
        session.commit()
    print("Saved active profile:")
    print(json.dumps(profile.model_dump(), indent=2, ensure_ascii=False))
    return 0


# --- C2 ----------------------------------------------------------------------
def seed_db_cmd(path: str, db_url: str = DEFAULT_DB_URL) -> int:
    """Seed opportunities from the pipeline's JSON output. Returns 0."""
    session = _session(db_url)
    with session:
        n = seed_from_json(session, path)
        total = count_opportunities(session)
    print(f"Seeded {n} record(s) from {path} "
          f"(total opportunities in DB: {total})")
    return 0


# --- C4 ----------------------------------------------------------------------
def show_profile_cmd(db_url: str = DEFAULT_DB_URL) -> int:
    """Print the active profile from the DB. Returns 0 if found, 1 if none."""
    profile = load_active_profile(db_url)
    if profile is None:
        print("No active profile in the database. Build one with:\n"
              "    python phd_aggregator.py --build-profile \"<your CV text>\"")
        return 1
    print(json.dumps(profile.model_dump(), indent=2, ensure_ascii=False))
    return 0


# --- Sprint 06, C1: admin bootstrap -------------------------------------------
def make_admin_cmd(email: str, db_url: str = DEFAULT_DB_URL) -> int:
    """Promote ``email`` to the ``admin`` role (bootstraps the first admin
    used to create invite codes). Returns 0 on success, 1 if the user is
    unknown."""
    from sqlalchemy import update
    from db.models import User

    email = (email or "").strip().lower()
    if not email:
        print("Usage: python phd_aggregator.py --make-admin <email>")
        return 1
    session = _session(db_url)
    with session:
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"User {email!r} not found. Register first, then promote.")
            return 1
        session.execute(
            update(User).where(User.id == user.id).values(role="admin"))
        session.commit()
        print(f"Promoted {user.email} (user id {user.id}) to admin.")
    return 0
