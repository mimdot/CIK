"""db.models — SQLAlchemy 2.0 declarative models (migration Phase 3, Track C1).

Implements the 7 tables from specs/05_V1_Database_Schema.md:
user_profiles, opportunities, supervisors, matches, applications, bookmarks,
digest_preferences.

Conventions: declarative style, naive-UTC datetimes, JSON sub-fields stored
as TEXT (JSON-encoded) to stay faithful to the V1 data contracts, and
full-precision float scores (no rounding).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dumps(value) -> Optional[str]:
    """JSON-encode a list/dict column value; keep None as None."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# 0.0 users (Sprint 04, Track C1) — bcrypt-hashed passwords, never plaintext
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32), default="user")
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    marketing_consent: Mapped[Optional[bool]] = mapped_column(Boolean)
    consent_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    profiles: Mapped[list["UserProfileRow"]] = relationship(
        back_populates="user")


# ---------------------------------------------------------------------------
# 3.1 user_profiles
# ---------------------------------------------------------------------------
class UserProfileRow(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    domain: Mapped[Optional[str]] = mapped_column(Text)
    subfield: Mapped[Optional[str]] = mapped_column(Text)
    skills: Mapped[Optional[str]] = mapped_column(Text)           # JSON list
    methods: Mapped[Optional[str]] = mapped_column(Text)          # JSON list
    tools: Mapped[Optional[str]] = mapped_column(Text)            # JSON list
    target_roles: Mapped[Optional[str]] = mapped_column(Text)     # JSON list
    countries_preferred: Mapped[Optional[str]] = mapped_column(Text)  # JSON list
    funding_requirement: Mapped[Optional[str]] = mapped_column(Text)
    constraints: Mapped[Optional[str]] = mapped_column(Text)      # JSON list
    experience_level: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow,
                                                 onupdate=utcnow)

    matches: Mapped[list["Match"]] = relationship(
        back_populates="profile", foreign_keys="Match.profile_id")
    applications: Mapped[list["Application"]] = relationship(
        back_populates="profile")
    user: Mapped[Optional["User"]] = relationship(back_populates="profiles")

    @classmethod
    def from_profile(cls, profile: dict) -> "UserProfileRow":
        """Build a row from a plain dict (e.g. ``UserProfile.model_dump()``).
        The DB layer stays independent of core.profile_schema."""
        return cls(
            user_id=profile.get("user_id"),
            raw_text=profile.get("raw_text", ""),
            domain=profile.get("domain"),
            subfield=profile.get("subfield"),
            skills=_dumps(profile.get("skills")),
            methods=_dumps(profile.get("methods")),
            tools=_dumps(profile.get("tools")),
            target_roles=_dumps(profile.get("target_roles")),
            countries_preferred=_dumps(profile.get("countries_preferred")),
            funding_requirement=profile.get("funding_requirement"),
            constraints=_dumps(profile.get("constraints")),
            experience_level=profile.get("experience_level"),
            confidence=profile.get("confidence"),
        )

    def to_profile(self) -> dict:
        """Return the profile as a plain dict with the same shape Pydantic's
        UserProfile.model_dump() would produce."""
        return {
            "domain": self.domain or "",
            "subfield": self.subfield,
            "methods": json.loads(self.methods) if self.methods else [],
            "tools": json.loads(self.tools) if self.tools else [],
            "skills": json.loads(self.skills) if self.skills else [],
            "experience_level": self.experience_level or "other",
            "target_roles": json.loads(self.target_roles) if self.target_roles else [],
            "countries_preferred": (json.loads(self.countries_preferred)
                                    if self.countries_preferred else []),
            "funding_requirement": self.funding_requirement,
            "constraints": json.loads(self.constraints) if self.constraints else [],
            "confidence": self.confidence or 0.0,
            "raw_text": self.raw_text or "",
        }


