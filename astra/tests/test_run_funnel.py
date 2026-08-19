"""Run accounting: one number, and a breakdown that explains every drop (S5).

The reported bug: the dashboard said "18 open positions" while the engine
reported "63 records (astronomy)". Two numbers from two layers, neither
explaining the other.

These tests pin down:
  * the funnel accounts for every record (found - drops == kept), so the UI
    can always show WHY the number shrank;
  * the engine's count and the stored row count agree;
  * every record is stamped with the field it was crawled under, and that
    stamp survives to the database — without it, a chemistry view still shows
    astronomy rows left over from an earlier run;
  * the opportunity cache is keyed by field, so switching field cannot serve
    the previous field's list.
"""

from __future__ import annotations

import argparse
import os
import tempfile

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import cache
from core.config import build_config
from core.records import OUTPUT_FIELDS, make_record
from db.init import count_opportunities, init_db, seed_from_json
from db.models import Opportunity
from pipeline.run import run as pipeline_run


def _cfg(field, tmp):
    cfg = build_config(argparse.Namespace(field=field, no_config=True))
    cfg.output_path = os.path.join(tmp, f"positions_{field}")
    cfg.write_html = False
    cfg.state_file = os.path.join(tmp, f".seen_{field}.json")
    return cfg


def _astro_batch():
    """7 records: 3 keepers + one of each drop reason."""
    return [
        make_record(title="PhD in Radio Astronomy", url="https://x/1",
                    short_description="radio astronomy interstellar medium",
                    source="aas"),
        make_record(title="PhD in Radio Astronomy", url="https://x/1",
                    short_description="radio astronomy interstellar medium",
                    source="aas"),                       # duplicate url
        make_record(title="PhD in Cosmology", url="https://x/2",
                    short_description="cosmology dark energy",
                    source="euraxess"),
        make_record(title="PhD in Marine Biology", url="https://x/3",
                    short_description="coral reef ecology",
                    source="euraxess"),                  # off-field
        make_record(title="PhD in Exoplanets", url="https://x/4",
                    short_description="exoplanet atmospheres",
                    deadline="2020-01-01", source="aas"),  # expired
        make_record(title="Lab Technician", url="https://x/6",
                    short_description="astronomy lab technician",
                    source="eso"),                       # wrong position type
        make_record(title="PhD in Stellar Astrophysics", url="https://x/5",
                    short_description="stellar astrophysics", source="eso"),
    ]


@pytest.fixture
def tmpdir_run():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


# --- the funnel --------------------------------------------------------------

def test_funnel_accounts_for_every_record(tmpdir_run):
    """found - (every drop) == what survived. No unexplained shrinkage."""
    cfg = _cfg("astronomy", tmpdir_run)
    funnel: dict = {}
    kept = pipeline_run(cfg, injected_raw=_astro_batch(), funnel=funnel)

    assert funnel["found"] == 7
    assert funnel["after_dedupe"] == len(kept)
    assert funnel["found"] - sum(funnel["dropped"].values()) == len(kept)


def test_funnel_names_each_drop_reason(tmpdir_run):
    cfg = _cfg("astronomy", tmpdir_run)
    funnel: dict = {}
    pipeline_run(cfg, injected_raw=_astro_batch(), funnel=funnel)

    dropped = funnel["dropped"]
    assert dropped["position_type"] == 1     # the lab technician
    assert dropped["off_field"] == 1         # the marine-biology PhD
    assert dropped["expired"] == 1           # deadline in 2020
    assert dropped["duplicate"] == 1         # the repeated url
    assert set(dropped) == {"position_type", "off_field", "expired",
                            "country", "stale", "duplicate"}


def test_funnel_records_the_active_field(tmpdir_run):
    funnel: dict = {}
    pipeline_run(_cfg("chemistry", tmpdir_run), injected_raw=[], funnel=funnel)
    assert funnel["field"] == "chemistry"


def test_run_without_funnel_still_works(tmpdir_run):
    """The out-param is optional — every existing caller keeps working."""
    kept = pipeline_run(_cfg("astronomy", tmpdir_run),
                        injected_raw=_astro_batch())
    assert len(kept) == 3


# --- engine count == stored count --------------------------------------------

