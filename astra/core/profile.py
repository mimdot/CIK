"""core.profile — extract a structured UserProfile from CV/bio text using an
LLM (migration Phase 2, Track B3).

``extract_profile`` builds the schema-instructed prompt, calls the
LLMRouter, parses the JSON answer, validates it with Pydantic and retries
once on failure. The LLM is passed in so tests can substitute a stub.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.llm import LLMRouter, extract_json_block
from core.profile_schema import UserProfile

log = logging.getLogger("astra")

PROMPT = """You are a astra assistant. Convert the candidate's CV
or biography below into a JSON object that conforms EXACTLY to this JSON
schema:

{schema}

Rules:
- "domain" is required; set it to the broad research area (e.g. "astronomy").
- "methods"/"tools"/"skills" are lists of short lowercase strings.
- "experience_level" must be one of: phd_student, postdoc, faculty, industry,
  other.
- "countries_preferred" should list ISO country names when mentioned.
- "confidence" must be a float 0-1 reflecting how confident you are.
- Use null / empty lists for anything not mentioned. Do NOT invent facts.
- Return ONLY the JSON object, no prose.

=== CV/BIO ===
{raw_text}
=== END ==="""


def build_prompt(raw_text: str, schema: dict) -> str:
    import json as _json
    return PROMPT.format(schema=_json.dumps(schema, indent=2), raw_text=raw_text)


def extract_profile(raw_text: str, llm: LLMRouter,
                    max_attempts: int = 2) -> Optional[UserProfile]:
    """Extract a validated UserProfile. Returns None if the LLM output never
    parses/validates. The caller decides whether None is fatal."""
    schema = UserProfile.model_json_schema()
    prompt = build_prompt(raw_text, schema)

    last_error: Optional[str] = None
    for attempt in range(1, max_attempts + 1):
        try:
            text = llm.complete(prompt, schema=schema)
            data = extract_json_block(text)
            profile = UserProfile.model_validate(data)
            if not profile.raw_text:
                profile.raw_text = raw_text
            log.debug("profile extracted on attempt %d (confidence=%s)",
                      attempt, profile.confidence)
            return profile
        except Exception as exc:
            last_error = str(exc)
            log.warning("profile extraction attempt %d failed: %s",
                        attempt, last_error)
    log.error("could not extract a valid profile from the LLM output: %s",
              last_error)
    return None
