"""db.repositories — thin wrappers over SQLAlchemy sessions (migration Phase
3, Track C3). No business logic lives here; each method is a focused CRUD
operation. Construct with a Session; callers manage transactions via commit
on the session (the repos call flush/refresh only).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from db.models import (ApiKey, ApiKeyUsage, AuditEvent, Bookmark, EmailEvent,
                       EmailVerification, Invite, Match, MatchFeedback,
                       Opportunity, PasswordReset, Supervisor, User,
                       UserProfileRow)


# --- UserRepo (Sprint 04, Track C1) -------------------------------------------
class UserRepo:
    def __init__(self, session: Session):
        self.session = session

    def create(self, email: str, hashed_password: str,
               role: str = "user") -> User:
        user = User(email=email, hashed_password=hashed_password, role=role)
        self.session.add(user)
        self.session.flush()
        return user

    def get_by_email(self, email: str) -> Optional[User]:
        return self.session.scalar(
            select(User).where(User.email == email))

    def get_by_id(self, user_id: int) -> Optional[User]:
        return self.session.get(User, user_id)

    def count(self) -> int:
        from sqlalchemy import func
        return self.session.scalar(select(func.count()).select_from(User)) or 0

    def set_password(self, user: User, hashed_password: str) -> User:
        """Rotate a user's password hash (password reset flow)."""
        user.hashed_password = hashed_password
        self.session.flush()
        return user


# --- OpportunityRepo -----------------------------------------------------------
class OpportunityRepo:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, opp_id: int) -> Optional[Opportunity]:
        return self.session.get(Opportunity, opp_id)

    def get_by_url(self, url: str) -> Optional[Opportunity]:
        return self.session.scalar(
            select(Opportunity).where(Opportunity.url == url))

    def search(self, *, country: Optional[str] = None,
               source: Optional[str] = None,
               position_type: Optional[str] = None,
               text: Optional[str] = None,
               limit: int = 100) -> list[Opportunity]:
        stmt = select(Opportunity)
        if country:
            stmt = stmt.where(Opportunity.country == country)
        if source:
            stmt = stmt.where(Opportunity.source == source)
        if position_type:
            stmt = stmt.where(Opportunity.position_type == position_type)
        if text:
            safe = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{safe}%"
            stmt = stmt.where(Opportunity.title.like(like, escape="\\") |
                              Opportunity.short_description.like(like, escape="\\"))
        return list(self.session.scalars(stmt.limit(limit)))

    def upsert(self, row: Opportunity) -> Opportunity:
        """Insert or update by (source, source_raw). Returns the row."""
        existing = self.session.scalar(
            select(Opportunity).where(
                Opportunity.source == row.source,
                Opportunity.source_raw == row.source_raw))
        if existing is None:
            self.session.add(row)
            self.session.flush()
            return row
        for col in Opportunity.__table__.columns.keys():
            if col in ("id", "created_at"):
                continue
            new_val = getattr(row, col)
            if new_val is not None:
                setattr(existing, col, new_val)
        self.session.flush()
        return existing


# --- ProfileRepo ---------------------------------------------------------------
class ProfileRepo:
    def __init__(self, session: Session):
        self.session = session

    def create(self, profile: dict) -> UserProfileRow:
        """Create a row from a plain dict (e.g. UserProfile.model_dump())."""
        row = UserProfileRow.from_profile(profile)
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_id(self, profile_id: int) -> Optional[UserProfileRow]:
        return self.session.get(UserProfileRow, profile_id)

    def get_active(self, user_id: Optional[int] = None) -> Optional[UserProfileRow]:
        stmt = select(UserProfileRow).where(UserProfileRow.active.is_(True))
        if user_id is not None:
            stmt = stmt.where(UserProfileRow.user_id == user_id)
        return self.session.scalar(stmt)

    def update(self, profile_id: int, **fields) -> Optional[UserProfileRow]:
        """Update scalar columns by name. Returns the updated row (or None)."""
        row = self.session.get(UserProfileRow, profile_id)
        if row is None:
            return None
        allowed = {c.name for c in UserProfileRow.__table__.columns}
        for k, v in fields.items():
            if k in allowed and k not in ("id", "created_at", "updated_at"):
                setattr(row, k, v)
        self.session.flush()
        return row

    def deactivate_all(self, user_id: Optional[int] = None) -> None:
        stmt = update(UserProfileRow).values(active=False)
        if user_id is not None:
            stmt = stmt.where(UserProfileRow.user_id == user_id)
        self.session.execute(stmt)


