"""Tests for Phase 3 (Track C): db.models (all 7 tables), db.init (init +
seeding), and db.repositories (CRUD). Uses an in-memory SQLite database."""

from __future__ import annotations

import json

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from core.profile_schema import UserProfile
from db.init import (_parse_iso_date, count_opportunities, create_engine_and_base,
                     init_db, resolve_db_url, seed_from_json)
from db.models import (ApiKey, Application, Base, Bookmark, DigestPreference,
                       Match, Opportunity, Supervisor, User, UserProfileRow)
from db.repositories import (ApiKeyRepo, ApiKeyUsageRepo, MatchRepo,
                             OpportunityRepo, ProfileRepo)

TABLES = {"user_profiles", "opportunities", "supervisors", "matches",
          "applications", "bookmarks", "digest_preferences", "users",
          "match_feedback", "invites", "api_keys", "api_key_usage"}


def _engine():
    eng = create_engine("sqlite://", future=True)
    Base.metadata.create_all(eng)
    return eng


def _session():
    return Session(_engine())


def _json_records():
    return [
        {"title": "PhD in radio astronomy", "institution": "MPIfR",
         "country": "Germany", "deadline": "2026-09-30",
         "posted_date": "2026-06-01", "effective_date": "2026-09-30",
         "age_days": 30, "freshness": "deadline", "url": "https://ex.org/j/1",
         "source": "euraxess", "relevance_score": 8.2,
         "matched_anchors": ["radio astronomy"],
         "matched_keywords": ["radio astronomy", "ISM"],
         "short_description": "Doctoral project on radio astronomy.",
         "position_type": "phd", "is_new": True},
        {"title": "PhD in cosmology", "institution": "Leiden",
         "country": "Netherlands", "deadline": "2026-08-15",
         "url": "https://ex.org/j/2", "source": "findaphd",
         "relevance_score": 7.5, "matched_keywords": [],
         "short_description": "Observational cosmology.",
         "position_type": "phd", "is_new": False},
    ]


def _profile():
    return UserProfile(
        domain="astronomy",
        subfield="interstellar medium",
        methods=["radio interferometry"],
        tools=["LOFAR", "Python"],
        skills=["dust polarization"],
        experience_level="phd_student",
        target_roles=["postdoc"],
        countries_preferred=["Germany"],
        confidence=0.9,
        raw_text="Some CV text.",
    ).model_dump()


# ---------------------------------------------------------------------------
# C1 — models
# ---------------------------------------------------------------------------
def test_all_seven_tables_created():
    from sqlalchemy import inspect
    eng = _engine()
    names = set(inspect(eng).get_table_names())
    assert TABLES <= names


def test_userprofile_row_roundtrip():
    s = _session()
    row = UserProfileRow.from_profile(_profile())
    s.add(row)
    s.commit()
    loaded = s.get(UserProfileRow, row.id)
    back = loaded.to_profile()          # plain dict now
    assert back["domain"] == "astronomy"
    assert back["tools"] == ["LOFAR", "Python"]
    assert back["raw_text"] == "Some CV text."


# ---------------------------------------------------------------------------
# C2 — init + seed
# ---------------------------------------------------------------------------
def test_seed_from_json_matches_count(tmp_path):
    eng = create_engine("sqlite://", future=True)
    Base.metadata.create_all(eng)
    s = Session(eng)
    p = tmp_path / "phd_positions.json"
    p.write_text(json.dumps(_json_records()))
    n = seed_from_json(s, str(p))
    assert n == 2
    assert count_opportunities(s) == 2
    # idempotent: seeding again does not duplicate
    seed_from_json(s, str(p))
    assert count_opportunities(s) == 2


def test_seed_from_json_missing_file(tmp_path):
    s = _session()
    assert seed_from_json(s, str(tmp_path / "nope.json")) == 0


def test_parse_iso_date_variants():
    assert _parse_iso_date("2026-09-30") is not None
    assert _parse_iso_date("2026-09-30T23:59:59") is not None
    assert _parse_iso_date(None) is None
    assert _parse_iso_date("not-a-date") is None


# ---------------------------------------------------------------------------
# Sprint 06 — A1: PostgreSQL support
# ---------------------------------------------------------------------------
def test_resolve_db_url_default_and_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert resolve_db_url() == "sqlite:///phd_data.db"
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/cik")
    assert resolve_db_url() == "postgresql://u:p@localhost/cik"


def test_postgres_engine_uses_queue_pool(monkeypatch):
    monkeypatch.setenv("DATABASE_URL",
                       "postgresql://u:p@localhost:5432/cik")
    eng = create_engine_and_base(resolve_db_url())
    assert eng.pool.__class__.__name__ == "QueuePool"
    assert eng.pool.size() == 5
    assert eng.pool._max_overflow == 10
    assert eng.pool.timeout() == 30
    assert eng.pool._recycle == 1800


def test_sqlite_engine_has_no_queue_pool():
    eng = create_engine_and_base("sqlite://")
    assert eng.pool.__class__.__name__ != "QueuePool"


