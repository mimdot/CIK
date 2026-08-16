"""api.schemas — Pydantic request/response models for the REST API (Sprint 04).

Kept separate from ``core.profile_schema`` so the API layer can evolve without
touching the extraction pipeline's models. List/json fields mirror the DB's
JSON-as-text encoding via the serializers in :mod:`api.serializers`.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Union

from pydantic import BaseModel, Field, field_validator

from api.scopes import ALL_SCOPES


# --- generic ------------------------------------------------------------------
class HealthOut(BaseModel):
    status: str
    version: str


# --- profile ------------------------------------------------------------------
class BuildProfileRequest(BaseModel):
    raw_text: str = Field(..., min_length=1,
                          description="CV / biography text to extract from")


class ExtractCvRequest(BaseModel):
    """Upload a CV file as base64 for local text extraction (Track 2B).

    Base64 in a JSON body (not multipart) keeps the upload dependency-free and
    the file bytes never touch a third party."""

    filename: str = Field(..., min_length=1,
                          description="original filename (used to pick a parser)")
    content_b64: str = Field(..., min_length=1,
                             description="base64-encoded file bytes")


class ExtractCvResponse(BaseModel):
    filename: str
    chars: int
    raw_text: str


class ProfileUpdate(BaseModel):
    """Optional fields accepted by PUT /api/profile."""

    domain: Optional[str] = None
    subfield: Optional[str] = None
    methods: Optional[list[str]] = None
    tools: Optional[list[str]] = None
    skills: Optional[list[str]] = None
    experience_level: Optional[str] = None
    target_roles: Optional[list[str]] = None
    countries_preferred: Optional[list[str]] = None
    funding_requirement: Optional[str] = None
    constraints: Optional[list[str]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


# --- auth ---------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=8)
    invite_code: Optional[str] = Field(
        None, description="Private-beta invite code (optional unless "
                           "INVITES_REQUIRED is set)")

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class AccessRequest(BaseModel):
    """Email + the shared entry code. Deliberately no password field.

    The code is not a password and must never be stored as one — see
    ``api.routes.auth.access_code`` for why it is not a secret at all.
    """

    email: str
    code: str


class AuthConfigOut(BaseModel):
    """How this deployment expects people to sign in.

    Lets one frontend serve both surfaces: the desktop build runs with a shared
    access code configured, a server deployment does not, and the sign-in form
    renders whichever the API reports instead of guessing from the platform.
    """

    auth_mode: str  # "access_code" | "password"
    invite_required: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    user_id: int
    email: str
    # Exposed so the dashboard can hide operator-only pages (Admin, API keys)
    # from ordinary users. The backend already returns 403 on those routes;
    # this stops them being advertised in the first place.
    role: str = "user"


# --- auth: password reset + email verification (Sprint 07, Track B2) ----------
class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        return v


class VerifyEmailRequest(BaseModel):
    token: str


class GenericActionResponse(BaseModel):
    status: str = "ok"


# --- opportunities / matches ---------------------------------------------------
class OpportunityFilters(BaseModel):
    country: Optional[str] = None
    source: Optional[str] = None
    type: Optional[str] = None
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)


class MatchFeedbackRequest(BaseModel):
    helpful: bool
    comment: Optional[str] = None


class MatchFeedbackV1(MatchFeedbackRequest):
    """Public-API feedback body: carries the target match/opportunity id."""

    match_id: int = Field(..., ge=1)


class BookmarkCreate(BaseModel):
    opportunity_id: int


# --- pipeline ------------------------------------------------------------------
class PipelineRunRequest(BaseModel):
    sources: Optional[list[str]] = None
    country: Optional[str] = None
    field: Optional[str] = Field(
        None, description="field profile to crawl and score under (e.g. "
                          "astronomy, biology); omit for the server default")
    subfields: Optional[list[str]] = Field(
        None, description="subfield ids within the field (e.g. organic, "
                          "catalysis). Their keywords BOOST matching "
                          "positions rather than hard-filtering them — job "
                          "ads are short and often omit subfield vocabulary.")
    include_slow: bool = Field(
        False, description="also run the opt-in slow sources (the university "
                           "department sweep). Adds minutes to a run; off by "
                           "default.")
    position_types: Optional[list[str]] = Field(
        None, description="which kinds of position to hunt, e.g. [\"phd\"] or "
                          "[\"postdoc\"]. PhD and Postdoc are separate "
                          "searches with their own results; omit for the "
                          "server default.")


class SupervisorRunRequest(BaseModel):
    """Trigger a supervisor search for one or more countries, optionally
    restricted to a field profile and its subfields."""
    country: Union[str, list[str]]
    field: Optional[str] = None
    subfields: Optional[list[str]] = Field(
        None, description="subfield ids to focus on. Unlike position search "
                          "these are a real topic filter — publication data "
                          "is rich enough to support one.")
    limit: Optional[int] = Field(
        None, ge=10, le=500,
        description="how many candidates to consider per field+country. The "
                    "old hard-wired 25 was far too tight; the default is now "
                    "100. Higher means slower.")


class PipelineRunOut(BaseModel):
    status: str
    run_id: str


class PipelineStatusOut(BaseModel):
    run_id: str
    status: str
    records: Optional[int] = None
    error: Optional[str] = None


# --- API keys (Sprint 08, Track A2) -------------------------------------------
class ApiKeyCreate(BaseModel):
    """Create a developer API key. ``scopes`` defaults to the read scope set
    when omitted; ``admin`` is never grantable here (admin-only role gate)."""

    name: str = Field(..., min_length=1, max_length=64)
    scopes: Optional[list[str]] = None
    expires_at: Optional[datetime] = None

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        unknown = [s for s in v if s not in ALL_SCOPES or s == "admin"]
        if unknown:
            raise ValueError(
                f"Invalid scopes for a user key: {unknown}. Allowed: "
                f"{', '.join(ALL_SCOPES)}")
        return v

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v is not None and v <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return v


class ApiKeyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    scopes: Optional[list[str]] = None

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        unknown = [s for s in v if s not in ALL_SCOPES or s == "admin"]
        if unknown:
            raise ValueError(
                f"Invalid scopes for a user key: {unknown}. Allowed: "
                f"{', '.join(ALL_SCOPES)}")
        return v


class ApiKeyOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    scopes: list[str]
    quota_limit: Optional[int] = None
    rate_limit: Optional[int] = None
    last_used_at: Optional[str] = None
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    created_at: str


class ApiKeyCreateOut(ApiKeyOut):
    """The one and only response that carries the raw key."""

    raw_key: str


class ApiKeyUsageOut(BaseModel):
    date: str
    requests: int
    rate_limited: int


class ApiKeyQuotaOverride(BaseModel):
    """Admin-only: override a key's per-day quota and/or per-minute rate."""

    quota_limit: Optional[int] = Field(None, ge=1)
    rate_limit: Optional[int] = Field(None, ge=1)


# --- assistant (Sprint 09, Track A2) ------------------------------------------
class CoverLetterRequest(BaseModel):
    opportunity_id: int = Field(..., ge=1)
    tone: Optional[str] = None        # professional | warm | enthusiastic
    length: Optional[str] = None      # short | medium | long


class ApplicationEmailRequest(BaseModel):
    opportunity_id: int = Field(..., ge=1)


class AssistantUsageOut(BaseModel):
    limit: int
    used: int
    remaining: int