# ---------------------------------------------------------------------------
# 3.2 opportunities
# ---------------------------------------------------------------------------
class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (UniqueConstraint("source", "source_raw", name="uq_source_raw"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    source_raw: Mapped[str] = mapped_column(String(512))          # upstream URL/id
    title: Mapped[str] = mapped_column(Text)
    institution: Mapped[Optional[str]] = mapped_column(Text)
    department: Mapped[Optional[str]] = mapped_column(Text)
    country: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    city: Mapped[Optional[str]] = mapped_column(String(128))
    url: Mapped[Optional[str]] = mapped_column(Text, index=True)
    type: Mapped[Optional[str]] = mapped_column(String(32))       # phd/postdoc/...
    field: Mapped[Optional[str]] = mapped_column(String(128))
    subfield: Mapped[Optional[str]] = mapped_column(String(128))
    topics: Mapped[Optional[str]] = mapped_column(Text)           # JSON list
    skills_required: Mapped[Optional[str]] = mapped_column(Text)  # JSON list
    methods_required: Mapped[Optional[str]] = mapped_column(Text) # JSON list
    funding_status: Mapped[Optional[str]] = mapped_column(String(64))
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime)
    posted_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    effective_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    age_days: Mapped[Optional[int]] = mapped_column(Integer)
    freshness: Mapped[Optional[str]] = mapped_column(String(32))
    relevance_score: Mapped[Optional[float]] = mapped_column(Float)
    matched_anchors: Mapped[Optional[str]] = mapped_column(Text)  # JSON list
    matched_keywords: Mapped[Optional[str]] = mapped_column(Text) # JSON list
    short_description: Mapped[Optional[str]] = mapped_column(Text)
    position_type: Mapped[Optional[str]] = mapped_column(String(32))
    is_new: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow,
                                                 onupdate=utcnow)

    matches: Mapped[list["Match"]] = relationship(
        back_populates="opportunity", foreign_keys="Match.opportunity_id")
    applications: Mapped[list["Application"]] = relationship(
        back_populates="opportunity")


# ---------------------------------------------------------------------------
# 3.3 supervisors
# ---------------------------------------------------------------------------
class Supervisor(Base):
    __tablename__ = "supervisors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[Optional[str]] = mapped_column(String(32))     # ads|openalex|arxiv
    name: Mapped[str] = mapped_column(String(256), index=True)
    institution: Mapped[Optional[str]] = mapped_column(Text)
    department: Mapped[Optional[str]] = mapped_column(Text)
    country: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    profile_url: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(String(256))
    topics: Mapped[Optional[str]] = mapped_column(Text)           # JSON list
    methods: Mapped[Optional[str]] = mapped_column(Text)          # JSON list
    recent_papers: Mapped[Optional[str]] = mapped_column(Text)    # JSON list
    fit_score: Mapped[Optional[float]] = mapped_column(Float)
    # How that 0-100 fit was arrived at, in plain words. A bare score is not
    # actionable; this is what a click on the number shows.
    fit_explanation: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow,
                                                 onupdate=utcnow)

    matches: Mapped[list["Match"]] = relationship(
        back_populates="supervisor", foreign_keys="Match.supervisor_id")


# ---------------------------------------------------------------------------
# 3.4 matches (polymorphic target: opportunity | supervisor)
# ---------------------------------------------------------------------------
class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("user_profiles.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(32))       # opportunity|supervisor
    opportunity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("opportunities.id"), nullable=True)
    supervisor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("supervisors.id"), nullable=True)
    overall_score: Mapped[Optional[float]] = mapped_column(Float)
    topic_score: Mapped[Optional[float]] = mapped_column(Float)
    method_score: Mapped[Optional[float]] = mapped_column(Float)
    skill_score: Mapped[Optional[float]] = mapped_column(Float)
    location_score: Mapped[Optional[float]] = mapped_column(Float)
    funding_score: Mapped[Optional[float]] = mapped_column(Float)
    competitiveness_score: Mapped[Optional[float]] = mapped_column(Float)
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    profile: Mapped["UserProfileRow"] = relationship(
        back_populates="matches", foreign_keys=[profile_id])
    opportunity: Mapped[Optional["Opportunity"]] = relationship(
        back_populates="matches", foreign_keys=[opportunity_id])
    supervisor: Mapped[Optional["Supervisor"]] = relationship(
        back_populates="matches", foreign_keys=[supervisor_id])


# ---------------------------------------------------------------------------
# 3.5 applications
# ---------------------------------------------------------------------------
class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("user_profiles.id"), index=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    cover_letter: Mapped[Optional[str]] = mapped_column(Text)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    outcome: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow,
                                                 onupdate=utcnow)

    profile: Mapped["UserProfileRow"] = relationship(back_populates="applications")
    opportunity: Mapped["Opportunity"] = relationship(back_populates="applications")


