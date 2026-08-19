"""tests.test_digest — Sprint 07, Track A2.

Covers the deterministic digest contract: selection thresholds (only
score > 0.85), caps (≤5 positions, ≤5 supervisors), ordering, and the rendered
subject/html/text all including why/deadline/funding/next-step. Purely offline.
"""

from __future__ import annotations

from core.digest import (DIGEST_MAX_POSITIONS, DIGEST_MAX_SUPERVISORS,
                         DIGEST_MIN_SCORE, build_digest, digest_llm_enabled,
                         rewrite_reasons, select_supervisors,
                         select_top_positions)
from core.llm import LLMRouter
from core.profile_schema import UserProfile

PROFILE = UserProfile(domain="astronomy", subfield="interstellar medium",
                      methods=["radio interferometry"], tools=["python"],
                      countries_preferred=["Germany", "Netherlands"],
                      funding_requirement="fully funded")


def _pos(match_score, title="PhD in radio astronomy", deadline="2026-10-01",
         country="Germany", funding="funded"):
    return {"title": title, "institution": "MPIfR", "country": country,
            "url": f"https://ex.org/j/{match_score}", "deadline": deadline,
            "funding_status": funding,
            "match_explanation": f"Strong topic match for {title}.",
            "match_score": match_score}


def _sup(name="Dr. Alvarez", fit_score=0.9, topics=("ISM", "magnetism")):
    return {"name": name, "institution": "MPIfR", "country": "Germany",
            "fit_score": fit_score, "topics": list(topics),
            "profile_url": "https://ex.org/orcid/0000"}


# --- selection ----------------------------------------------------------------
def test_select_top_positions_filters_below_threshold():
    matches = [_pos(0.9), _pos(0.5), _pos(0.84), _pos(0.86)]
    out = select_top_positions(matches)
    scores = [m["match_score"] for m in out]
    assert all(s > DIGEST_MIN_SCORE for s in scores)
    assert 0.5 not in scores and 0.84 not in scores


def test_select_top_positions_caps_and_orders():
    matches = [_pos(0.86, title="A"), _pos(0.92, title="B"),
               _pos(0.95, title="C"), _pos(0.97, title="D"),
               _pos(0.93, title="E"), _pos(0.99, title="F")]
    out = select_top_positions(matches)
    assert len(out) <= DIGEST_MAX_POSITIONS
    assert [m["title"] for m in out] == ["F", "D", "C", "E", "B"]  # score desc


def test_select_top_positions_never_mutates_input():
    matches = [_pos(0.9, title="Z"), _pos(0.8, title="A")]
    original = [dict(m) for m in matches]
    select_top_positions(matches)
    assert [m["title"] for m in matches] == [original[0]["title"],
                                             original[1]["title"]]


def test_select_top_positions_sorts_by_real_date_not_lexicographic():
    """Chronological deadline ordering, not a string compare: "2026-10-1"
    sorts BEFORE "2026-9-1" lexicographically ('1' < '9'), but Sept 1 is the
    genuinely earlier deadline."""
    early = _pos(0.9, title="Sep", deadline="2026-9-1")
    late = _pos(0.9, title="Oct", deadline="2026-10-1")
    out = select_top_positions([late, early])
    assert [m["title"] for m in out] == ["Sep", "Oct"]


def test_select_top_positions_undated_sorts_last():
    dated = _pos(0.9, title="Dated", deadline="2026-09-01")
    rolling = _pos(0.9, title="Rolling", deadline=None)
    out = select_top_positions([rolling, dated])
    assert [m["title"] for m in out] == ["Dated", "Rolling"]


def test_select_top_positions_accepts_datetime_deadlines():
    from datetime import datetime
    early = _pos(0.9, title="Early", deadline=datetime(2026, 9, 1))
    late = _pos(0.9, title="Late", deadline=datetime(2026, 10, 5))
    out = select_top_positions([late, early])
    assert [m["title"] for m in out] == ["Early", "Late"]


def test_select_supervisors_caps_and_orders():
    sups = [_sup("A", 0.9), _sup("B", 0.95), _sup("C", 0.5), _sup("D", 0.7),
            _sup("E", 0.8), _sup("F", 0.85)]
    out = select_supervisors(sups)
    assert len(out) <= DIGEST_MAX_SUPERVISORS
    assert out[0]["name"] == "B"
    assert all(o["fit_score"] >= out[-1]["fit_score"] for o in out)


def test_select_supervisors_empty_input():
    assert select_supervisors(None) == []
    assert select_supervisors([]) == []


# --- rendering ----------------------------------------------------------------
def test_build_digest_subject_includes_domain():
    d = build_digest(PROFILE, positions=[_pos(0.9)])
    assert "astronomy/interstellar medium" in d["subject"]


def test_build_digest_includes_why_deadline_funding_next():
    d = build_digest(PROFILE, positions=[_pos(0.9, funding="fully funded")])
    assert "Strong topic match" in d["html"]
    assert "Deadline" in d["html"]
    assert "fully funded" in d["html"]
    assert "Apply by" in d["html"] or "apply" in d["html"].lower()


