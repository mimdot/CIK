"""Tests for Phase 2 (Track B): core.llm (LLMRouter), core.profile_schema
(UserProfile), and core.profile (extract_profile). All LLM calls are mocked —
no provider, no litellm, no network required."""

from __future__ import annotations

import json

from core.llm import LLMRouter, extract_json_block
from core.profile import extract_profile
from core.profile_schema import EXPERIENCE_LEVELS, UserProfile

CV_TEXT = """Mohammad is a PhD student in astronomy at Tehran University.
He works on the interstellar medium and magnetic fields, using radio
interferometry (LOFAR, VLA) and Python. He develops MHD simulations with
dust-polarization methods. He aims to become a postdoc in Europe, prefers
Germany and the Netherlands, and needs a funded position."""


class _StubLLM(LLMRouter):
    """LLM stub returning a canned JSON payload for the profile extraction."""

    def __init__(self, payload):
        super().__init__(backend=self)
        self.payload = payload

    def _call(self, model, prompt, schema):
        if isinstance(self.payload, dict):
            return json.dumps(self.payload)
        return self.payload

    def complete(self, prompt, schema=None):
        return self._call(self.default_model, prompt, schema)


# ---------------------------------------------------------------------------
# B1 — core.llm
# ---------------------------------------------------------------------------
def test_llm_router_uses_backend_and_returns_text():
    seen = {}
    def backend(model, messages, **kw):
        seen["model"] = model
        # schema is embedded in the prompt text; response_format must NOT be
        # passed for json mode (litellm's json_object has no schema key)
        assert "response_format" not in kw
        assert messages[0]["content"] == "hi"
        return "{\"ok\": true}"
    llm = LLMRouter(default_model="fake/model", backend=backend)
    out = llm.complete("hi", schema={"type": "object"})
    assert out == '{"ok": true}'
    assert seen["model"] == "fake/model"


def test_llm_router_falls_back_after_failures():
    calls = []
    def backend(model, messages, **kw):
        calls.append(model)
        raise RuntimeError("boom")
    llm = LLMRouter(default_model="primary/m", fallback_model="fallback/m",
                    backend=backend, max_retries=1)
    try:
        llm.complete("hi")
        raise AssertionError("expected failure")
    except RuntimeError:
        pass
    assert calls[-1] == "fallback/m"          # fallback was attempted last
    assert calls.count("primary/m") == 2      # 1 + max_retries attempts


def test_extract_json_block_strips_fences_and_prose():
    assert extract_json_block('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_block('Here you go: {"a": 1} thanks') == {"a": 1}


# ---------------------------------------------------------------------------
# B2 — core.profile_schema
# ---------------------------------------------------------------------------
def test_userprofile_validates_full_fixture():
    p = UserProfile(
        domain="astronomy",
        subfield="interstellar medium",
        methods=["radio interferometry", "MHD simulation"],
        tools=["LOFAR", "VLA", "Python"],
        skills=["dust polarization"],
        experience_level="phd_student",
        target_roles=["postdoc"],
        countries_preferred=["Germany", "Netherlands"],
        funding_requirement="fully funded",
        constraints=["must be funded"],
        confidence=0.9,
        raw_text=CV_TEXT,
    )
    assert p.confidence == 0.9
    assert p.experience_level in EXPERIENCE_LEVELS
    assert "Germany" in p.countries_preferred


def test_userprofile_defaults_and_bounds():
    p = UserProfile(domain="astronomy")
    assert p.skills == [] and p.methods == []
    assert 0.0 <= p.confidence <= 1.0

    import pytest
    with pytest.raises(Exception):
        UserProfile(domain="astronomy", confidence=1.5)


def test_userprofile_to_db_columns():
    p = UserProfile(domain="astronomy", skills=["a", "b"])
    cols = p.to_db_columns()
    assert cols["domain"] == "astronomy"
    assert cols["skills"] == ["a", "b"]
    assert cols["raw_text"] == ""


# ---------------------------------------------------------------------------
# B3 — core.profile
# ---------------------------------------------------------------------------
def test_extract_profile_with_stub_llm():
    payload = {
        "domain": "astronomy",
        "subfield": "interstellar medium",
        "methods": ["radio interferometry", "MHD simulation"],
        "tools": ["LOFAR", "Python"],
        "skills": ["dust polarization"],
        "experience_level": "phd_student",
        "target_roles": ["postdoc"],
        "countries_preferred": ["Germany", "Netherlands"],
        "funding_requirement": "fully funded",
        "constraints": [],
        "confidence": 0.85,
    }
    profile = extract_profile(CV_TEXT, _StubLLM(payload))
    assert profile is not None
    assert profile.domain == "astronomy"
    assert profile.experience_level == "phd_student"
    assert profile.countries_preferred == ["Germany", "Netherlands"]
    assert profile.raw_text == CV_TEXT


def test_extract_profile_returns_none_on_garbage():
    assert extract_profile(CV_TEXT, _StubLLM("not json at all")) is None
