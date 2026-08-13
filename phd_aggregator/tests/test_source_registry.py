"""Field-aware source registry (Phase 1A).

The defect these tests lock down: `fetch_sources` used to read a single global
`sources_enabled` dict, so selecting *chemistry* still crawled the AAS Job
Register, ESO and ESA. Sources now declare which disciplines they serve and a
resolver intersects that with the user's on/off switches.

The astronomy assertions are the no-regression guard: astronomy must keep
resolving to exactly the set it crawled before this change.
"""

from __future__ import annotations

import pytest

import sources  # noqa: F401 — importing populates the registry
from core.config import SOURCES_ENABLED
from sources.base import (ANY_FIELD, SOURCE_INFO, SOURCES, SourceInfo,
                          general_sources, register_source,
                          resolve_sources_for_field,
                          specialist_sources_for_field)


# Sources that were enabled in config.yaml before the registry existed — the
# exact set an astronomy run crawled, and therefore must still crawl.
LEGACY_ENABLED = {
    "euraxess", "nature_careers", "jobs_ac_uk", "findaphd", "academictransfer",
    "academicjobsonline", "aas", "jrecin", "eso", "esa", "linkedin",
    "uni_departments", "seed_urls",
}
ASTRONOMY_ONLY = {"aas", "eso"}


def _on(field, enabled=None):
    resolved = resolve_sources_for_field(field, enabled or SOURCES_ENABLED)
    return {name for name, is_on in resolved.items() if is_on}


# --- registry shape ----------------------------------------------------------

def test_every_source_has_registry_metadata():
    """SOURCES and SOURCE_INFO stay in lockstep — no source without metadata."""
    assert set(SOURCES) == set(SOURCE_INFO)
    assert all(isinstance(info, SourceInfo) for info in SOURCE_INFO.values())


def test_astronomy_only_boards_declare_astronomy():
    for name in ASTRONOMY_ONLY:
        info = SOURCE_INFO[name]
        assert not info.is_general, f"{name} must not be a general board"
        assert info.fields == ("astronomy",)


def test_esa_serves_space_science_and_engineering():
    """ESA hires astronomers, physicists and (heavily) engineers."""
    assert set(SOURCE_INFO["esa"].fields) == {"astronomy", "physics",
                                              "engineering"}


def test_multidiscipline_boards_are_general():
    for name in ("euraxess", "jobs_ac_uk", "findaphd", "nature_careers",
                 "academictransfer", "academicjobsonline", "jrecin",
                 "linkedin", "seed_urls", "uni_departments"):
        assert SOURCE_INFO[name].is_general, f"{name} should serve every field"
    assert set(general_sources()) >= {"euraxess", "jobs_ac_uk"}


# --- the resolver ------------------------------------------------------------

def test_astronomy_resolves_to_the_legacy_set_unchanged():
    """No regression: astronomy keeps every board it crawled before."""
    assert _on("astronomy") == LEGACY_ENABLED


def test_no_field_selected_keeps_old_behaviour():
    """field=None is a no-op — sources_enabled alone decides, as before."""
    assert _on(None) == LEGACY_ENABLED


@pytest.mark.parametrize("field", ["chemistry", "biology", "computer_science",
                                   "mathematics", "economics"])
def test_zero_astronomy_only_sources_for_other_fields(field):
    """The headline fix: a chemistry run must not touch an astronomy board."""
    resolved = _on(field)
    assert not (resolved & ASTRONOMY_ONLY), (
        f"{field} still resolves astronomy-only sources: "
        f"{sorted(resolved & ASTRONOMY_ONLY)}")
    assert "esa" not in resolved  # space agency: not a chemistry/biology board


def test_other_fields_still_get_every_general_board():
    """Excluding specialists must not shrink a field's general coverage."""
    chemistry = _on("chemistry")
    assert chemistry == {n for n in general_sources() if n in LEGACY_ENABLED}
    assert len(chemistry) == 10


def test_physics_and_engineering_keep_esa():
    for field in ("physics", "engineering"):
        resolved = _on(field)
        assert "esa" in resolved
        assert not (resolved & ASTRONOMY_ONLY)


def test_disabled_source_stays_off_even_when_relevant():
    """sources_enabled can only ever turn a source OFF, never on."""
    enabled = dict(SOURCES_ENABLED, aas=False)
    assert "aas" not in _on("astronomy", enabled)