# --- MatchRepo -----------------------------------------------------------------
class MatchRepo:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, profile_id: int, target_type: str,
               opportunity_id: Optional[int] = None,
               supervisor_id: Optional[int] = None,
               scores: Optional[dict] = None,
               explanation: Optional[str] = None,
               confidence: Optional[float] = None) -> Match:
        if target_type == "opportunity" and opportunity_id is None:
            raise ValueError("MatchRepo.upsert: target_type 'opportunity' "
                             "requires opportunity_id")
        if target_type == "supervisor" and supervisor_id is None:
            raise ValueError("MatchRepo.upsert: target_type 'supervisor' "
                             "requires supervisor_id")
        stmt = select(Match).where(Match.profile_id == profile_id,
                                   Match.target_type == target_type)
        if target_type == "opportunity":
            stmt = stmt.where(Match.opportunity_id == opportunity_id)
        else:
            stmt = stmt.where(Match.supervisor_id == supervisor_id)
        existing = self.session.scalar(stmt)
        if existing is None:
            m = Match(profile_id=profile_id, target_type=target_type,
                      opportunity_id=opportunity_id,
                      supervisor_id=supervisor_id,
                      explanation=explanation, confidence=confidence)
            if scores:
                for k, v in scores.items():
                    setattr(m, k, v)
            self.session.add(m)
            self.session.flush()
            return m
        if scores:
            for k, v in scores.items():
                setattr(existing, k, v)
        if explanation is not None:
            existing.explanation = explanation
        if confidence is not None:
            existing.confidence = confidence
        self.session.flush()
        return existing

    def get_by_profile(self, profile_id: int, limit: int = 100) -> list[Match]:
        return list(self.session.scalars(
            select(Match).where(Match.profile_id == profile_id)
            .order_by(Match.overall_score.desc().nulls_last()).limit(limit)))


# --- SupervisorRepo (Sprint 04) -------------------------------------------------
class SupervisorRepo:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, sup_id: int) -> Optional[Supervisor]:
        return self.session.get(Supervisor, sup_id)

    def search(self, *, country: Optional[str] = None,
               field: Optional[list[str]] = None,
               q: Optional[str] = None,
               limit: int = 100) -> list[Supervisor]:
        from sqlalchemy import func, or_

        stmt = select(Supervisor)
        if country:
            # Case-insensitive: "germany", "GERMANY" and "Germany" must all
            # return the same rows. The route already normalises the input to
            # its canonical name; this guards any casing drift in stored rows.
            stmt = stmt.where(
                func.lower(Supervisor.country) == country.strip().lower())
        if q:
            safe = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{safe}%"
            stmt = stmt.where(
                or_(Supervisor.name.ilike(like, escape="\\"),
                    Supervisor.department.ilike(like, escape="\\"),
                    Supervisor.topics.ilike(like, escape="\\")))
        if field:
            # Filter supervisors whose topics contain any of the field keywords
            conditions = []
            for keyword in field:
                safe = keyword.replace("\\", "\\\\").replace("%", "\\%")
                like = f"%{safe}%"
                conditions.append(Supervisor.topics.like(like, escape="\\"))
                conditions.append(Supervisor.department.like(like, escape="\\"))
            if conditions:
                stmt = stmt.where(or_(*conditions))
        return list(self.session.scalars(
            stmt.order_by(Supervisor.fit_score.desc().nulls_last()).limit(limit)))

    def upsert(self, data: dict) -> Supervisor:
        """Insert or update a supervisor by (name, country) dedup key.

        Keeps the highest fit_score; merges topics/methods/recent_papers
        from the new data when the incoming score is better.
        """
        name = data.get("name")
        country = data.get("country")
        if not name or not country:
            raise ValueError("Supervisor upsert requires name and country")

        existing = self.session.scalar(
            select(Supervisor).where(
                Supervisor.name == name, Supervisor.country == country))
        if existing is None:
            row = Supervisor(**data)
            self.session.add(row)
            self.session.flush()
            return row

        incoming_score = data.get("fit_score") or 0.0
        current_score = existing.fit_score or 0.0
        if incoming_score >= current_score:
            for k, v in data.items():
                if v is not None:
                    setattr(existing, k, v)
            self.session.flush()
        return existing