def test_engine_count_equals_stored_count(tmpdir_run):
    """The 18-vs-63 regression, in one assertion."""
    cfg = _cfg("astronomy", tmpdir_run)
    funnel: dict = {}
    kept = pipeline_run(cfg, injected_raw=_astro_batch(), funnel=funnel)

    engine = init_db(f"sqlite:///{tmpdir_run}/t.db")
    with Session(engine) as session:
        seed_from_json(session, cfg.json_path)
        stored = count_opportunities(session)

    assert len(kept) == stored == funnel["after_dedupe"]


def test_stored_counts_this_run_not_the_whole_table(tmpdir_run, monkeypatch):
    """"stored" is the funnel's last stage, so it must be THIS run's rows.

    The bug this pins: ``_persist_records`` reported ``count_opportunities()``,
    the size of the whole table. Against a database holding earlier runs that
    printed "0 after dedupe -> 40 stored" — the two-unrelated-numbers problem
    the funnel exists to end. Invisible to the test above because a fresh
    tmpdir database starts empty, which makes the two counts coincide.
    """
    db_url = f"sqlite:///{tmpdir_run}/t.db"
    monkeypatch.setattr("db.init.resolve_db_url", lambda *a, **k: db_url)

    # An earlier run's rows are already in the table.
    seeded_cfg = _cfg("astronomy", tmpdir_run)
    pipeline_run(seeded_cfg, injected_raw=_astro_batch())
    engine = init_db(db_url)
    with Session(engine) as session:
        seed_from_json(session, seeded_cfg.json_path)
        pre_existing = count_opportunities(session)
    assert pre_existing > 0

    # This run finds nothing that survives the filters.
    cfg = _cfg("astronomy", tmpdir_run)
    funnel: dict = {}
    pipeline_run(cfg, injected_raw=[], funnel=funnel)
    from core import tasks
    tasks._persist_records(cfg, funnel, "Germany")

    assert funnel["stored"] == funnel["after_dedupe"] == 0, \
        "stored must report what this run wrote"
    assert funnel["stored_total"] == pre_existing, \
        "the table total is still reported, under its own name"


# --- the field stamp ---------------------------------------------------------

def test_field_is_part_of_the_written_schema():
    assert "field" in OUTPUT_FIELDS and "subfield" in OUTPUT_FIELDS
    assert "field" in make_record(title="t")   # complete by construction


def test_stored_rows_carry_their_field_and_are_separable(tmpdir_run):
    """A chemistry view must not show astronomy rows from an earlier run."""
    paths = []
    for field, url, title, desc in [
        ("astronomy", "https://x/a", "PhD in Radio Astronomy",
         "radio astronomy interstellar medium"),
        ("chemistry", "https://x/c", "PhD in Organic Chemistry",
         "organic chemistry catalysis synthesis"),
    ]:
        cfg = _cfg(field, tmpdir_run)
        pipeline_run(cfg, injected_raw=[make_record(
            title=title, url=url, short_description=desc, source="euraxess")])
        paths.append(cfg.json_path)

    engine = init_db(f"sqlite:///{tmpdir_run}/t.db")
    with Session(engine) as session:
        for p in paths:
            seed_from_json(session, p)
        astro = session.scalars(select(Opportunity)
                                .where(Opportunity.field == "astronomy")).all()
        chem = session.scalars(select(Opportunity)
                               .where(Opportunity.field == "chemistry")).all()
        assert count_opportunities(session) == 2
    assert len(astro) == 1 and "Astronomy" in astro[0].title
    assert len(chem) == 1 and "Chemistry" in chem[0].title


# --- the cache ---------------------------------------------------------------

def test_opportunity_cache_is_keyed_by_field():
    assert cache.opportunity_list_key("chemistry") != \
        cache.opportunity_list_key("astronomy")
    assert cache.opportunity_list_key() == "opportunities:list"  # legacy key


def test_cached_list_does_not_bleed_between_fields():
    cache.invalidate_opportunities()
    try:
        cache.cache_opportunity_list([{"title": "astro row"}], "astronomy")
        assert cache.get_cached_opportunity_list("chemistry") is None
        assert cache.get_cached_opportunity_list("astronomy") == \
            [{"title": "astro row"}]
    finally:
        cache.invalidate_opportunities()


def test_invalidate_clears_every_field_key():
    cache.cache_opportunity_list([{"a": 1}], "astronomy")
    cache.cache_opportunity_list([{"b": 2}], "chemistry")
    cache.invalidate_opportunities()
    assert cache.get_cached_opportunity_list("astronomy") is None
    assert cache.get_cached_opportunity_list("chemistry") is None