# ---------------------------------------------------------------------------
# 3.6 bookmarks
# ---------------------------------------------------------------------------
class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = (UniqueConstraint("profile_id", "opportunity_id",
                                       name="uq_bookmark_profile_opportunity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("user_profiles.id"), index=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# 3.7 digest_preferences
# ---------------------------------------------------------------------------
class DigestPreference(Base):
    __tablename__ = "digest_preferences"

    profile_id: Mapped[int] = mapped_column(
        ForeignKey("user_profiles.id"), primary_key=True)
    email: Mapped[Optional[str]] = mapped_column(String(256))
    frequency: Mapped[str] = mapped_column(String(16), default="weekly")
    include_matches: Mapped[int] = mapped_column(Integer, default=5)
    include_supervisors: Mapped[bool] = mapped_column(Boolean, default=False)
    quiet_days: Mapped[Optional[str]] = mapped_column(Text)       # JSON list
    timezone: Mapped[Optional[str]] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow,
                                                 onupdate=utcnow)


# ---------------------------------------------------------------------------
# 3.8 match_feedback (Sprint 04) — user feedback on a computed match
# ---------------------------------------------------------------------------
class MatchFeedback(Base):
    __tablename__ = "match_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True)
    match_id: Mapped[int] = mapped_column(Integer, index=True)
    target_type: Mapped[str] = mapped_column(String(32), default="opportunity")
    helpful: Mapped[Optional[bool]] = mapped_column(Boolean)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# 3.9 invites (Sprint 06, Track C1) — private-beta access codes
# ---------------------------------------------------------------------------
class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    used_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


# ---------------------------------------------------------------------------
# 3.10 email_events (Sprint 07, Track A1/A4) — transactional + digest sends
# ---------------------------------------------------------------------------
class EmailEvent(Base):
    __tablename__ = "email_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_to: Mapped[Optional[str]] = mapped_column(String(256))
    event_type: Mapped[str] = mapped_column(String(32))  # sent|bounced|complained|failed|unsubscribed
    subject: Mapped[Optional[str]] = mapped_column(String(256))
    provider_id: Mapped[Optional[str]] = mapped_column(String(128))  # Resend message id
    detail: Mapped[Optional[str]] = mapped_column(Text)              # JSON payload
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ---------------------------------------------------------------------------
# 3.11 password_resets (Sprint 07, Track B2) — SHA-256 hashed, single-use
# ---------------------------------------------------------------------------
class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# 3.12 email_verifications (Sprint 07, Track B2) — SHA-256 hashed, single-use
# ---------------------------------------------------------------------------
class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# 3.13 audit_events (Sprint 07, Track B4) — immutable action log
# ---------------------------------------------------------------------------
class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(16), default="user")
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"),
                                                   nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(32))
    target_id: Mapped[Optional[int]] = mapped_column(Integer)
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    user_agent: Mapped[Optional[str]] = mapped_column(String(256))
    meta: Mapped[Optional[str]] = mapped_column(Text)   # JSON payload
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow,
                                                 index=True)


# ---------------------------------------------------------------------------
# 3.14 api_keys (Sprint 08, Track A1) — SHA-256-hashed developer keys; the
# raw key is only ever returned once at creation time and never stored.
# scopes is a JSON list, e.g. ["read:matches", "write:bookmarks"].
# quota_limit (requests/day) and rate_limit (requests/minute) are optional
# overrides; NULL means "unlimited" / "platform default".
# ---------------------------------------------------------------------------
class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16))
    scopes: Mapped[Optional[str]] = mapped_column(Text)         # JSON list
    quota_limit: Mapped[Optional[int]] = mapped_column(Integer)
    rate_limit: Mapped[Optional[int]] = mapped_column(Integer)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# 3.15 api_key_usage (Sprint 08, Track B4) — nightly per-key/day request rollup
# ---------------------------------------------------------------------------
class ApiKeyUsage(Base):
    __tablename__ = "api_key_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), index=True)
    usage_date: Mapped[str] = mapped_column(String(10))          # YYYY-MM-DD
    requests: Mapped[int] = mapped_column(Integer, default=0)
    rate_limited: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow,
                                                 onupdate=utcnow)

    __table_args__ = (UniqueConstraint("key_id", "usage_date"),)


# ---------------------------------------------------------------------------
# 3.16 llm_usage (Sprint 09, Track C1) — per-call LLM accounting for the
# cost guard + admin dashboard. user_id is NULL for system-level calls
# (digest rewriting for a profile without an owner).
# ---------------------------------------------------------------------------
class LlmUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"),
                                                   nullable=True, index=True)
    feature: Mapped[str] = mapped_column(String(32), default="generic")
    model: Mapped[str] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow,
                                                 index=True)