# --- BookmarkRepo (Sprint 04) ----------------------------------------------------
class BookmarkRepo:
    def __init__(self, session: Session):
        self.session = session

    def list_by_profile(self, profile_id: int) -> list[Bookmark]:
        return list(self.session.scalars(
            select(Bookmark).where(Bookmark.profile_id == profile_id)
            .order_by(Bookmark.created_at.desc())))

    def get(self, bookmark_id: int) -> Optional[Bookmark]:
        return self.session.get(Bookmark, bookmark_id)

    def create(self, profile_id: int, opportunity_id: int) -> Bookmark:
        row = Bookmark(profile_id=profile_id, opportunity_id=opportunity_id)
        self.session.add(row)
        self.session.flush()
        return row

    def delete(self, bookmark_id: int, profile_id: Optional[int] = None) -> bool:
        row = self.session.get(Bookmark, bookmark_id)
        if row is None:
            return False
        if profile_id is not None and row.profile_id != profile_id:
            return False
        self.session.delete(row)
        return True


# --- MatchFeedbackRepo (Sprint 04) ----------------------------------------------
class MatchFeedbackRepo:
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, user_id: Optional[int], match_id: int,
               target_type: str = "opportunity",
               helpful: Optional[bool] = None,
               comment: Optional[str] = None) -> MatchFeedback:
        row = MatchFeedback(user_id=user_id, match_id=match_id,
                            target_type=target_type, helpful=helpful,
                            comment=comment)
        self.session.add(row)
        self.session.flush()
        return row


# --- InviteRepo (Sprint 06, Track C1) -------------------------------------------
class InviteRepo:
    def __init__(self, session: Session):
        self.session = session

    def create(self, code: str, created_by: int) -> Invite:
        row = Invite(code=code, created_by=created_by)
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_code(self, code: str) -> Optional[Invite]:
        return self.session.scalar(
            select(Invite).where(Invite.code == code))

    def list_all(self) -> list[Invite]:
        return list(self.session.scalars(
            select(Invite).order_by(Invite.created_at.desc())))

    def redeem(self, invite: Invite, used_by: int) -> Invite:
        from datetime import datetime, timezone
        invite.used_by = used_by
        invite.used_at = datetime.now(timezone.utc)
        self.session.flush()
        return invite

    def count_unused(self) -> int:
        from sqlalchemy import func
        return self.session.scalar(
            select(func.count()).select_from(Invite).where(
                Invite.used_by.is_(None))) or 0