def test_stub_sources_stay_off():
    """Disabled-by-design stubs are not resurrected by the resolver."""
    assert not (_on("astronomy") & {"iau", "astrobetter", "china", "korea"})


# --- profile-declared sources ------------------------------------------------

def test_profile_sources_block_claims_a_specialist_board():
    """A field can claim a board in YAML without touching any Python."""
    resolved = resolve_sources_for_field(
        "chemistry", dict(SOURCES_ENABLED, aas=True), profile_sources=["aas"])
    assert resolved["aas"] is True


def test_unknown_profile_source_is_ignored_not_fatal(caplog):
    with caplog.at_level("WARNING"):
        resolved = resolve_sources_for_field(
            "chemistry", SOURCES_ENABLED,
            profile_sources=["not_a_real_board"])
    assert "not_a_real_board" not in resolved
    assert "unknown source" in caplog.text


def test_field_with_no_dedicated_sources_logs_the_fallback(caplog):
    """The brief's requirement: say so, clearly, instead of failing quietly."""
    with caplog.at_level("INFO"):
        resolved = resolve_sources_for_field("marine_biology", SOURCES_ENABLED)
    assert "no dedicated sources for 'marine_biology'" in caplog.text
    assert any(resolved.values()), "must still fall back to general boards"


def test_specialist_lookup_by_field():
    assert set(specialist_sources_for_field("astronomy")) >= ASTRONOMY_ONLY
    assert specialist_sources_for_field("chemistry") == []
    assert specialist_sources_for_field(None) == []


# --- the decorator -----------------------------------------------------------

def test_register_source_defaults_to_general():
    try:
        @register_source("_t_general")
        def _src(cfg, http):
            return []
        assert SOURCE_INFO["_t_general"].fields == (ANY_FIELD,)
        assert SOURCE_INFO["_t_general"].serves("anything")
    finally:
        SOURCE_INFO.pop("_t_general", None)
        SOURCES.pop("_t_general", None)


# --- end-to-end: what a real run actually crawls ----------------------------

def _crawled_sources(field, monkeypatch, only_sources=None):
    """Names fetch_sources really calls, with the network stubbed out."""
    import argparse

    import pipeline.run as run_mod
    from core.config import build_config

    called: list[str] = []

    def _fake(name):
        def _fn(cfg, http):
            called.append(name)
            return []
        return _fn

    monkeypatch.setattr(run_mod, "SOURCES",
                        {n: _fake(n) for n in SOURCES})
    monkeypatch.setattr(run_mod, "Http",
                        lambda cfg, detect=True: type(
                            "H", (), {"close": lambda self: None})())
    cfg = build_config(argparse.Namespace(field=field, no_config=True))
    run_mod.fetch_sources(cfg, only_sources=only_sources)
    return set(called)


def test_chemistry_run_queries_zero_astronomy_only_sources(monkeypatch):
    """Phase 8 requirement, end to end: not merely 'resolved off' — the
    astronomy source functions are never CALLED for a chemistry run."""
    crawled = _crawled_sources("chemistry", monkeypatch)
    assert not (crawled & ASTRONOMY_ONLY)
    assert "esa" not in crawled
    assert "euraxess" in crawled and "findaphd" in crawled


def test_astronomy_run_still_queries_its_specialist_boards(monkeypatch):
    """Astronomy must not be weakened — it keeps every board it had."""
    assert _crawled_sources("astronomy", monkeypatch) == LEGACY_ENABLED


def test_explicit_source_flag_overrides_the_field(monkeypatch):
    """--source aas is the user naming names; honour it even for chemistry."""
    crawled = _crawled_sources("chemistry", monkeypatch, only_sources=["aas"])
    assert crawled == {"aas"}


def test_register_source_dedupes_and_falls_back_to_general():
    try:
        @register_source("_t_dupes", fields=("chemistry", "chemistry", "  "))
        def _src(cfg, http):
            return []
        assert SOURCE_INFO["_t_dupes"].fields == ("chemistry",)

        @register_source("_t_empty", fields=())
        def _src2(cfg, http):
            return []
        assert SOURCE_INFO["_t_empty"].is_general
    finally:
        for name in ("_t_dupes", "_t_empty"):
            SOURCE_INFO.pop(name, None)
            SOURCES.pop(name, None)
