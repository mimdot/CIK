"""core.assistant — LLM-assisted drafting (Sprint 09, Track A1).

Cover-letter / application-email drafting and CV-improvement suggestions,
built on :class:`core.llm.LLMRouter`. The LLM is a **drafting tool only**:

- Every prompt is grounded in the given profile + opportunity facts and the
  deterministic match explanation. The model is told never to invent skills,
  publications, projects or experience.
- ``temperature=0.3``, a token cap on the returned text, and a deterministic
  fallback for every function (the dashboard always has *something* to show
  even when the LLM is down or rate-limited).
- Drafts are never auto-submitted — the dashboard renders an editable copy.

All functions accept an optional ``llm`` (an ``LLMRouter``); tests inject one
with a fake backend so the suite stays offline.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from core.llm import LLMRouter
from core.profile_schema import UserProfile

log = logging.getLogger("astra")

ASSISTANT_MODEL = os.environ.get("ASSISTANT_MODEL", "openai/gpt-4o-mini")
ASSISTANT_TEMPERATURE = 0.3
ASSISTANT_TOKEN_CAP = int(os.environ.get("ASSISTANT_TOKEN_CAP", "600"))


def _router() -> LLMRouter:
    """A default router for the drafting features (temperature 0.3)."""
    return LLMRouter(default_model=ASSISTANT_MODEL,
                     fallback_model=os.environ.get("LLM_FALLBACK_MODEL",
                                                   "ollama/llama3.1:8b"),
                     temperature=ASSISTANT_TEMPERATURE)


def _estimate_tokens(text: str) -> int:
    """A rough token estimate (words) used for per-call accounting."""
    return len((text or "").split())


def _truncate(text: str, cap: int = ASSISTANT_TOKEN_CAP) -> str:
    """Enforce the per-draft token cap (defensive — the prompt also limits
    length, but the cap is non-negotiable)."""
    words = (text or "").split()
    if len(words) <= cap:
        return text or ""
    return " ".join(words[:cap]) + " …"


def _profile_facts(profile: UserProfile) -> str:
    """A compact, fact-only summary of the profile for the prompt."""
    lines = [f"Domain: {profile.domain or 'not stated'}"]
    if profile.subfield:
        lines.append(f"Subfield: {profile.subfield}")
    if profile.experience_level:
        lines.append(f"Experience level: {profile.experience_level}")
    if profile.target_roles:
        lines.append(f"Target roles: {', '.join(profile.target_roles)}")
    if profile.methods:
        lines.append(f"Methods: {', '.join(profile.methods)}")
    if profile.tools:
        lines.append(f"Tools: {', '.join(profile.tools)}")
    if profile.skills:
        lines.append(f"Skills: {', '.join(profile.skills)}")
    if profile.countries_preferred:
        lines.append("Countries preferred: "
                     + ", ".join(profile.countries_preferred))
    return "\n".join(lines)


def _opportunity_facts(opportunity: dict) -> str:
    """The key facts about an opportunity the LLM may reference."""
    lines = [
        f"Position title: {opportunity.get('title') or 'not stated'}",
        f"Institution: {opportunity.get('institution') or 'not stated'}",
        f"Country: {opportunity.get('country') or 'not stated'}",
        f"Deadline: {opportunity.get('deadline') or 'rolling'}",
        f"Funding: {opportunity.get('funding_status')
                    or opportunity.get('funding_requirement')
                    or 'check posting'}",
    ]
    desc = (opportunity.get("short_description") or "").strip()
    if desc:
        lines.append(f"Position description: {desc}")
    if opportunity.get("url"):
        lines.append(f"Posting URL: {opportunity['url']}")
    return "\n".join(lines)


def _grounding_rules() -> str:
    return (
        "GROUND RULES: Ground every sentence in the facts above. Do NOT "
        "invent skills, methods, publications, projects, supervisors or "
        "experience that are not present in the profile facts or the "
        "opportunity facts. If a fact is missing, omit that topic rather "
        "than fabricating it. Write plain prose, no markdown, no headings."
    )


def assistant_enabled() -> bool:
    """Feature toggle: ``ASSISTANT_ENABLED`` (default on)."""
    from core.llm import feature_enabled
    return feature_enabled("assistant")


def draft_cover_letter(profile: UserProfile, opportunity: dict,
                       tone: str = "professional",
                       length: str = "medium",
                       llm: Optional[LLMRouter] = None,
                       user_id: Optional[int] = None,
                       feature: str = "assistant.cover_letter") -> dict:
    """Generate a cover-letter draft from profile + opportunity facts.

    ``tone``: professional | warm | enthusiastic. ``length``: short |
    medium | long. Returns ``{"text", "model", "token_count"}``. The text is
    a DRAFT — the dashboard shows an editable copy and nothing is submitted.
    """
    tone = tone if tone in ("professional", "warm", "enthusiastic") \
        else "professional"
    length = length if length in ("short", "medium", "long") else "medium"
    length_hint = {"short": "~150 words", "medium": "~250 words",
                   "long": "~400 words"}[length]

    prompt = (
        "You are a careful application assistant for a researcher. Write a "
        f"cover letter for the position below, in a {tone} tone, "
        f"{length_hint}.\n\n"
        "PROFILE FACTS (only these are true):\n"
        f"{_profile_facts(profile)}\n\n"
        "OPPORTUNITY FACTS:\n"
        f"{_opportunity_facts(opportunity)}\n\n"
        "WHY THIS MATCH (deterministic analysis of the posting):\n"
        f"{opportunity.get('match_explanation') or 'no explanation provided'}\n\n"
        f"{_grounding_rules()}\n"
    )
    router = llm if llm is not None else _router()
    text = _truncate(router.complete(prompt, user_id=user_id, feature=feature))
    return {"text": text, "model": router.default_model,
            "token_count": _estimate_tokens(prompt) + _estimate_tokens(text)}


def draft_application_email(profile: UserProfile, opportunity: dict,
                            llm: Optional[LLMRouter] = None,
                            user_id: Optional[int] = None,
                            feature: str = "assistant.application_email") -> dict:
    """Draft a short email to send the PI / contact address.

    Returns ``{"text", "model", "token_count"}`` with a ~120-word draft.
    """
    prompt = (
        "You are a careful application assistant for a researcher. Write a "
        "SHORT, polite email (about 120 words) to the principal investigator "
        "about the position below.\n\n"
        "PROFILE FACTS (only these are true):\n"
        f"{_profile_facts(profile)}\n\n"
        "OPPORTUNITY FACTS:\n"
        f"{_opportunity_facts(opportunity)}\n\n"
        "WHY THIS MATCH (deterministic analysis of the posting):\n"
        f"{opportunity.get('match_explanation') or 'no explanation provided'}\n\n"
        f"{_grounding_rules()}\n"
        "Do not include a subject line; start directly with the greeting.\n"
    )
    router = llm if llm is not None else _router()
    text = _truncate(router.complete(prompt, user_id=user_id, feature=feature),
                     cap=250)
    return {"text": text, "model": router.default_model,
            "token_count": _estimate_tokens(prompt) + _estimate_tokens(text)}


def suggest_cv_improvements(profile: UserProfile,
                            gaps: Optional[list] = None,
                            llm: Optional[LLMRouter] = None,
                            user_id: Optional[int] = None,
                            feature: str = "assistant.cv_improvements") -> dict:
    """List skill/tool gaps from recent high-fit-but-failed matches.

    ``gaps`` is the deterministic list of profile methods/tools that recent
    strong matches did not advertise (computed by the caller from
    ``matching.missing_methods``). Returns ``{"improvements": [...],
    "model", "source"}`` where ``source`` is ``"llm"`` or ``"deterministic"``.
    Never raises — an LLM failure falls back to the deterministic wording.
    """
    gaps = [str(g) for g in (gaps or []) if str(g)][:5]
    fallback = [f"Consider adding '{g}' to your CV or coursework notes."
                for g in gaps] or [
        "Keep your profile's methods and tools current — no gaps were found "
        "in the latest scan."]

    if not gaps or (llm is None and not os.environ.get("LLM_API_KEY", "")):
        return {"improvements": fallback, "model": None, "source": "deterministic"}

    prompt = (
        "You are a career coach for a researcher. Based on the profile facts "
        "and the skill/tool gaps that recent strong matches did not "
        "advertise, write a short list of concrete CV improvement "
        "suggestions.\n\n"
        "PROFILE FACTS (only these are true):\n"
        f"{_profile_facts(profile)}\n\n"
        "DETECTED GAPS:\n"
        f"{', '.join(gaps)}\n\n"
        "Return a JSON object {\"improvements\": [\"suggestion\", ...]} with "
        "at most 5 short, actionable suggestions grounded only in the facts "
        "above.\n"
    )
    router = llm if llm is not None else _router()
    try:
        text = router.complete(prompt, user_id=user_id, feature=feature)
        from core.llm import extract_json_block
        parsed = extract_json_block(text)
        items = parsed.get("improvements", []) if isinstance(parsed, dict) \
            else []
        items = [str(i) for i in items if str(i)][:5]
        if not items:
            return {"improvements": fallback, "model": router.default_model,
                    "source": "deterministic"}
        return {"improvements": items, "model": router.default_model,
                "source": "llm"}
    except Exception as exc:
        log.warning("CV-improvement LLM failed (%s) — deterministic fallback",
                    exc)
        return {"improvements": fallback, "model": router.default_model,
                "source": "deterministic"}
