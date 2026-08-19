"""core.profile_schema — the UserProfile Pydantic model (migration Phase 2,
Track B2). Extracted from the SPRINT_02.md spec.

This is the validated, structured shape that the LLM extraction produces from
a CV/bio, and the shape that db/models.py maps onto user_profiles. Every list
field defaults to [] and unknown scalar fields default to None so a partially
populated LLM response never breaks validation.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# Valid values for experience_level — kept open so future levels don't
# require a migration, but documented here for the extraction prompt.
EXPERIENCE_LEVELS = ("phd_student", "postdoc", "faculty", "industry", "other")


class UserProfile(BaseModel):
    domain: str
    subfield: Optional[str] = None
    methods: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience_level: str = "other"
    target_roles: list[str] = Field(default_factory=list)
    countries_preferred: list[str] = Field(default_factory=list)
    funding_requirement: Optional[str] = None
    constraints: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_text: str = ""

    # ---- convenience accessors -------------------------------------------------
    def to_db_columns(self) -> dict:
        """Map onto the user_profiles table's JSON-as-text columns (Track C)."""
        return {
            "domain": self.domain,
            "subfield": self.subfield,
            "skills": self.skills,
            "methods": self.methods,
            "tools": self.tools,
            "target_roles": self.target_roles,
            "countries_preferred": self.countries_preferred,
            "funding_requirement": self.funding_requirement,
            "constraints": self.constraints,
            "experience_level": self.experience_level,
            "confidence": self.confidence,
            "raw_text": self.raw_text,
        }
