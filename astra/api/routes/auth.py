"""api.routes.auth — registration / login / refresh / current-user
(Sprint 04, Track C1) + password reset / email verification
(Sprint 07, Track B2).

Passwords are bcrypt-hashed on registration and verified on login; login
issues an HS256 JWT the client sends as ``Authorization: Bearer <token>``
(also set as an httpOnly cookie for browser clients). Registration and login
are rate-limited per client to blunt brute-force / spam attempts. Reset and
verification tokens are single-use, SHA-256-hashed in the DB, and issued
with an identical response whether or not the email exists (no enumeration).
"""

from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from api.deps import COOKIE_NAME, get_current_user, get_db
from api.routes.invites import invites_required, validate_invite_code
from api.schemas import (AccessRequest, AuthConfigOut, ForgotPasswordRequest,
                         GenericActionResponse, LoginRequest, RegisterRequest,
                         ResetPasswordRequest, TokenResponse, UserOut,
                         VerifyEmailRequest)
from api.security import (create_access_token, generate_secure_token,
                          hash_password, hash_token, log_audit, login_limiter,
                          register_limiter, reset_limiter, verify_limiter,
                          verify_password)
from db.models import PasswordReset, User
from db.repositories import (EmailVerificationRepo, InviteRepo,
                             PasswordResetRepo, UserRepo)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_RESET_TTL_HOURS = 24  # password-reset / verification tokens live 24 h

def _coerce_utc(value) -> datetime:
    """SQLite returns naive datetimes; treat naive as UTC so expiry checks
    compare like-for-like (aware)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _client_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:256]


def _link_for(path: str, token: str) -> str:
    """Frontend URL that surfaces the token to the user (dashboard app)."""
    from core.digest import dashboard_url
    return f"{dashboard_url()}{path}?token={token}"


def _issue_token(repo, user_id: int) -> tuple[str, PasswordReset]:
    """Create a hashed single-use token row; return (plaintext, row)."""
    token = generate_secure_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=_RESET_TTL_HOURS)
    row = repo.create(user_id=user_id, token_hash=hash_token(token),
                      expires_at=expires)
    return token, row


def _issue_token_discard() -> None:
    """Generate + hash a token and throw it away.

    Used by constant-work paths (e.g. ``forgot-password`` for unknown emails)
    so honest and dishonest lookups cost the same crypto + allocation work, and
    nothing is persisted. The SHA-256 hash mirrors what :func:`_issue_token`
    would store, so the branch timing is comparable."""
    token = generate_secure_token()
    hash_token(token)


def _send_verification_email(email: str, token: str) -> None:
    """Queue the verification email off the request path (never blocks)."""
    from core.tasks import enqueue_transactional_email
    link = _link_for("/verify-email", token)
    enqueue_transactional_email(
        to=email,
        subject="Verify your email — Astra",
        html=(
            "<p>Thanks for signing up. Confirm your address to finish "
            "registration:</p>"
            f"<p><a href='{link}'>{link}</a></p>"
            "<p>This link expires in 24 hours. Ignore it if you did not "
            "register.</p>"
        ),
    )


def _send_reset_email(email: str, token: str) -> None:
    """Queue the password-reset email off the request path (never blocks)."""
    from core.tasks import enqueue_transactional_email
    link = _link_for("/reset-password", token)
    enqueue_transactional_email(
        to=email,
        subject="Reset your password — Astra",
        html=(
            "<p>We received a request to reset your password:</p>"
            f"<p><a href='{link}'>{link}</a></p>"
            "<p>This link expires in 24 hours and can be used once. If you "
            "did not request it, you can ignore this email.</p>"
        ),
    )


def _cookie_secure() -> bool:
    """Whether session/CSRF cookies carry the ``Secure`` attribute.

    Defaults to True (required behind TLS). Set ``ASTRA_COOKIE_SECURE=0`` for
    plain-HTTP local development — browsers refuse to store Secure cookies on
    ``http://localhost`` origins, which silently breaks browser sessions."""
    from core.env import env_flag
    return env_flag("ASTRA_COOKIE_SECURE", default=True)


