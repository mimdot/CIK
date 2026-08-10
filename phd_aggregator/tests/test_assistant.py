"""tests.test_assistant — Sprint 09, Track A1 (product AI drafting).

All LLM calls use a fake backend injected into LLMRouter — no provider, no
network, no API keys. Covers: prompts contain the opportunity facts, output
is editable text, the token cap is enforced, and the CV-improvement path
falls back to deterministic wording when the LLM fails or returns garbage.
"""

from __future__ import annotations

from core.assistant import (ASSISTANT_TOKEN_CAP, draft_application_email,
                            draft_cover_letter, suggest_cv_improvements)
from core.llm import LLMRouter
from core.profile_schema import UserProfile

OPP = {
    "title": "PhD position in interstellar medium",
    "institution": "MPIfR Bonn",
    "country": "Germany",
    "deadline": "2026-10-01",
    "funding_status": "fully funded",
    "short_description": "Radio interferometry on the galactic magnetic field.",
    "url": "https://example.com/pos/1",
    "match_explanation": "Strong topic match: your radio-interferometry "
                         "background aligns directly with this position.",
}

PROFILE = UserProfile(
    domain="astronomy",
    subfield="interstellar medium",
    methods=["radio interferometry"],
    tools=["LOFAR", "Python"],
    skills=["dust polarization"],
    experience_level="phd_student",
    target_roles=["postdoc"],
    countries_preferred=["Germany", "Netherlands"],
    funding_requirement="fully funded",
    confidence=0.9,
)


def _router(payload: str) -> LLMRouter:
    def backend(model, messages, **kw):
        return payload
    return LLMRouter(default_model="fake/model", backend=backend)


def test_cover_letter_prompt_contains_opportunity_facts():
    seen = {}

    def backend(model, messages, **kw):
        seen["prompt"] = messages[0]["content"]
        return "Dear Professor,\n\nI would like to apply..."

    llm = LLMRouter(default_model="fake/model", backend=backend)
    result = draft_cover_letter(PROFILE, OPP, llm=llm)
    prompt = seen["prompt"]
    assert "PhD position in interstellar medium" in prompt
    assert "MPIfR Bonn" in prompt
    assert "2026-10-01" in prompt
    assert "fully funded" in prompt
    assert "radio interferometry" in prompt          # profile facts grounded
    assert "GROUND RULES" in prompt                  # no-invention guardrail
    assert "Dear Professor" in result["text"]
    assert result["model"] == "fake/model"
    assert result["token_count"] > 0


def test_cover_letter_is_editable_draft_text():
    result = draft_cover_letter(PROFILE, OPP,
                                llm=_router("Some draft text"))
    assert isinstance(result["text"], str)
    assert len(result["text"]) > 0


def test_cover_letter_enforces_token_cap():
    huge = "word " * (ASSISTANT_TOKEN_CAP * 2)
    result = draft_cover_letter(PROFILE, OPP, llm=_router(huge))
    assert len(result["text"].split()) <= ASSISTANT_TOKEN_CAP + 1


def test_application_email_contains_facts():
    seen = {}

    def backend(model, messages, **kw):
        seen["prompt"] = messages[0]["content"]
        return "Dear Dr. Example, I am writing to ask about..."

    llm = LLMRouter(default_model="fake/model", backend=backend)
    result = draft_application_email(PROFILE, OPP, llm=llm)
    assert "Dear Dr. Example" in result["text"]
    assert "MPIfR Bonn" in seen["prompt"]
    assert "GROUND RULES" in seen["prompt"]


def test_cv_improvements_llm_path():
    payload = '{"improvements": ["Add LOFAR imaging", "Learn MCMC"]}'
    result = suggest_cv_improvements(
        PROFILE, gaps=["MCMC", "LOFAR imaging"], llm=_router(payload))
    assert result["source"] == "llm"
    assert result["improvements"] == ["Add LOFAR imaging", "Learn MCMC"]


def test_cv_improvements_falls_back_when_llm_fails():
    def backend(model, messages, **kw):
        raise RuntimeError("llm down")

    llm = LLMRouter(default_model="fake/model", backend=backend)
    result = suggest_cv_improvements(PROFILE, gaps=["MCMC"], llm=llm)
    assert result["source"] == "deterministic"
    assert any("MCMC" in i for i in result["improvements"])


def test_cv_improvements_falls_back_on_garbage_json():
    result = suggest_cv_improvements(PROFILE, gaps=["MCMC"],
                                     llm=_router("no json here"))
    assert result["source"] == "deterministic"
    assert result["improvements"]


def test_cv_improvements_no_gaps_is_deterministic():
    result = suggest_cv_improvements(PROFILE, gaps=[], llm=_router("{}"))
    assert result["source"] == "deterministic"
