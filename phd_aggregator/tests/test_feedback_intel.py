"""tests.test_feedback_intel — Sprint 09, Track B2 (match-feedback intel).

Covers the overall summary, the score-bracket breakdown (low-scoring matches
come out as unhelpful), the resource/source breakdown, and comment keyword
focus, all over seeded in-memory data.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.feedback_intel import (comment_focus, feedback_intel, score_brackets,
                                 source_breakdown, summary)
from db.models import Base, Match, MatchFeedback, Opportunity, UserProfileRow


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed(session, comments: bool = False):
    opps = [
        Opportunity(source="euraxess", source_raw="eu/1", title="Radio PhD",
                    institution="MPIfR", country="Germany",
                    short_description="Interferometry"),
        Opportunity(source="findaphd", source_raw="fp/2", title="Exo geophys",
                    institution="KU Leuven", country="Belgium",
                    short_description="Exoplanets"),
    ]
    session.add_all(opps)
    session.flush()

    profile = UserProfileRow(user_id=None)
    session.add(profile)
    session.flush()

    sentinel = "mismatch — needed funding details" if comments else ""

    def make(opp, overall, helpful):
        m = Match(profile_id=profile.id, target_type="opportunity",
                  opportunity_id=opp.id, overall_score=overall)
        session.add(m)
        session.flush()
        if helpful is not None:
            session.add(MatchFeedback(match_id=m.id, helpful=helpful,
                                      comment=sentinel))
    make(opps[0], 90.0, True)
    make(opps[0], 75.0, True)
    make(opps[0], 15.0, False)
    make(opps[1], 10.0, False)
    make(opps[1], 30.0, False)
    session.flush()
    return opps[0]


def test_empty_intel(db_session):
    data = feedback_intel(db_session)
    assert data["summary"]["total"] == 0
    assert data["brackets"] == []
    assert data["sources"] == []
    assert data["comments"]["keywords"] == []


def test_summary_rate(db_session):
    seed(db_session)
    s = summary(db_session)
    assert s["total"] == 5
    assert s["helpful"] == 2
    assert s["rate"] == 0.4


def test_brackets_low_band_heavy_unhelpful(db_session):
    seed(db_session)
    brackets = {b["key"]: b for b in score_brackets(db_session)}
    assert brackets["0-20"]["total"] == 2
    assert brackets["0-20"]["helpful"] == 0
    assert brackets["0-20"]["rate"] == 0.0
    assert brackets["80-100"]["helpful"] == 1
    assert brackets["60-80"]["rate"] == 1.0


def test_source_breakdown_groups(db_session):
    seed(db_session)
    rows = source_breakdown(db_session)
    by = {r["key"]: r for r in rows}
    assert by["euraxess"]["total"] == 3
    assert by["euraxess"]["rate"] == pytest.approx(0.667, abs=0.01)
    assert by["findaphd"]["total"] == 2
    assert by["findaphd"]["rate"] == 0.0


def test_comment_focus_keywords(db_session):
    seed(db_session, comments=True)
    out = comment_focus(db_session)
    assert out["samples"]
    assert all(isinstance(s["comment"], str) for s in out["samples"])
    kw = {k["keyword"]: k["count"] for k in out["keywords"]}
    assert kw.get("funding", 0) >= 0
    assert any("needed funding" in s["comment"] for s in out["samples"])