def test_build_digest_excludes_low_scoring():
    d = build_digest(PROFILE, positions=[_pos(0.9), _pos(0.3)])
    assert "PhD in radio astronomy" in d["html"]
    assert "2026-10-01" in d["html"]  # from the 0.9 item
    # The 0.3 item shares the same title, so count table rows instead.
    assert d["html"].count("<tr>") == 1


def test_build_digest_no_positions_message():
    d = build_digest(PROFILE, positions=[_pos(0.5)])
    assert "No matching positions this week" in d["html"]
    assert "No matching positions this week" in d["text"]


def test_build_digest_includes_supervisors_only_when_enabled():
    sups = [_sup()]
    without = build_digest(PROFILE, positions=[_pos(0.9)],
                           supervisors=sups, include_supervisors=False)
    with_ = build_digest(PROFILE, positions=[_pos(0.9)],
                         supervisors=sups, include_supervisors=True)
    assert "Supervisors worth contacting" not in without["html"]
    assert "Supervisors worth contacting" in with_["html"]
    assert "Dr. Alvarez" in with_["html"]


def test_build_digest_text_version_has_actions():
    d = build_digest(PROFILE, positions=[_pos(0.9, deadline="2026-09-30")],
                     supervisors=[_sup()], include_supervisors=True)
    assert "next step" in d["text"].lower()
    assert "2026-09-30" in d["text"]
    assert "Dr. Alvarez" in d["text"]


def test_build_digest_plain_profile_without_subfield():
    p = UserProfile(domain="biology")
    d = build_digest(p, positions=[_pos(0.9)])
    assert "Your weekly career digest (biology)" == d["subject"]


# --- Sprint 09 v2: LLM reason rewrite (always falls back deterministically)
def _fake_llm(payload: str) -> LLMRouter:
    def backend(model, messages, **kw):
        return payload
    return LLMRouter(default_model="fake/model", backend=backend)


def test_rewrite_reasons_returns_aligned_sentences():
    items = [_pos(0.9, title="Alpha"), _pos(0.95, title="Beta")]
    llm = _fake_llm('{"reasons": [{"index": 0, "reason": "Matches your ISM '
                    'background."}, {"index": 1, "reason": "Needs your '
                    'methods."}]}')
    reasons = rewrite_reasons(items, llm)
    assert reasons[0] == "Matches your ISM background."
    assert reasons[1] == "Needs your methods."


def test_rewrite_reasons_none_when_llm_fails():
    def backend(model, messages, **kw):
        raise RuntimeError("llm down")
    llm = LLMRouter(default_model="fake/model", backend=backend)
    reasons = rewrite_reasons([_pos(0.9)], llm)
    assert reasons == [None]


def test_rewrite_reasons_none_on_garbage():
    reasons = rewrite_reasons([_pos(0.9)], _fake_llm("not json"))
    assert reasons == [None]


def test_build_digest_uses_rewritten_reason():
    llm = _fake_llm('{"reasons": [{"index": 0, '
                    '"reason": "This fits you because of your LOFAR work."}]}')
    d = build_digest(PROFILE, positions=[_pos(0.9)], llm=llm)
    assert "This fits you because of your LOFAR work." in d["html"]
    assert "This fits you because of your LOFAR work." in d["text"]
    # Deterministic fallback text must NOT be used when the rewrite exists.
    assert "Strong topic match" not in d["html"]


def test_build_digest_falls_back_when_llm_fails():
    def backend(model, messages, **kw):
        raise RuntimeError("llm down")
    llm = LLMRouter(default_model="fake/model", backend=backend)
    d = build_digest(PROFILE, positions=[_pos(0.9)], llm=llm)
    assert "Strong topic match" in d["html"]     # deterministic fallback


def test_build_digest_never_raises_on_llm_failure():
    def backend(model, messages, **kw):
        raise RuntimeError("llm down")
    llm = LLMRouter(default_model="fake/model", backend=backend)
    d = build_digest(PROFILE, positions=[_pos(0.9), _pos(0.95)], llm=llm)
    assert "Subject" not in d
    assert "Your weekly career digest" in d["subject"]


def test_digest_llm_enabled_defaults_on_and_can_be_disabled():
    assert digest_llm_enabled() is True
    import os
    try:
        os.environ["DIGEST_LLM_ENABLED"] = "0"
        assert digest_llm_enabled() is False
    finally:
        os.environ.pop("DIGEST_LLM_ENABLED", None)


def test_build_digest_skips_rewrite_when_toggle_off():
    import os
    llm = _fake_llm('{"reasons": [{"index": 0, '
                    '"reason": "LLM version."}]}')
    try:
        os.environ["DIGEST_LLM_ENABLED"] = "0"
        d = build_digest(PROFILE, positions=[_pos(0.9)], llm=llm)
        assert "LLM version." not in d["html"]
        assert "Strong topic match" in d["html"]
    finally:
        os.environ.pop("DIGEST_LLM_ENABLED", None)