# --- EmailEventRepo (Sprint 07, Track A1/A4) -----------------------------------
class EmailEventRepo:
    def __init__(self, session: Session):
        self.session = session

    def record(self, *, email_to: str, event_type: str,
               subject: Optional[str] = None,
               provider_id: Optional[str] = None,
               detail: Optional[dict] = None) -> EmailEvent:
        """Persist one email lifecycle event (sent / bounced / complained /
        failed / unsubscribed). Callers commit the session."""
        import json
        row = EmailEvent(
            email_to=email_to,
            event_type=event_type,
            subject=subject,
            provider_id=provider_id,
            detail=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_recent(self, limit: int = 50) -> list[EmailEvent]:
        return list(self.session.scalars(
            select(EmailEvent).order_by(EmailEvent.created_at.desc())
            .limit(limit)))


# --- PasswordResetRepo (Sprint 07, Track B2) ------------------------------------
class PasswordResetRepo:
    def __init__(self, session: Session):
        self.session = session

    def create(self, user_id: int, token_hash: str,
               expires_at: datetime) -> PasswordReset:
        row = PasswordReset(user_id=user_id, token_hash=token_hash,
                            expires_at=expires_at)
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_hash(self, token_hash: str) -> Optional[PasswordReset]:
        return self.session.scalar(
            select(PasswordReset).where(PasswordReset.token_hash == token_hash))

    def mark_used(self, row: PasswordReset) -> PasswordReset:
        row.used_at = datetime.now(timezone.utc)
        self.session.flush()
        return row


# --- EmailVerificationRepo (Sprint 07, Track B2) --------------------------------
class EmailVerificationRepo:
    def __init__(self, session: Session):
        self.session = session

    def create(self, user_id: int, token_hash: str,
               expires_at: datetime) -> EmailVerification:
        row = EmailVerification(user_id=user_id, token_hash=token_hash,
                                expires_at=expires_at)
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_hash(self, token_hash: str) -> Optional[EmailVerification]:
        return self.session.scalar(
            select(EmailVerification).where(
                EmailVerification.token_hash == token_hash))

    def mark_used(self, row: EmailVerification) -> EmailVerification:
        row.used_at = datetime.now(timezone.utc)
        self.session.flush()
        return row


# --- AuditEventRepo (Sprint 07, Track B4) ---------------------------------------
class AuditEventRepo:
    def __init__(self, session: Session):
        self.session = session

    def record(self, *, actor_type: str, action: str,
               actor_id: Optional[int] = None,
               target_type: Optional[str] = None,
               target_id: Optional[int] = None,
               ip: Optional[str] = None,
               user_agent: Optional[str] = None,
               meta: Optional[dict] = None) -> AuditEvent:
        """Append an immutable audit row. Callers commit the session."""
        import json
        row = AuditEvent(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            user_agent=user_agent,
            meta=json.dumps(meta, ensure_ascii=False) if meta else None,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list(self, *, action: Optional[str] = None,
             actor_id: Optional[int] = None, page: int = 1,
             limit: int = 50) -> list[AuditEvent]:
        query = select(AuditEvent)
        if action:
            query = query.where(AuditEvent.action == action)
        if actor_id:
            query = query.where(AuditEvent.actor_id == actor_id)
        query = (query.order_by(AuditEvent.created_at.desc())
                 .offset((page - 1) * limit).limit(limit))
        return list(self.session.scalars(query))


# --- ApiKeyRepo (Sprint 08, Track A1) ----------------------------------------
# The repo only ever sees the SHA-256 hash of a key plus its display prefix;
# raw keys are generated, shown once, and never persisted or logged.
class ApiKeyRepo:
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, user_id: int, name: str, key_hash: str,
               key_prefix: str, scopes: Optional[list] = None,
               quota_limit: Optional[int] = None,
               rate_limit: Optional[int] = None,
               expires_at: Optional[datetime] = None) -> ApiKey:
        import json
        row = ApiKey(
            user_id=user_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes=json.dumps(scopes, ensure_ascii=False)
            if scopes is not None else None,
            quota_limit=quota_limit,
            rate_limit=rate_limit,
            expires_at=expires_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        return self.session.scalar(
            select(ApiKey).where(ApiKey.key_hash == key_hash))

    def get_by_id(self, key_id: int) -> Optional[ApiKey]:
        return self.session.get(ApiKey, key_id)

    def list_for_user(self, user_id: int) -> list[ApiKey]:
        return list(self.session.scalars(
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .order_by(ApiKey.created_at.desc())))

    def list_all(self, *, page: int = 1, limit: int = 50) -> list[ApiKey]:
        return list(self.session.scalars(
            select(ApiKey)
            .order_by(ApiKey.created_at.desc())
            .offset((page - 1) * limit).limit(limit)))

    def revoke(self, row: ApiKey) -> ApiKey:
        row.revoked_at = datetime.now(timezone.utc)
        self.session.flush()
        return row

    def set_limits(self, row: ApiKey, *, quota_limit: Optional[int],
                   rate_limit: Optional[int]) -> ApiKey:
        row.quota_limit = quota_limit
        row.rate_limit = rate_limit
        self.session.flush()
        return row

    def touch_last_used(self, row: ApiKey) -> ApiKey:
        row.last_used_at = datetime.now(timezone.utc)
        self.session.flush()
        return row


# --- ApiKeyUsageRepo (Sprint 08, Track B4) ------------------------------------
class ApiKeyUsageRepo:
    def __init__(self, session: Session):
        self.session = session

    def upsert_usage(self, key_id: int, usage_date: str,
                     requests: int, rate_limited: int = 0) -> ApiKeyUsage:
        """Accumulate a key's per-day counts, creating the row if needed."""
        row = self.session.scalar(
            select(ApiKeyUsage).where(
                ApiKeyUsage.key_id == key_id,
                ApiKeyUsage.usage_date == usage_date))
        if row is None:
            row = ApiKeyUsage(key_id=key_id, usage_date=usage_date,
                              requests=requests, rate_limited=rate_limited)
            self.session.add(row)
        else:
            row.requests += requests
            row.rate_limited += rate_limited
        self.session.flush()
        return row

    def get_usage(self, key_id: int, usage_date: str) -> Optional[ApiKeyUsage]:
        return self.session.scalar(
            select(ApiKeyUsage).where(
                ApiKeyUsage.key_id == key_id,
                ApiKeyUsage.usage_date == usage_date))

    def list_usage(self, key_id: int, *, limit: int = 30) -> list[ApiKeyUsage]:
        return list(self.session.scalars(
            select(ApiKeyUsage)
            .where(ApiKeyUsage.key_id == key_id)
            .order_by(ApiKeyUsage.usage_date.desc())
            .limit(limit)))