# ---------------------------------------------------------------------------
# Sprint 06 — A2: Alembic migrations
# ---------------------------------------------------------------------------
def test_alembic_upgrade_creates_schema_and_downgrade_rolls_back(tmp_path,
                                                                 monkeypatch):
    """Alembic must be able to build the schema from scratch and roll it back
    cleanly, on a fresh database, using the same migration chain the deployed
    app will use."""
    db_file = tmp_path / "migrate_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    # Alembic's env.py calls logging.config.fileConfig on startup, which would
    # clobber pytest's caplog root logger for subsequent tests — no-op it.
    monkeypatch.setattr("logging.config.fileConfig", lambda *a, **k: None)

    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")

    command.upgrade(cfg, "head")
    from sqlalchemy import inspect
    eng = create_engine(f"sqlite:///{db_file}", future=True)
    names = set(inspect(eng).get_table_names())
    assert TABLES <= names

    command.downgrade(cfg, "base")
    eng2 = create_engine(f"sqlite:///{db_file}", future=True)
    assert "users" not in inspect(eng2).get_table_names()


# ---------------------------------------------------------------------------
# C3 — repositories
# ---------------------------------------------------------------------------
def test_opportunity_repo_upsert_and_search():
    s = _session()
    repo = OpportunityRepo(s)
    opp = Opportunity(source="euraxess", source_raw="https://ex.org/j/1",
                      title="PhD in radio astronomy", country="Germany",
                      position_type="phd", url="https://ex.org/j/1")
    repo.upsert(opp)
    s.commit()
    assert repo.get_by_url("https://ex.org/j/1") is not None
    assert len(repo.search(country="Germany")) == 1
    assert len(repo.search(text="radio")) == 1
    # upsert same source+raw -> no duplicate
    opp2 = Opportunity(source="euraxess", source_raw="https://ex.org/j/1",
                       title="PhD in radio astronomy (updated)",
                       country="Germany", url="https://ex.org/j/1")
    repo.upsert(opp2)
    s.commit()
    assert len(s.scalars(select(Opportunity)).all()) == 1


def test_profile_repo_crud_and_active_singleton():
    s = _session()
    repo = ProfileRepo(s)
    p1 = repo.create(_profile())
    s.commit()
    assert repo.get_by_id(p1.id).domain == "astronomy"
    assert repo.get_active().id == p1.id

    # update keeps id; deactivating clears active
    repo.update(p1.id, subfield="cosmic magnetism")
    s.commit()
    assert repo.get_by_id(p1.id).subfield == "cosmic magnetism"
    repo.deactivate_all()
    s.commit()
    assert repo.get_active() is None


def test_match_repo_upsert_and_get_by_profile():
    s = _session()
    profile = ProfileRepo(s).create(_profile())
    opp = Opportunity(source="a", source_raw="u1", title="T", country="DE")
    s.add(opp)
    s.commit()
    repo = MatchRepo(s)
    m1 = repo.upsert(profile.id, "opportunity", opportunity_id=opp.id,
                     scores={"overall_score": 0.87, "topic_score": 0.9},
                     explanation="topical fit")
    s.commit()
    assert m1.overall_score == 0.87
    # upserting again updates in place
    repo.upsert(profile.id, "opportunity", opportunity_id=opp.id,
                scores={"overall_score": 0.91})
    s.commit()
    got = repo.get_by_profile(profile.id)
    assert len(got) == 1
    assert got[0].overall_score == 0.91


# ---------------------------------------------------------------------------
# Sprint 08 — A1: ApiKey + ApiKeyUsage models/repos
# ---------------------------------------------------------------------------
def _user(s):
    user = User(email="dev@example.com", hashed_password="x")
    s.add(user)
    s.flush()
    return user


def test_api_key_repo_roundtrip_and_scopes_json():
    s = _session()
    user = _user(s)
    repo = ApiKeyRepo(s)
    row = repo.create(user_id=user.id, name="CI bot",
                      key_hash="a" * 64, key_prefix="cik_1234",
                      scopes=["read:matches", "write:bookmarks"],
                      quota_limit=1000, rate_limit=30)
    s.commit()
    loaded = repo.get_by_hash("a" * 64)
    assert loaded is not None
    assert loaded.key_prefix == "cik_1234"
    assert loaded.name == "CI bot"
    assert loaded.quota_limit == 1000
    assert loaded.rate_limit == 30
    assert json.loads(loaded.scopes) == ["read:matches", "write:bookmarks"]
    assert loaded.revoked_at is None
    # user scoping
    assert [k.id for k in repo.list_for_user(user.id)] == [row.id]
    assert repo.get_by_id(row.id).id == row.id


def test_api_key_repo_revoke_and_limits_override():
    s = _session()
    user = _user(s)
    repo = ApiKeyRepo(s)
    row = repo.create(user_id=user.id, name="t", key_hash="b" * 64,
                      key_prefix="cik_9999")
    s.commit()
    repo.set_limits(row, quota_limit=None, rate_limit=10)
    s.commit()
    assert row.quota_limit is None
    assert row.rate_limit == 10
    repo.revoke(row)
    s.commit()
    assert row.revoked_at is not None


def test_api_key_usage_repo_accumulates():
    s = _session()
    user = _user(s)
    key = ApiKeyRepo(s).create(user_id=user.id, name="t", key_hash="c" * 64,
                               key_prefix="cik_0001")
    s.commit()
    repo = ApiKeyUsageRepo(s)
    repo.upsert_usage(key.id, "2026-08-08", 5, rate_limited=1)
    repo.upsert_usage(key.id, "2026-08-08", 3)
    repo.upsert_usage(key.id, "2026-08-07", 2)
    s.commit()
    row = repo.get_usage(key.id, "2026-08-08")
    assert row.requests == 8
    assert row.rate_limited == 1
    days = [u.usage_date for u in repo.list_usage(key.id, limit=30)]
    assert days == ["2026-08-08", "2026-08-07"]