def _set_auth_cookie(response: Response, token: str) -> None:
    """Store the JWT as an httpOnly cookie (SameSite=Strict, Secure in TLS)."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="strict",
        secure=_cookie_secure(),
        max_age=60 * 60,
        path="/",
    )


def _set_csrf_cookie(response: Response) -> str:
    """Issue the double-submit CSRF token (Sprint 07, B3).

    Non-httpOnly so the dashboard's JS can read it and echo it back in the
    ``X-CSRF-Token`` header on mutating requests. SameSite=Strict + the header
    check gives defense-in-depth against cross-site request forgery.
    """
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        key="csrf_token",
        value=token,
        httponly=False,
        samesite="strict",
        secure=_cookie_secure(),
        max_age=60 * 60,
        path="/",
    )
    return token


def _rate_limit_headers(limiter, key: str) -> dict:
    """X-RateLimit-* headers describing the current window usage."""
    return {
        "X-RateLimit-Limit": str(limiter.max_requests),
        "X-RateLimit-Remaining": str(limiter.remaining(key)),
    }


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterRequest, request: Request, response: Response,
             session: Session = Depends(get_db)) -> UserOut:
    ip = _client_ip(request)
    if not register_limiter.check(ip):
        raise HTTPException(
            status_code=429,
            detail="Too many registration attempts — try again later",
            headers=_rate_limit_headers(register_limiter, ip))
    response.headers.update(_rate_limit_headers(register_limiter, ip))
    email = _normalize_email(body.email)
    if not _EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=422, detail="Invalid email address")
    if len(body.password) < 8:
        raise HTTPException(status_code=422,
                            detail="Password must be at least 8 characters")
    repo = UserRepo(session)
    if repo.get_by_email(email) is not None:
        raise HTTPException(status_code=409,
                            detail="Email already registered")

    # Private beta (Sprint 06, C1): when invites are required a valid, unused
    # invite code must accompany registration; otherwise the code is optional.
    invite = None
    if body.invite_code:
        invite = validate_invite_code(session, body.invite_code)
    elif invites_required():
        raise HTTPException(status_code=422,
                            detail="An invite code is required to register")

    user = repo.create(email, hash_password(body.password))
    if invite is not None:
        InviteRepo(session).redeem(invite, used_by=user.id)
        log_audit(session, action="invite.redeem", actor_type="user",
                  actor_id=user.id, target_type="invite",
                  target_id=invite.id, ip=ip,
                  user_agent=_client_agent(request))
    log_audit(session, action="auth.register", actor_type="user",
              actor_id=user.id, target_type="user", target_id=user.id,
              ip=ip, user_agent=_client_agent(request))
    session.commit()

    # Email verification (Sprint 07, B2) — dev mode logs the link instead.
    token, _ = _issue_token(EmailVerificationRepo(session), user.id)
    session.commit()
    _send_verification_email(email, token)
    return UserOut(user_id=user.id, email=email,
                   role=getattr(user, "role", "user") or "user")


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, response: Response,
          session: Session = Depends(get_db)) -> TokenResponse:
    ip = _client_ip(request)
    if not login_limiter.check(ip):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts — try again later",
            headers=_rate_limit_headers(login_limiter, ip))
    response.headers.update(_rate_limit_headers(login_limiter, ip))
    user = UserRepo(session).get_by_email(_normalize_email(body.email))
    if user is None or not verify_password(body.password, user.hashed_password):
        log_audit(session, action="auth.login_failed",
                  actor_type="user",
                  actor_id=user.id if user else None,
                  target_type="user", target_id=user.id if user else None,
                  ip=ip, user_agent=_client_agent(request))
        session.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    log_audit(session, action="auth.login", actor_type="user",
              actor_id=user.id, target_type="user", target_id=user.id,
              ip=ip, user_agent=_client_agent(request))
    session.commit()
    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    _set_csrf_cookie(response)
    return TokenResponse(access_token=token)


def access_code() -> str:
    """The shared entry code, or "" when that gate is switched off.

    **This is not a secret, and nothing may be built as though it were.** It
    ships inside a desktop binary that anyone can run `strings` on, so it is
    extractable in seconds and will circulate publicly. It exists so the front
    door asks for something rather than nothing. Never put data, a paid
    feature, or any real trust boundary behind it — the account system does
    that, and this sits in front of the account system, not instead of it.

    Read from the environment on every call, not captured at import, so it can
    be changed by setting ``ASTRA_ACCESS_CODE`` without rebuilding anything.
    Unset or empty means classic email + password registration, which is what
    a server deployment uses — so switching back later is one variable.
    """
    return (os.environ.get("ASTRA_ACCESS_CODE") or "").strip()


@router.get("/config", response_model=AuthConfigOut)
def auth_config() -> AuthConfigOut:
    """How to sign in here, so the frontend renders the right form.

    Asked rather than assumed: the same built frontend runs on the desktop
    (shared code) and on a server (email + password), and the platform is not
    what decides — the configuration is.
    """
    code = access_code()
    return AuthConfigOut(
        auth_mode="access_code" if code else "password",
        invite_required=invites_required(),
    )


@router.post("/access", response_model=TokenResponse)
def access(body: AccessRequest, request: Request, response: Response,
           session: Session = Depends(get_db)) -> TokenResponse:
    """Sign in with an email and the shared access code.

    Sits *in front of* the normal account system rather than replacing it: a
    real user row is created on first sight, so profiles, bookmarks and
    everything else keep working exactly as they do with a password.
    """
    configured = access_code()
    if not configured:
        # Not merely rejected — absent. A server deployment should not expose
        # a code endpoint at all.
        raise HTTPException(status_code=404,
                            detail="Access-code sign-in is not enabled here")

    ip = _client_ip(request)
    if not login_limiter.check(ip):
        raise HTTPException(
            status_code=429,
            detail="Too many attempts — try again later",
            headers=_rate_limit_headers(login_limiter, ip))
    response.headers.update(_rate_limit_headers(login_limiter, ip))

    email = _normalize_email(body.email)
    if not _EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=422, detail="Invalid email address")

    if not secrets.compare_digest(body.code.strip(), configured):
        log_audit(session, action="auth.access_failed", actor_type="user",
                  actor_id=None, target_type="user", target_id=None, ip=ip,
                  user_agent=_client_agent(request))
        session.commit()
        raise HTTPException(status_code=401, detail="That access code is not right")

    repo = UserRepo(session)
    user = repo.get_by_email(email)
    if user is None:
        # No password is stored for a code account, because the code is not a
        # password and must not quietly become one. A random hash nobody holds
        # the input for keeps /login closed for this row: the only way in is
        # the code endpoint, which is exactly as strong as the code.
        user = repo.create(email, hash_password(secrets.token_urlsafe(32)))
        log_audit(session, action="auth.access_register", actor_type="user",
                  actor_id=user.id, target_type="user", target_id=user.id,
                  ip=ip, user_agent=_client_agent(request))

    log_audit(session, action="auth.access", actor_type="user",
              actor_id=user.id, target_type="user", target_id=user.id,
              ip=ip, user_agent=_client_agent(request))
    session.commit()

    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    _set_csrf_cookie(response)
    return TokenResponse(access_token=token)


@router.post("/logout", response_model=GenericActionResponse)
def logout(response: Response) -> GenericActionResponse:
    """Drop the session cookies.

    There was no way to sign out at all before this — the session cookie is
    httpOnly, so the frontend cannot clear it itself and a user who entered the
    wrong email was stuck with it until the token expired.
    """
    response.delete_cookie(COOKIE_NAME, path="/")
    response.delete_cookie("csrf_token", path="/")
    return GenericActionResponse(status="ok")


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response,
            user: User = Depends(get_current_user)) -> TokenResponse:
    """Issue a fresh token with a new expiry for a still-valid session."""
    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(user_id=user.id, email=user.email,
                   role=getattr(user, "role", "user") or "user")


# ---------------------------------------------------------------------------
# Password reset + email verification (Sprint 07, Track B2)
# ---------------------------------------------------------------------------
@router.post("/forgot-password", response_model=GenericActionResponse)
def forgot_password(body: ForgotPasswordRequest, request: Request,
                    session: Session = Depends(get_db)) -> GenericActionResponse:
    """Issue a password-reset token and email a link.

    The response is identical whether or not the email exists so the endpoint
    cannot be used to enumerate registered addresses. No error is surfaced for
    unknown addresses.
    """
    ip = _client_ip(request)
    if not reset_limiter.check(ip):
        raise HTTPException(
            status_code=429,
            detail="Too many reset requests — try again later",
            headers=_rate_limit_headers(reset_limiter, ip))
    response = GenericActionResponse()
    email = _normalize_email(body.email)
    user = UserRepo(session).get_by_email(email)
    if user is not None:
        token, _ = _issue_token(PasswordResetRepo(session), user.id)
        log_audit(session, action="auth.forgot_password", actor_type="user",
                  actor_id=user.id, target_type="user", target_id=user.id,
                  ip=ip, user_agent=_client_agent(request))
        session.commit()
        _send_reset_email(email, token)
    else:
        # Constant-time-ish: an unknown address still pays the same token
        # generation + hashing cost (nothing is persisted, so there is no
        # enumeration signal in response time either).
        _issue_token_discard()
        log_audit(session, action="auth.forgot_password_unknown",
                  actor_type="system", ip=ip,
                  user_agent=_client_agent(request))
        session.commit()
    return response


@router.post("/reset-password", response_model=GenericActionResponse)
def reset_password(body: ResetPasswordRequest, request: Request,
                   session: Session = Depends(get_db)) -> GenericActionResponse:
    """Verify a reset token and rotate the password.

    Tokens are single-use (used_at set on success) and expire after 24 h.
    A used/expired/unknown token returns the same generic error.
    """
    repo = PasswordResetRepo(session)
    row = repo.get_by_hash(hash_token(body.token))
    now = datetime.now(timezone.utc)
    if (row is None or row.used_at is not None
            or _coerce_utc(row.expires_at) <= now):
        raise HTTPException(status_code=400,
                            detail="Invalid or expired reset token")
    user = UserRepo(session).get_by_id(row.user_id)
    if user is None:
        raise HTTPException(status_code=400,
                            detail="Invalid or expired reset token")
    repo.mark_used(row)
    UserRepo(session).set_password(user, hash_password(body.new_password))
    log_audit(session, action="auth.reset_password", actor_type="user",
              actor_id=user.id, target_type="user", target_id=user.id,
              ip=_client_ip(request), user_agent=_client_agent(request))
    session.commit()
    return GenericActionResponse()


@router.post("/verify-email", response_model=GenericActionResponse)
def verify_email(body: VerifyEmailRequest, request: Request,
                 session: Session = Depends(get_db)) -> GenericActionResponse:
    """Mark the user's email as verified using a single-use token."""
    repo = EmailVerificationRepo(session)
    row = repo.get_by_hash(hash_token(body.token))
    now = datetime.now(timezone.utc)
    if (row is None or row.used_at is not None
            or _coerce_utc(row.expires_at) <= now):
        raise HTTPException(status_code=400,
                            detail="Invalid or expired verification token")
    user = UserRepo(session).get_by_id(row.user_id)
    if user is None:
        raise HTTPException(status_code=400,
                            detail="Invalid or expired verification token")
    repo.mark_used(row)
    user.email_verified = True
    user.email_verified_at = now
    log_audit(session, action="auth.verify_email", actor_type="user",
              actor_id=user.id, target_type="user", target_id=user.id,
              ip=_client_ip(request), user_agent=_client_agent(request))
    session.commit()
    return GenericActionResponse()


@router.post("/resend-verification", response_model=GenericActionResponse)
def resend_verification(body: ForgotPasswordRequest, request: Request,
                        session: Session = Depends(get_db)) -> GenericActionResponse:
    """Re-issue a verification email (rate-limited, no enumeration).

    Response is identical whether or not the address exists; emails are only
    sent to real, unverified accounts.
    """
    ip = _client_ip(request)
    if not verify_limiter.check(ip):
        raise HTTPException(
            status_code=429,
            detail="Too many verification requests — try again later",
            headers=_rate_limit_headers(verify_limiter, ip))
    response = GenericActionResponse()
    email = _normalize_email(body.email)
    user = UserRepo(session).get_by_email(email)
    if user is not None and not user.email_verified:
        token, _ = _issue_token(EmailVerificationRepo(session), user.id)
        log_audit(session, action="auth.resend_verification",
                  actor_type="user", actor_id=user.id,
                  target_type="user", target_id=user.id,
                  ip=ip, user_agent=_client_agent(request))
        session.commit()
        _send_verification_email(email, token)
    return response
