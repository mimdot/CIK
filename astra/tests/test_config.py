#!/usr/bin/env python3
"""Offline tests for core/config.py (migration Step 1).

Cover the extracted configuration subsystem and, crucially, the back-compat
wiring: astra.py must still expose every name it used to define, the
config.yaml / fields/*.yaml layering must behave identically, and the
country-alias tables must stay visible to the monolith's geo helpers even
after apply_config_yaml() rebuilds _ALIAS_LOOKUP at runtime.

Run:  python -m pytest tests/test_config.py -q
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.config as _core_config
import astra as P


def _no_config(**kwargs) -> argparse.Namespace:
    base = dict(no_config=True, debug=False, phd_only=False, field=None)
    base.update(kwargs)
    return argparse.Namespace(**base)


# ---------------------------------------------------------------------------
# build_config defaults
# ---------------------------------------------------------------------------
def test_build_config_defaults_match_constants():
    # Default build (no flags, no config.yaml) still overlays the repo's
    # fields/astronomy.yaml taxonomy...
    cfg = P.build_config(_no_config())
    prof = P.load_field_profile("astronomy") or {}
    assert cfg.field_profile == "astronomy"
    assert cfg.subfield is None
    assert cfg.core_anchors == prof.get("core_anchors", P.CORE_ANCHORS)
    # ...while every non-taxonomy knob comes straight from the CONFIG block.
    assert cfg.output_path == P.OUTPUT_PATH
    assert cfg.write_html == P.WRITE_HTML
    assert cfg.proxy == P.PROXY
    assert cfg.proxy_fallback_direct == P.PROXY_FALLBACK_DIRECT
    assert cfg.timeout == P.REQUEST_TIMEOUT
    assert cfg.max_retries == P.MAX_RETRIES
    assert cfg.delay == P.REQUEST_DELAY
    assert cfg.robots_obey == P.ROBOTS_OBEY
    assert cfg.max_desc == P.MAX_DESC_CHARS
    assert cfg.exclude_expired == P.EXCLUDE_EXPIRED
    assert cfg.keep_ambiguous == P.KEEP_AMBIGUOUS
    assert cfg.wanted_types == P.WANTED_POSITION_TYPES
    assert cfg.sources_enabled == P.SOURCES_ENABLED
    assert cfg.max_age_days == P.MAX_AGE_DAYS


def test_build_config_builtin_defaults_without_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_core_config, "load_field_profile", lambda name: None)
    cfg = P.build_config(_no_config())
    assert cfg.core_anchors == P.CORE_ANCHORS
    assert cfg.context_terms == P.CONTEXT_TERMS
    assert cfg.negative_terms == P.NEGATIVE_TERMS
    assert cfg.search_terms == P.SEARCH_TERMS
    assert cfg.countries == P.COUNTRIES
    assert cfg.keep_ambiguous == P.KEEP_AMBIGUOUS
    assert cfg.sources_enabled == P.SOURCES_ENABLED
    assert cfg.field_profile == P.FIELD_PROFILE
    assert cfg.subfield is None
    assert cfg.weights == P.RELEVANCE_WEIGHTS
    assert cfg.threshold == P.RELEVANCE_THRESHOLD


def test_build_config_compiles_taxonomy():
    cfg = P.build_config(_no_config())
    assert cfg._core_rx and cfg._context_rx and cfg._negative_rx
    first_term, first_rx = cfg._core_rx[0]
    assert first_term == P.CORE_ANCHORS[0]
    assert first_rx.search(first_term + " PhD position") is not None
    ism = [rx for t, rx in cfg._core_rx if t == "ISM"]
    assert ism and ism[0].search("interstellar medium (ISM)") is not None
    assert ism[0].search("the mechanism is simple") is None


# ---------------------------------------------------------------------------
# config.yaml + CLI layering (constants < config.yaml < CLI flags)
# ---------------------------------------------------------------------------
def test_config_yaml_overlays_defaults(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        "output_path: xyz_run\nproxy: \"\"\nrequest_delay: 1.0\n"
        "keep_ambiguous: false\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cfg = P.build_config(argparse.Namespace(no_config=False))
    assert cfg.output_path == "xyz_run"
    assert cfg.proxy is None
    assert cfg.delay == 1.0
    assert cfg.keep_ambiguous is False


def test_cli_flags_beat_config_yaml(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        "output_path: from_yaml\nrequest_delay: 1.0\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(no_config=False, output="from_cli")
    cfg = P.build_config(args)
    assert cfg.output_path == "from_cli"


def test_field_profile_via_build_config(tmp_path, monkeypatch):
    (tmp_path / "fields").mkdir()
    (tmp_path / "fields" / "zzz.yaml").write_text(
        "core_anchors: [quantum dots]\nsearch_terms: [quantum]\n"
        "weights:\n  core_title: 9.0\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cfg = P.build_config(_no_config(field="zzz"))
    assert cfg.field_profile == "zzz"
    assert cfg.core_anchors == ["quantum dots"]
    assert cfg.weights["core_title"] == 9.0
    assert cfg.weights["core_desc"] == 2.5  # merged, not replaced


def test_no_config_skips_config_yaml(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("output_path: yaml_only\n",
                                          encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cfg = P.build_config(argparse.Namespace(no_config=True))
    assert cfg.output_path == P.OUTPUT_PATH


# ---------------------------------------------------------------------------
# apply_field_profile semantics
# ---------------------------------------------------------------------------
def test_apply_field_profile_replaces_and_merges():
    cfg = P.build_config(_no_config())
    P.apply_field_profile(cfg, {
        "core_anchors": ["marine biology"],
        "weights": {"core_title": 7.0},
        "threshold": 1.5,
    })
    assert cfg.core_anchors == ["marine biology"]
    assert cfg.weights["core_title"] == 7.0
    assert cfg.weights["negative"] == P.RELEVANCE_WEIGHTS["negative"]
    assert cfg.threshold == 1.5


def test_apply_field_profile_ignores_bad_values():
    cfg = P.build_config(_no_config())
    before = list(cfg.core_anchors)
    P.apply_field_profile(cfg, {
        "core_anchors": "not-a-list",
        "threshold": "not-a-number",
    })
    assert cfg.core_anchors == before
    assert cfg.threshold == P.RELEVANCE_THRESHOLD


# ---------------------------------------------------------------------------
# country-alias tables stay consistent across the core/monolith boundary
# ---------------------------------------------------------------------------
def test_country_aliases_propagate_to_canonical_country():
    """A user-added alias from config.yaml reaches canonical_country.

    Uses a nonsense alias on purpose: since Phase 2D, canonical_country falls
    through to the full ISO-3166 table plus a shipped colloquial-alias list, so
    a real-world abbreviation like "brd" now resolves on its own and could no
    longer prove that the config.yaml path was what did the work.
    """
    _core_config.reset_country_aliases()
    try:
        cfg = P.build_config(_no_config())
        assert P.canonical_country("zzland") is None
        P.apply_config_yaml(cfg, {"country_aliases": {"Germany": ["zzland"]}})
        assert P.canonical_country("zzland") == "Germany"
    finally:
        _core_config.reset_country_aliases()


def test_shipped_aliases_resolve_without_any_config():
    """The Phase 2D promise: real countries work out of the box."""
    _core_config.reset_country_aliases()
    try:
        P.build_config(_no_config())
        assert P.canonical_country("brd") == "Germany"
        assert P.canonical_country("Kazakhstan") == "Kazakhstan"
        assert P.canonical_country("KZ") == "Kazakhstan"
    finally:
        _core_config.reset_country_aliases()


def test_country_tables_are_shared_objects():
    assert P.ISO2_COUNTRY["DE"] == "Germany"
    assert _core_config._CANON_TO_ISO2["Germany"] == "DE"
    assert _core_config.ISO2_COUNTRY is P.ISO2_COUNTRY
    assert _core_config.COUNTRY_ALIASES is P.COUNTRY_ALIASES


# ---------------------------------------------------------------------------
# resolve_field_arg / list_field_profiles / _oa_field_id
# ---------------------------------------------------------------------------
def test_resolve_field_arg_subfield_of_nondefault_profile():
    pname, sub, profile = P.resolve_field_arg("econometrics")
    assert pname == "economics"
    assert sub == "econometrics"
    assert profile is not None


def test_resolve_field_arg_default_profile():
    pname, sub, profile = P.resolve_field_arg("astronomy")
    assert pname == "astronomy"
    assert sub is None
    assert profile is not None


def test_resolve_field_arg_unknown_raises():
    try:
        P.resolve_field_arg("no_such_field_xyz")
    except SystemExit as exc:
        assert "no_such_field_xyz" in str(exc)
    else:
        raise AssertionError("expected SystemExit for unknown --field")


def test_list_field_profiles_excludes_template():
    names = P.list_field_profiles()
    assert "template" not in names
    assert names == sorted(names)
    assert {"astronomy", "computer_science"} <= set(names)


def test_oa_field_id_normalization():
    assert P._oa_field_id("https://openalex.org/fields/20") == "20"
    assert P._oa_field_id("fields/31") == "31"
    assert P._oa_field_id("16") == "16"
    assert P._oa_field_id("banana") is None
    assert P._oa_field_id({"id": "https://openalex.org/fields/17"}) == "17"


# ---------------------------------------------------------------------------
# _script_dir fix: config/fields must still resolve next to the script
# ---------------------------------------------------------------------------
def test_script_dir_resolves_to_aggregator_dir():
    assert os.path.basename(_core_config._script_dir()) == "astra"


def test_find_config_path_falls_back_to_script_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = P._find_config_path("config.yaml")
    assert path is not None
    assert path.endswith("astra" + os.sep + "config.yaml")
    assert P.load_field_profile("astronomy") is not None


def test_load_yaml_file_missing_returns_none(tmp_path):
    assert P._load_yaml_file(os.path.join(str(tmp_path), "nope.yaml")) is None


# ---------------------------------------------------------------------------
# back-compat: monolith still exposes the whole config API
# ---------------------------------------------------------------------------
def test_backcompat_surface():
    for name in ("Config", "build_config", "apply_config_yaml",
                 "apply_field_profile", "load_field_profile",
                 "list_field_profiles", "resolve_field_arg",
                 "compile_taxonomy", "_compile_term", "_oa_field_id",
                 "_find_config_path", "_load_yaml_file", "_CANON_TO_ISO2",
                 "_HAVE_YAML", "CORE_ANCHORS", "CONTEXT_TERMS",
                 "NEGATIVE_TERMS", "FIELD_PROFILE", "CONFIG_FILE",
                 "FIELDS_DIR", "SUBFIELDS", "SOURCES_ENABLED", "SEARCH_TERMS",
                 "COUNTRY_ALIASES", "ISO2_COUNTRY", "SUPERVISOR_SOURCE"):
        assert hasattr(P, name), name
        assert hasattr(_core_config, name), name


# ---------------------------------------------------------------------------
# Config convenience properties
# ---------------------------------------------------------------------------
def test_config_path_properties():
    cfg = P.build_config(_no_config())
    # `stem` is os.path.splitext of what it was GIVEN — it does not rewrite
    # separators, and Windows accepts a forward slash in a path anyway. So the
    # expectation is the literal input, not os.path.join: joining rebuilt these
    # with a backslash on Windows and failed a test the code had passed.
    cfg.output_path = "out/results.csv"
    assert cfg.stem == "out/results"
    assert cfg.csv_path == "out/results.csv"
    assert cfg.json_path == "out/results.json"
    assert cfg.html_path == "out/results.html"
    assert cfg.geo_filter_active is False
    cfg.countries = ["Germany"]
    assert cfg.geo_filter_active is True


# --- field_profile_keywords is a FILTER, not a keyword dump ------------------

def test_field_filter_excludes_context_terms():
    """context_terms are boost-only and must never qualify a record.

    This is the supervisor "results are not filtered" bug. The filter used to
    include context_terms, so a statistics search filtered on "machine
    learning", "collaboration", "benchmark" -- and on "R", a single letter,
    whose LIKE '%r%' matched essentially every supervisor row in the table.
    """
    from core.config import field_profile_keywords
    kws = field_profile_keywords("statistics_data_science")
    assert kws, "profile should yield qualifying terms"
    # Straight from that profile's context_terms: tooling and generic research
    # vocabulary, none of which establishes that a supervisor is a statistician.
    # "r" is the one that made the bug total -- LIKE '%r%' matches every row.
    for boost_only in ("machine learning", "collaboration", "benchmark",
                       "python", "r", "gpu", "big data", "covariate"):
        assert boost_only not in kws, (
            f"{boost_only!r} is a context term and must not qualify a record")
    # "deep learning" IS present and should be: it arrives from the
    # statistical_ml SUBFIELD, where it is subject matter rather than context.
    # Subfield keywords qualify their subfield by design, so the filter keeps
    # them; the rule being enforced here is about context_terms specifically.
    assert "deep learning" in kws
    # ...while the anchors that define the field are still there.
    assert "bayesian" in kws
    assert "causal inference" in kws


def test_field_filter_drops_terms_that_are_unsafe_as_substrings():
    """No term may match inside an unrelated word.

    Two classes: anything under three characters, and the schema's ALL-CAPS
    acronyms -- which are whole-word/case-sensitive by design, a rule this
    lowercased substring list cannot express. '%tem%' would match "system",
    '%sem%' "assembly", '%ism%' "mechanism", '%ert%' "expert".
    """
    from core.config import field_profile_keywords, list_field_profiles
    unrelated = ["system", "assembly", "expert", "mechanism", "laboratory",
                 "strategy", "temperature", "demonstration", "generation"]
    for field in list_field_profiles():
        for kw in field_profile_keywords(field):
            assert len(kw) >= 3, f"{field}: {kw!r} is too short to filter on"
            for word in unrelated:
                # `analysis` (mathematics) is a real, deliberate anchor and the
                # only accepted overlap; everything else must be clean.
                if kw == "analysis":
                    continue
                assert kw not in word, (
                    f"{field}: {kw!r} matches inside {word!r} as a substring")


def test_field_filter_is_empty_for_an_unknown_profile():
    """An unknown field must yield [] so callers can say 'no results' rather
    than silently matching everything."""
    from core.config import field_profile_keywords
    assert field_profile_keywords("underwater_basket_weaving") == []
