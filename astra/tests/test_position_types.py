"""Position types as data, and PhD/postdoc as separate searches (Phase 2C).

Types used to be hardcoded dicts in core.taxonomy, so PhD and postdoc could
only ever be one blended list and adding Master's or Scholarships meant editing
Python in several places. They now come from position_types.yaml.
"""

from __future__ import annotations

import argparse

import pytest

from core import position_types as pt
from core.config import build_config
from core.taxonomy import classify_position_type


def _cfg(**kw):
    return build_config(argparse.Namespace(field="astronomy", no_config=True,
                                           **kw))


# --- the registry ------------------------------------------------------------

def test_the_registry_loads_from_yaml():
    names = pt.type_names()
    assert names[:2] == ["phd", "postdoc"], "order IS classifier priority"
    assert {"masters", "scholarship", "faculty", "staff"} <= set(names)


def test_phd_and_postdoc_are_the_offered_types():
    assert [t.name for t in pt.offered_types()] == ["phd", "postdoc"]


def test_masters_and_scholarships_are_planned_not_offered():
    """Shipped and classified, but not selectable yet — 'coming soon'."""
    planned = {t.name for t in pt.coming_soon_types()}
    assert planned == {"masters", "scholarship"}
    for name in planned:
        entry = pt.get(name)
        assert entry.selectable is True     # a real future user choice
        assert entry.enabled is False       # just not switched on
        assert entry.is_offered is False


def test_faculty_and_staff_are_classified_but_never_offered():
    """They exist so senior ads are recognised and EXCLUDED, not searched."""
    for name in ("faculty", "staff"):
        assert pt.get(name).selectable is False
        assert pt.get(name).is_offered is False


def test_every_type_carries_a_label_and_help_text():
    for entry in pt.TYPES:
        assert entry.label and entry.patterns
        if entry.selectable:
            assert entry.description, f"{entry.name} needs user-facing help"


# --- classification is unchanged for the historical types --------------------

@pytest.mark.parametrize("title,description,expected", [
    ("PhD position in Radio Astronomy (m/f/d)", "", "phd"),
    ("Doctoral researcher: exoplanets", "", "phd"),
    ("Early-stage researcher", "", "phd"),
    # The classic bug: "doctoral" inside "Post Doctoral" must NOT mean PhD.
    ("Post Doctoral Research Associate", "", "postdoc"),
    ("Postdoctoral Researcher in Galaxies", "", "postdoc"),
    ("Assistant Professor of Astrophysics", "", "faculty"),
    ("Software Developer", "", "staff"),
    ("Research opportunities", "various openings", "unknown"),
])
def test_historical_classification_is_unchanged(title, description, expected):
    assert classify_position_type(title, description) == expected


def test_a_phd_mentioned_as_a_requirement_is_not_a_phd_opening():
    assert classify_position_type(
        "Researcher in cosmology",
        "The successful candidate must hold a PhD in astronomy.") != "phd"


def test_the_new_types_classify_too():
    """They are labelled correctly TODAY, which is what keeps them out of the
    PhD/postdoc buckets — enabling them is the only remaining step."""
    assert classify_position_type("MSc student position in chemistry", "") == "masters"
    assert classify_position_type("Master's thesis project", "") == "masters"
    assert classify_position_type("Call for applications: mobility grant", "") == "scholarship"
    assert classify_position_type("PhD Scholarship in Chemistry", "") == "phd", \
        "PhD wins over scholarship — it precedes it in the registry"


# --- separate searches -------------------------------------------------------

def test_a_phd_only_search_excludes_postdocs():
    cfg = _cfg(types=["phd"])
    assert cfg.wanted_types == ["phd"]
    assert "postdoc" not in cfg.wanted_types


def test_a_postdoc_only_search_excludes_phds():
    cfg = _cfg(types=["postdoc"])
    assert cfg.wanted_types == ["postdoc"]
    assert "phd" not in cfg.wanted_types


def test_both_can_still_be_hunted_together():
    assert _cfg(types=["phd", "postdoc"]).wanted_types == ["phd", "postdoc"]


def test_a_not_yet_available_type_is_reported_not_silently_empty(caplog):
    """Selecting Master's must not quietly return zero results."""
    with caplog.at_level("WARNING"):
        cfg = _cfg(types=["masters"])
    assert "not available yet" in caplog.text
    assert cfg.wanted_types  # falls back rather than searching for nothing


def test_an_unknown_type_is_reported(caplog):
    with caplog.at_level("WARNING"):
        _cfg(types=["nonsense"])
    assert "not a known type" in caplog.text


def test_no_types_argument_leaves_the_default_alone():
    assert _cfg().wanted_types == _cfg(types=None).wanted_types


# --- the filter honours the selection ----------------------------------------

def test_the_filter_drops_the_other_type():
    from core.records import make_record
    from pipeline.filter import filter_records

    records = [
        make_record(title="PhD in Radio Astronomy", url="https://x/1",
                    short_description="radio astronomy interstellar medium",
                    source="t"),
        make_record(title="Postdoctoral Researcher in Radio Astronomy",
                    url="https://x/2",
                    short_description="radio astronomy interstellar medium",
                    source="t"),
    ]
    cfg = _cfg(types=["phd"])
    cfg.keep_ambiguous = False
    kept = filter_records([dict(r) for r in records], cfg)
    assert [r["position_type"] for r in kept] == ["phd"]

    cfg = _cfg(types=["postdoc"])
    cfg.keep_ambiguous = False
    kept = filter_records([dict(r) for r in records], cfg)
    assert [r["position_type"] for r in kept] == ["postdoc"]


# --- resilience: classification gates every record ---------------------------

def test_a_broken_registry_falls_back_to_the_builtin_types(tmp_path,
                                                           monkeypatch, caplog):
    """A typo in the YAML must not classify everything as 'unknown'."""
    (tmp_path / "position_types.yaml").write_text(
        "phd:\n  label: PhD\n  patterns: ['\\bph\\.?d\\b']\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with caplog.at_level("WARNING"):
        types = pt.reload_types()
    try:
        assert {"phd", "postdoc", "faculty", "staff"} <= {t.name for t in types}
        assert "missing required position type" in caplog.text
    finally:
        monkeypatch.undo()
        pt.reload_types()


def test_a_missing_yaml_falls_back_silently(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pt, "_yaml_path", lambda: None)
    try:
        assert {"phd", "postdoc"} <= {t.name for t in pt.reload_types()}
    finally:
        monkeypatch.undo()
        pt.reload_types()


def test_backcompat_shims_still_mirror_the_registry():
    """astra.py re-exports these and older tests import them."""
    from core import taxonomy
    assert taxonomy._TYPE_PRIORITY == pt.type_names()
    assert set(taxonomy._TYPE_PATTERNS) == set(pt.type_names())
    assert taxonomy._PHD_REQUIREMENT_NOISE.search("must hold a PhD")
