"""tests.core.saved_keys — the identity a saved item is kept by.

The whole point is surviving a re-crawl, so the tests that matter are the ones
where the same posting arrives looking slightly different and must key the
same — and, just as important, where two different postings must NOT collide.
"""

from __future__ import annotations

import pytest

from core.saved_keys import (key_for, normalize_url, opportunity_key,
                             supervisor_key)


class TestNormalizeUrl:
    @pytest.mark.parametrize("a,b", [
        ("https://example.org/jobs/1", "http://example.org/jobs/1"),
        ("https://example.org/jobs/1", "https://www.example.org/jobs/1"),
        ("https://example.org/jobs/1", "https://example.org/jobs/1/"),
        ("https://EXAMPLE.org/jobs/1", "https://example.org/jobs/1"),
        ("https://example.org/jobs/1", "https://example.org/jobs/1#apply"),
        ("https://example.org/jobs/1?utm_source=x", "https://example.org/jobs/1"),
        ("https://example.org/jobs/1?a=1&b=2", "https://example.org/jobs/1?b=2&a=1"),
        ("https://example.org//jobs//1", "https://example.org/jobs/1"),
    ])
    def test_same_page_normalises_the_same(self, a, b):
        assert normalize_url(a) == normalize_url(b)

    @pytest.mark.parametrize("a,b", [
        ("https://example.org/jobs/1", "https://example.org/jobs/2"),
        ("https://example.org/jobs/1", "https://other.org/jobs/1"),
        ("https://example.org/jobs?id=1", "https://example.org/jobs?id=2"),
    ])
    def test_different_pages_stay_different(self, a, b):
        assert normalize_url(a) != normalize_url(b)

    def test_meaningful_query_is_kept(self):
        """FindAPhD's per-discipline token lives in the query string."""
        assert "10m7w0" in normalize_url(
            "https://www.findaphd.com/phds/physics/?10M7W0").lower()

    @pytest.mark.parametrize("bad", [None, "", "   "])
    def test_nothing_usable_gives_empty(self, bad):
        assert normalize_url(bad) == ""


class TestOpportunityKey:
    def test_survives_a_recrawl_that_changes_the_row_id(self):
        """The failure this exists to prevent."""
        before = {"id": 41, "url": "https://example.org/p/1", "source": "euraxess"}
        after = {"id": 903, "url": "http://www.example.org/p/1/", "source": "euraxess"}
        assert opportunity_key(before) == opportunity_key(after)

    def test_falls_back_to_the_upstream_id_without_a_url(self):
        a = {"source": "euraxess", "source_raw": "abc-123"}
        b = {"source": "euraxess", "source_raw": "abc-123", "title": "renamed"}
        assert opportunity_key(a) == opportunity_key(b)

    def test_last_resort_uses_the_record_itself(self):
        a = {"title": "PhD in ISM", "institution": "MPIfR"}
        b = {"title": "PhD in ISM", "institution": "MPIfR"}
        c = {"title": "PhD in cosmology", "institution": "MPIfR"}
        assert opportunity_key(a) == opportunity_key(b)
        assert opportunity_key(a) != opportunity_key(c)

    def test_different_postings_never_collide(self):
        a = {"url": "https://example.org/p/1"}
        b = {"url": "https://example.org/p/2"}
        assert opportunity_key(a) != opportunity_key(b)


class TestSupervisorKey:
    def test_orcid_wins_over_a_moved_profile_page(self):
        before = {"orcid": "0000-0002-1825-0097",
                  "profile_url": "https://old.example.edu/~a"}
        after = {"orcid": "0000-0002-1825-0097",
                 "profile_url": "https://new.example.edu/people/a"}
        assert supervisor_key(before) == supervisor_key(after)

    def test_profile_url_when_there_is_no_orcid(self):
        a = {"profile_url": "https://example.edu/people/a"}
        b = {"profile_url": "http://www.example.edu/people/a/"}
        assert supervisor_key(a) == supervisor_key(b)

    def test_name_and_institution_as_a_last_resort(self):
        a = {"name": "Ada Lovelace", "institution": "MPIfR"}
        b = {"name": "  ada   lovelace ", "institution": "mpifr"}
        assert supervisor_key(a) == supervisor_key(b)

    def test_same_name_at_a_different_institution_is_a_different_person(self):
        a = {"name": "Ada Lovelace", "institution": "MPIfR"}
        b = {"name": "Ada Lovelace", "institution": "ESO"}
        assert supervisor_key(a) != supervisor_key(b)


class TestKeyFor:
    def test_dispatches_to_the_right_scheme(self):
        record = {"url": "https://example.org/x",
                  "orcid": "0000-0002-1825-0097"}
        # An opportunity keys on its URL; a supervisor prefers the ORCID. Same
        # record, deliberately different keys — the kinds are separate spaces.
        assert key_for("opportunity", record) == opportunity_key(record)
        assert key_for("supervisor", record) == supervisor_key(record)
        assert key_for("opportunity", record) != key_for("supervisor", record)

    def test_an_unknown_kind_is_refused_loudly(self):
        with pytest.raises(ValueError):
            key_for("banana", {"url": "https://example.org/x"})
