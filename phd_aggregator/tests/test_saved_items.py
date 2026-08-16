"""tests.test_saved_items — saving opportunities and supervisors.

The behaviours worth pinning are the ones bookmarks got wrong: an entry must
survive the re-crawl that changes its row id, must still read correctly after
the source row is gone, and must not be lost when the user rebuilds a profile.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import get_current_user, get_db
from db.models import Base, Opportunity, SavedItem, Supervisor, User
from db.repositories import UserRepo


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture()
def user(db_session) -> User:
    return UserRepo(db_session).create("saved@example.com", "x")


@pytest.fixture()
def client(db_session, user):
    def db_override():
        yield db_session

    def user_override():
        return user

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = user_override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def make_opp(session, **kw) -> Opportunity:
    row = Opportunity(source=kw.get("source", "euraxess"),
                      source_raw=kw.get("source_raw", "raw-1"),
                      title=kw.get("title", "PhD in radio astronomy"),
                      institution=kw.get("institution", "MPIfR"),
                      country=kw.get("country", "Germany"),
                      url=kw.get("url", "https://example.org/p/1"))
    session.add(row)
    session.commit()
    return row


def make_sup(session, **kw) -> Supervisor:
    row = Supervisor(source="ads", name=kw.get("name", "Ada Lovelace"),
                     institution=kw.get("institution", "MPIfR"),
                     country="Germany",
                     profile_url=kw.get("profile_url",
                                        "https://example.edu/people/ada"))
    session.add(row)
    session.commit()
    return row


class TestSaving:
    def test_saves_an_opportunity(self, client, db_session):
        opp = make_opp(db_session)
        r = client.post("/api/saved",
                        json={"kind": "opportunity", "record_id": opp.id})
        assert r.status_code == 201, r.text
        assert r.json()["record"]["title"] == "PhD in radio astronomy"

    def test_saves_a_supervisor(self, client, db_session):
        sup = make_sup(db_session)
        r = client.post("/api/saved",
                        json={"kind": "supervisor", "record_id": sup.id})
        assert r.status_code == 201, r.text
        assert r.json()["record"]["name"] == "Ada Lovelace"

    def test_the_two_kinds_are_listed_separately(self, client, db_session):
        client.post("/api/saved", json={"kind": "opportunity",
                                        "record_id": make_opp(db_session).id})
        client.post("/api/saved", json={"kind": "supervisor",
                                        "record_id": make_sup(db_session).id})
        opps = client.get("/api/saved", params={"kind": "opportunity"}).json()
        sups = client.get("/api/saved", params={"kind": "supervisor"}).json()
        assert opps["total"] == 1 and sups["total"] == 1
        assert opps["items"][0]["kind"] == "opportunity"

    def test_saving_twice_is_not_an_error(self, client, db_session):
        """A toggle whose state the user cannot see must not punish them."""
        opp = make_opp(db_session)
        first = client.post("/api/saved",
                            json={"kind": "opportunity", "record_id": opp.id})
        second = client.post("/api/saved",
                             json={"kind": "opportunity", "record_id": opp.id})
        assert second.status_code in (200, 201)
        assert second.json()["id"] == first.json()["id"]
        assert client.get("/api/saved",
                          params={"kind": "opportunity"}).json()["total"] == 1

    def test_unknown_kind_is_refused(self, client):
        assert client.post("/api/saved",
                           json={"kind": "banana", "record_id": 1}).status_code == 422

    def test_saving_something_that_does_not_exist_is_404(self, client):
        r = client.post("/api/saved",
                        json={"kind": "opportunity", "record_id": 9999})
        assert r.status_code == 404


class TestSurvival:
    def test_survives_a_recrawl_that_changes_the_row_id(self, client, db_session):
        """The bug the old bookmarks table could not avoid."""
        opp = make_opp(db_session, url="https://example.org/p/1")
        client.post("/api/saved", json={"kind": "opportunity",
                                        "record_id": opp.id})
        # Re-crawl: the row is replaced, same posting, new id and a URL that
        # differs only in the ways normalisation ignores.
        db_session.delete(opp)
        db_session.commit()
        make_opp(db_session, source_raw="raw-2",
                 url="http://www.example.org/p/1/")

        body = client.get("/api/saved", params={"kind": "opportunity"}).json()
        assert body["total"] == 1
        assert body["items"][0]["still_listed"] is True, \
            "the same posting re-crawled must still count as listed"

    def test_still_readable_after_the_source_disappears(self, client, db_session):
        opp = make_opp(db_session)
        client.post("/api/saved", json={"kind": "opportunity",
                                        "record_id": opp.id})
        db_session.delete(opp)
        db_session.commit()

        item = client.get("/api/saved",
                          params={"kind": "opportunity"}).json()["items"][0]
        assert item["still_listed"] is False, "must be marked no longer listed"
        # ...and still shows what was saved, rather than an empty husk.
        assert item["record"]["title"] == "PhD in radio astronomy"
        assert item["record"]["institution"] == "MPIfR"

    def test_survives_a_profile_rebuild(self, client, db_session, user):
        """Saved items hang off the user, not the active profile."""
        opp = make_opp(db_session)
        client.post("/api/saved", json={"kind": "opportunity",
                                        "record_id": opp.id})
        saved = db_session.scalars(select(SavedItem)).all()
        assert saved and saved[0].user_id == user.id
        assert client.get("/api/saved",
                          params={"kind": "opportunity"}).json()["total"] == 1



class TestNotesAndStatus:
    def test_defaults_to_interested(self, client, db_session):
        opp = make_opp(db_session)
        body = client.post("/api/saved", json={"kind": "opportunity",
                                               "record_id": opp.id}).json()
        assert body["status"] == "interested"

    def test_note_and_status_can_be_set(self, client, db_session):
        opp = make_opp(db_session)
        item = client.post("/api/saved", json={"kind": "opportunity",
                                               "record_id": opp.id}).json()
        r = client.patch(f"/api/saved/{item['id']}",
                         json={"note": "email the PI first", "status": "applied"})
        assert r.status_code == 200, r.text
        assert r.json()["note"] == "email the PI first"
        assert r.json()["status"] == "applied"

    def test_an_invented_status_is_refused(self, client, db_session):
        opp = make_opp(db_session)
        item = client.post("/api/saved", json={"kind": "opportunity",
                                               "record_id": opp.id}).json()
        r = client.patch(f"/api/saved/{item['id']}", json={"status": "maybe"})
        assert r.status_code == 422


class TestRemoval:
    def test_remove(self, client, db_session):
        opp = make_opp(db_session)
        item = client.post("/api/saved", json={"kind": "opportunity",
                                               "record_id": opp.id}).json()
        assert client.delete(f"/api/saved/{item['id']}").status_code == 200
        assert client.get("/api/saved",
                          params={"kind": "opportunity"}).json()["total"] == 0

    def test_cannot_touch_another_users_item(self, client, db_session, user):
        other = UserRepo(db_session).create("other@example.com", "x")
        theirs = SavedItem(user_id=other.id, kind="opportunity",
                           stable_key="url:example.org/x",
                           snapshot=json.dumps({"title": "theirs"}))
        db_session.add(theirs)
        db_session.commit()
        assert client.delete(f"/api/saved/{theirs.id}").status_code == 404
        assert client.patch(f"/api/saved/{theirs.id}",
                            json={"note": "x"}).status_code == 404


class TestIdsEndpoint:
    def test_maps_live_record_ids_to_saved_ids(self, client, db_session):
        """What a list of cards needs to render its toggles in one request."""
        opp = make_opp(db_session)
        item = client.post("/api/saved", json={"kind": "opportunity",
                                               "record_id": opp.id}).json()
        ids = client.get("/api/saved/ids",
                         params={"kind": "opportunity"}).json()["ids"]
        assert ids == {str(opp.id): item["id"]}

    def test_tracks_the_new_row_id_after_a_recrawl(self, client, db_session):
        """The saved item follows the posting, not the id it was saved under."""
        opp = make_opp(db_session, url="https://example.org/p/1")
        item = client.post("/api/saved", json={"kind": "opportunity",
                                               "record_id": opp.id}).json()
        db_session.delete(opp)
        db_session.commit()
        fresh = make_opp(db_session, source_raw="raw-2",
                         url="http://www.example.org/p/1/")

        ids = client.get("/api/saved/ids",
                         params={"kind": "opportunity"}).json()["ids"]
        assert ids == {str(fresh.id): item["id"]}

    def test_a_delisted_item_is_absent(self, client, db_session):
        opp = make_opp(db_session)
        client.post("/api/saved", json={"kind": "opportunity",
                                        "record_id": opp.id})
        db_session.delete(opp)
        db_session.commit()
        assert client.get("/api/saved/ids",
                          params={"kind": "opportunity"}).json()["ids"] == {}


class TestMigrationFromBookmarks:
    """Old bookmarks must not be silently dropped when the table changes."""

    def _seed_old_bookmark(self, engine):
        from db.models import Bookmark, UserProfileRow
        with Session(engine) as s:
            user = UserRepo(s).create("legacy@example.com", "x")
            prof = UserProfileRow(user_id=user.id, domain="astronomy",
                                  confidence=0.9, active=True)
            s.add(prof)
            opp = Opportunity(source="euraxess", source_raw="raw-legacy",
                              title="Legacy PhD", institution="MPIfR",
                              url="https://example.org/legacy")
            s.add(opp)
            s.commit()
            s.add(Bookmark(profile_id=prof.id, opportunity_id=opp.id))
            s.commit()
            return user.id

    def test_bookmarks_are_carried_over(self):
        from db.init import migrate_bookmarks_to_saved
        engine = create_engine("sqlite://",
                               connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        user_id = self._seed_old_bookmark(engine)

        assert migrate_bookmarks_to_saved(engine) == 1
        with Session(engine) as s:
            items = s.scalars(select(SavedItem)).all()
            assert len(items) == 1
            assert items[0].user_id == user_id, "re-homed onto the user"
            assert items[0].kind == "opportunity"
            # Snapshot taken, so it survives the opportunity being deleted.
            assert json.loads(items[0].snapshot)["title"] == "Legacy PhD"
        engine.dispose()

    def test_running_it_twice_does_not_duplicate(self):
        from db.init import migrate_bookmarks_to_saved
        engine = create_engine("sqlite://",
                               connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self._seed_old_bookmark(engine)

        assert migrate_bookmarks_to_saved(engine) == 1
        assert migrate_bookmarks_to_saved(engine) == 0, "must be idempotent"
        with Session(engine) as s:
            assert len(s.scalars(select(SavedItem)).all()) == 1
        engine.dispose()
