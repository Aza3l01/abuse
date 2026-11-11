"""
api/routes/auth.py — All authentication endpoints.

Routes
------
POST   /auth/register
GET    /auth/validate-code
POST   /auth/verify-email
POST   /auth/resend-verification
POST   /auth/login
POST   /auth/login/mfa
POST   /auth/logout
POST   /auth/refresh
GET    /auth/me
POST   /auth/forgot-password
POST   /auth/reset-password
POST   /auth/change-password
POST   /auth/delete-account
POST   /auth/mfa/setup
POST   /auth/mfa/verify
POST   /auth/mfa/disable
POST   /auth/mfa/nudge-dismiss
GET    /auth/sessions
DELETE /auth/sessions/{session_id}
DELETE /auth/sessions
"""
import os
import hashlib
import hmac
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Optional

import redis as _redis_lib
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
from jose import JWTError as _JWTError, jwt as _jose_jwt
import pyotp
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth_utils import (
    JWT_ALGORITHM,
    JWT_SECRET,
    REFRESH_TOKEN_EXPIRE_DAYS,
    ahash_password,
    averify_password,
    clear_auth_cookies,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    decrypt_secret,
    encrypt_secret,
    generate_backup_codes,
    generate_otp,
    hash_token,
    send_login_lockout_email,
    send_mfa_enabled_email,
    send_password_changed_email,
    send_password_reset_email,
    send_verification_email,
    set_auth_cookies,
    set_last_org_cookie,
    verify_turnstile_token,
)
from api.deps import get_current_client, get_current_org, get_db
from api.limiter import limiter
from api.referrals import code_unavailable_reason
from api.routes.billing import cancel_org_subscriptions_for_deletion
from api.validation import check_password, clean_email, clean_text
from db.models import BillingEvent, Client, MfaBackupCode, Organization, OrganizationMember, PromoCode, RefreshToken

router = APIRouter()

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
DASHBOARD_URL         = os.environ.get("DASHBOARD_URL", "http://localhost:3000")
REDIS_URL            = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

_redis = _redis_lib.from_url(REDIS_URL, decode_responses=True)

_OTP_EXPIRE_SECONDS = 15 * 60  # 15 minutes


# ---------------------------------------------------------------------------
# Item 65: Redis backs every rate/lockout check below and was previously an
# unguarded hard dependency of login: a Redis outage turned every login
# into an unhandled 500. Posture chosen (written down here, not left
# implicit): fail CLOSED. Return a clear 503 rather than let a broken
# security control silently pass every request through with rate limiting
# and brute-force lockout disabled. Fail-open was considered and rejected,
# the limiter itself is Redis-backed too (item 58), so a Redis outage
# already means "auth is degraded," a 503 says so honestly instead of
# quietly serving unprotected logins.
# ---------------------------------------------------------------------------

def _fail_closed_on_redis_error(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _redis_lib.exceptions.RedisError:
            raise HTTPException(
                status_code=503,
                detail="Login is temporarily unavailable. Please try again shortly.",
            )
    return wrapper


# Phase 12b: shown when login or resend-verification is rejected for a bad or
# missing CAPTCHA token. The second sentence is for the real user whose
# script blocker stopped the widget from loading (no token was ever made).
_CAPTCHA_FAILED_DETAIL = (
    "CAPTCHA verification failed. Please try again. If the check does not "
    "appear, a script blocker or privacy extension may be stopping it: allow "
    "challenges.cloudflare.com for this site and reload the page."
)


# ---------------------------------------------------------------------------
# Email-based rate limiting helper (used where slowapi can't key on body)
# ---------------------------------------------------------------------------

@_fail_closed_on_redis_error
def _check_email_rate(email: str, limit: int, window: int, prefix: str) -> bool:
    """
    Increment a Redis counter for (prefix, email).
    Returns True if the request is within the limit, False if exceeded.
    Sets the TTL on first increment so the window resets automatically.
    """
    key = f"{prefix}:{email.strip().lower()}"
    count = _redis.incr(key)
    if count == 1:
        _redis.expire(key, window)
    return count <= limit


# ---------------------------------------------------------------------------
# Item 6 — login brute force lockout (failed attempts only, distinct from
# _check_email_rate's blanket per-request counter above)
# ---------------------------------------------------------------------------

_LOGIN_LOCKOUT_THRESHOLD = 5
_LOGIN_LOCKOUT_WINDOW    = 15 * 60  # 15 minutes


def _login_failure_key(email: str) -> str:
    return f"clew:login_fail:{hashlib.sha256(email.strip().lower().encode()).hexdigest()}"


@_fail_closed_on_redis_error
def _is_login_locked_out(email: str) -> bool:
    count = _redis.get(_login_failure_key(email))
    return count is not None and int(count) >= _LOGIN_LOCKOUT_THRESHOLD


@_fail_closed_on_redis_error
def _record_login_failure(email: str, account_exists: bool = True) -> None:
    """Increment the failed-attempt counter; on the attempt that trips the
    lockout, email the account owner.

    account_exists=False (email not registered) still counts toward the
    lockout — so failed-attempt timing can't be used to enumerate valid
    accounts — but never sends mail to an address that isn't a real account.
    """
    key = _login_failure_key(email)
    count = _redis.incr(key)
    if count == 1:
        _redis.expire(key, _LOGIN_LOCKOUT_WINDOW)
    if count == _LOGIN_LOCKOUT_THRESHOLD and account_exists:
        send_login_lockout_email(email)


@_fail_closed_on_redis_error
def _reset_login_failures(email: str) -> None:
    _redis.delete(_login_failure_key(email))


# ---------------------------------------------------------------------------
# Phase 14 (F-005): wrong-guess counter for the 6 digit email verification
# code. The fifth wrong guess burns the code (see verify_email).
# ---------------------------------------------------------------------------

_VERIFY_MAX_WRONG = 5


def _verify_failure_key(email: str) -> str:
    return f"clew:verify_fail:{hashlib.sha256(email.strip().lower().encode()).hexdigest()}"


@_fail_closed_on_redis_error
def _record_verify_failure(email: str) -> int:
    key = _verify_failure_key(email)
    count = _redis.incr(key)
    if count == 1:
        _redis.expire(key, _OTP_EXPIRE_SECONDS)
    return count


@_fail_closed_on_redis_error
def _reset_verify_failures(email: str) -> None:
    _redis.delete(_verify_failure_key(email))


# ---------------------------------------------------------------------------
# Phase 14 (F-007): a TOTP code and an MFA challenge token are single use.
#
# pyotp's verify(valid_window=2) accepts a code for about 2.5 minutes and
# remembers nothing, so one phished code could be replayed any number of
# times. The step a code belongs to is now claimed in Redis (SET NX), and so
# is the challenge token's jti once the challenge succeeds. Both fail closed
# on a Redis outage like every other check in this file. Backup codes were
# already single use.
# ---------------------------------------------------------------------------

_TOTP_STEP_SECONDS = 30
_TOTP_WINDOW = 2  # steps either side of now, same tolerance as before
_TOTP_CLAIM_TTL = (2 * _TOTP_WINDOW + 1) * _TOTP_STEP_SECONDS + 30
_MFA_CHALLENGE_MINUTES = 5


def _totp_step_for(secret: str, code: str) -> Optional[int]:
    """The 30 second step `code` is valid for (within the window), or None."""
    code = (code or "").strip()
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    current = int(time.time() // _TOTP_STEP_SECONDS)
    for step in range(current - _TOTP_WINDOW, current + _TOTP_WINDOW + 1):
        if hmac.compare_digest(totp.at(step * _TOTP_STEP_SECONDS), code):
            return step
    return None


@_fail_closed_on_redis_error
def _claim_once(key: str, ttl: int) -> bool:
    """True the first time `key` is claimed, False for every later attempt."""
    return bool(_redis.set(key, "1", nx=True, ex=ttl))


def _totp_accepted(client_id: str, secret: str, code: str) -> bool:
    """Valid code that has not been used before. Marks it used."""
    step = _totp_step_for(secret, code)
    if step is None:
        return False
    return _claim_once(f"clew:totp_used:{client_id}:{step}", _TOTP_CLAIM_TTL)


def _create_mfa_challenge(client_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=_MFA_CHALLENGE_MINUTES)
    return _jose_jwt.encode(
        {"sub": client_id, "exp": expire, "type": "mfa_challenge", "jti": str(uuid.uuid4())},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def _claim_mfa_challenge(jti: Optional[str]) -> bool:
    """Spend a challenge token. A token without a jti (issued before this
    change) is refused, the user just signs in again."""
    if not jti:
        return False
    return _claim_once(f"clew:mfa_challenge_used:{jti}", _MFA_CHALLENGE_MINUTES * 60 + 60)


# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------

class RegisterBody(BaseModel):
    email: str
    password: str
    full_name: str
    company_name: str
    # TODO.md priority item 5: dual-purpose, an admin pilot code or another
    # org's referral code, api/routes/org.py's create_organization() tells
    # them apart by PromoCode.kind.
    pilot_code: Optional[str] = None
    captcha_token: str
    tos_accepted: bool
    # Phase 12b: optional "how did you hear about us". Validated and trimmed
    # in api/routes/org.py's create_organization (unknown source is a 422).
    signup_source: Optional[str] = None
    signup_source_detail: Optional[str] = None


class VerifyEmailBody(BaseModel):
    email: str
    code: str


class ResendVerificationBody(BaseModel):
    email: str
    captcha_token: str = ""


class LoginBody(BaseModel):
    email: str
    password: str
    captcha_token: str = ""


class ForgotPasswordBody(BaseModel):
    email: str
    captcha_token: str


class ResetPasswordBody(BaseModel):
    email: str
    code: str
    new_password: str


class MfaVerifyBody(BaseModel):
    code: str


class MfaDisableBody(BaseModel):
    password: str


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


class DeleteAccountBody(BaseModel):
    confirmation: str


class MfaLoginBody(BaseModel):
    mfa_token: str
    code: str
    is_backup_code: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _store_refresh_token(
    db: Session,
    client_id: str,
    raw_token: str,
    request: Request,
) -> None:
    """Persist a hashed refresh token so it can be revoked individually."""
    expires = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    db.add(
        RefreshToken(
            client_id=client_id,
            token_hash=hash_token(raw_token),
            expires_at=expires,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
        )
    )
    db.commit()


def _resolve_org_for_login(
    db: Session, client_id: str, preferred_org_id: Optional[str],
) -> Optional[str]:
    """Pick which org_id goes into the new JWT.

    preferred_org_id (an explicit switch-org target, or the last_org_id
    cookie) wins if the client still belongs to it. Otherwise auto-select
    when the client belongs to exactly one org. Multi-org with no valid
    preference returns None — the frontend sends the user to /select-org.
    """
    memberships = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.client_id == client_id)
        .all()
    )
    if not memberships:
        return None
    if preferred_org_id and any(m.org_id == preferred_org_id for m in memberships):
        return preferred_org_id
    if len(memberships) == 1:
        return memberships[0].org_id
    return None


def _issue_tokens(
    response: Response,
    db: Session,
    client: Client,
    request: Request,
    org_id: Optional[str] = None,
) -> None:
    """Create an access+refresh token pair, persist the refresh hash, set cookies.

    org_id: an explicit org to select (e.g. POST /auth/switch-org, or the org
    just created at registration). If omitted, falls back to the
    last_org_id cookie, then to auto-select when there is exactly one org.
    """
    preferred = org_id or request.cookies.get("last_org_id")
    resolved_org_id = _resolve_org_for_login(db, client.id, preferred)
    extra = {"org_id": resolved_org_id} if resolved_org_id else None
    access_tok  = create_access_token(subject=client.id, extra=extra)
    refresh_tok = create_refresh_token(subject=client.id)
    _store_refresh_token(db, client.id, refresh_tok, request)
    set_auth_cookies(response, access_tok, refresh_tok)
    set_last_org_cookie(response, resolved_org_id)


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------

@router.post("/register", status_code=201)
@limiter.limit("5/hour")
async def register(
    request: Request,
    body: RegisterBody,
    db: Session = Depends(get_db),
):
    if not body.tos_accepted:
        raise HTTPException(status_code=400, detail="You must accept the Terms of Service and Privacy Policy.")

    # Phase 14 (F-002, F-003, F-004): checked before the CAPTCHA so a typo does
    # not spend a one-use Turnstile token. The email is trimmed and lower-cased
    # once here and used everywhere below.
    email = clean_email(body.email)
    full_name = clean_text(body.full_name, "Full name")
    company_name = clean_text(body.company_name, "Company name")
    check_password(body.password)

    remote_ip = request.client.host if request.client else None
    if not verify_turnstile_token(body.captcha_token, remote_ip):
        raise HTTPException(status_code=400, detail=_CAPTCHA_FAILED_DETAIL)

    existing = db.query(Client).filter(Client.email == email).first()
    if existing:
        # Generic message — don't confirm whether the email is registered.
        raise HTTPException(
            status_code=400,
            detail=(
                "We could not create that account. If you already have one, try "
                "signing in or resetting your password. Still stuck? Email "
                "support@clewsec.com."
            ),
        )

    otp = generate_otp()
    now = datetime.now(timezone.utc)
    client = Client(
        email=email,
        password_hash=await ahash_password(body.password),
        full_name=full_name,
        tos_accepted_at=now,
        email_verified=False,
        verify_token=await ahash_password(otp),  # bcrypt-hash the OTP before storage
        verify_token_expires_at=now + timedelta(seconds=_OTP_EXPIRE_SECONDS),
    )
    db.add(client)
    db.flush()  # populate client.id without committing yet
    # Item 63: shared with POST /org so the two org-creation entry points
    # can't diverge on tier/trial setup. Deferred import: api/routes/org.py
    # imports _issue_tokens from this module at its own module level, a
    # top-level import here would be circular.
    from api.routes.org import create_organization
    create_organization(
        db, company_name, client, body.pilot_code, remote_ip=remote_ip,
        signup_source=body.signup_source, signup_source_detail=body.signup_source_detail,
    )
    db.commit()

    send_verification_email(email, otp)
    return {"message": "Account created. Check your email for a verification code."}


# ---------------------------------------------------------------------------
# GET /auth/validate-code (Phase 12)
#
# Public, rate limited. The register form calls it on blur so a mistyped code
# is caught before the form is submitted, and a referral code can say what it
# gives. It reveals only whether a code is usable and its kind, never who
# owns it. Registration itself re-checks the code, this is advice only.
# ---------------------------------------------------------------------------

@router.get("/validate-code")
@limiter.limit("20/hour")
async def validate_code(
    request: Request,
    code: str = Query(..., min_length=1, max_length=50),
    db: Session = Depends(get_db),
):
    promo = db.query(PromoCode).filter(PromoCode.code == code.strip().upper()).first()
    if code_unavailable_reason(promo, db) is not None:
        return {"valid": False, "kind": None}
    return {"valid": True, "kind": promo.kind}


# ---------------------------------------------------------------------------
# POST /auth/verify-email
# ---------------------------------------------------------------------------

@router.post("/verify-email")
@limiter.limit("10/15minutes")  # per IP; the wrong-guess counter below is per account
async def verify_email(
    request: Request,
    response: Response,
    body: VerifyEmailBody,
    db: Session = Depends(get_db),
):
    email = body.email.strip().lower()
    client = db.query(Client).filter(Client.email == email).first()

    # Use a single generic error for all failure modes (token not found,
    # expired, wrong code) to prevent revealing account existence.
    _bad = HTTPException(status_code=400, detail="Invalid or expired code.")

    if not client or not client.verify_token or not client.verify_token_expires_at:
        raise _bad
    if client.verify_token_expires_at < datetime.now(timezone.utc):
        raise _bad
    if not await averify_password(body.code, client.verify_token):
        # Phase 14 (F-005): a 6 digit code can be guessed, so the fifth wrong
        # guess burns it. The real user taps Resend for a new one (that has its
        # own CAPTCHA and limit). Burning, not locking, means a stranger who
        # types someone else's address can cost them one resend, never a
        # lockout of the account.
        if _record_verify_failure(email) >= _VERIFY_MAX_WRONG:
            client.verify_token = None
            client.verify_token_expires_at = None
            db.commit()
            _reset_verify_failures(email)
        raise _bad

    _reset_verify_failures(email)
    client.email_verified          = True
    client.verify_token            = None
    client.verify_token_expires_at = None
    db.commit()

    _issue_tokens(response, db, client, request)
    return {"message": "Email verified. You are now logged in."}


# ---------------------------------------------------------------------------
# POST /auth/resend-verification
# ---------------------------------------------------------------------------

@router.post("/resend-verification")
@limiter.limit("10/hour")  # IP fallback; tighter email-based limit below
async def resend_verification(
    request: Request,
    body: ResendVerificationBody,
    db: Session = Depends(get_db),
):
    # Phase 12b: CAPTCHA first, before the per-email counter, so a bot
    # without a token cannot spend a real user's resend allowance.
    remote_ip = request.client.host if request.client else None
    if not verify_turnstile_token(body.captcha_token, remote_ip):
        raise HTTPException(status_code=400, detail=_CAPTCHA_FAILED_DETAIL)

    if not _check_email_rate(body.email, limit=3, window=3600, prefix="rl:resend"):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    # Always 200 — don't confirm whether the email is registered.
    client = db.query(Client).filter(Client.email == body.email.strip().lower()).first()
    if client and not client.email_verified:
        otp = generate_otp()
        now = datetime.now(timezone.utc)
        client.verify_token            = await ahash_password(otp)
        client.verify_token_expires_at = now + timedelta(seconds=_OTP_EXPIRE_SECONDS)
        db.commit()
        _reset_verify_failures(client.email)
        send_verification_email(client.email, otp)

    return {"message": "If that email is registered and unverified, a new code was sent."}


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

@router.post("/login")
@limiter.limit("10/15minutes")  # IP-based; email-based handled manually below
async def login(
    request: Request,
    response: Response,
    body: LoginBody,
    db: Session = Depends(get_db),
):
    # Phase 12b: CAPTCHA first. It runs before the per-email counter and the
    # failed-attempts lockout so a rejected token never counts as a failed
    # login and a bot cannot lock a real user out by hammering their email.
    remote_ip = request.client.host if request.client else None
    if not verify_turnstile_token(body.captcha_token, remote_ip):
        raise HTTPException(status_code=400, detail=_CAPTCHA_FAILED_DETAIL)

    # Tighter per-email limit (10/15 min) on top of the per-IP limit above.
    # Phase 14 (F-009): 10, not 5. It counts every attempt, successes too, and
    # at 5 it tripped together with the failed-attempt lockout below, so the
    # lockout message was never shown and a 6th good sign-in was refused. At 10
    # the 5-failure lockout always comes first.
    if not _check_email_rate(body.email, limit=10, window=900, prefix="rl:login"):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    # Item 6: failed-attempts lockout, distinct from the blanket counter above.
    if _is_login_locked_out(body.email):
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again in 15 minutes.",
        )

    client = db.query(Client).filter(
        Client.email == body.email.strip().lower(),
        Client.deleted_at.is_(None),
    ).first()

    # Generic error — never reveal which field is wrong or whether the account exists.
    _creds = HTTPException(status_code=401, detail="Invalid credentials.")

    if not client or not client.password_hash:
        _record_login_failure(body.email, account_exists=client is not None)
        raise _creds
    if not await averify_password(body.password, client.password_hash):
        _record_login_failure(body.email, account_exists=True)
        raise _creds

    _reset_login_failures(body.email)

    if not client.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Email not verified.",
            headers={"X-Error-Code": "EMAIL_NOT_VERIFIED"},
        )

    if client.mfa_enabled:
        # Return a short-lived challenge token so the frontend can present
        # the TOTP input and submit to POST /auth/login/mfa.
        return {"code": "MFA_REQUIRED", "mfa_token": _create_mfa_challenge(client.id)}

    _issue_tokens(response, db, client, request)
    return {"message": "Logged in."}


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------

@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if refresh_token:
        record = (
            db.query(RefreshToken)
            .filter(RefreshToken.token_hash == hash_token(refresh_token))
            .first()
        )
        if record:
            record.revoked = True
            db.commit()

    clear_auth_cookies(response)
    return {"message": "Logged out."}


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------

@router.post("/refresh")
@limiter.limit("30/minute")
async def refresh_tokens(
    request: Request,
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
):
    _expired = HTTPException(status_code=401, detail="Session expired. Please log in again.")

    if not refresh_token:
        clear_auth_cookies(response)
        raise _expired

    payload = decode_refresh_token(refresh_token)
    if not payload:
        clear_auth_cookies(response)
        raise _expired

    record = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token_hash == hash_token(refresh_token),
            RefreshToken.revoked == False,  # noqa: E712
        )
        .first()
    )
    if not record or record.expires_at < datetime.now(timezone.utc):
        clear_auth_cookies(response)
        raise _expired

    client = db.query(Client).filter(Client.id == payload["sub"]).first()
    if not client:
        clear_auth_cookies(response)
        raise _expired

    # Rotate: revoke the old token before issuing a new pair.
    record.revoked = True
    db.commit()

    _issue_tokens(response, db, client, request)
    return {"message": "Token refreshed."}


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------

@router.get("/me")
async def me(
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    memberships = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.client_id == client.id)
        .all()
    )
    org_ids = [m.org_id for m in memberships]
    orgs_by_id = {
        o.id: o for o in db.query(Organization).filter(Organization.id.in_(org_ids)).all()
    } if org_ids else {}

    orgs = [
        {
            "id":           m.org_id,
            "company_name": orgs_by_id[m.org_id].company_name if m.org_id in orgs_by_id else None,
            "role":         m.role,
        }
        for m in memberships
    ]

    return {
        "id":             client.id,
        "email":          client.email,
        "full_name":      client.full_name,
        "email_verified": client.email_verified,
        "mfa_enabled":    client.mfa_enabled,
        "mfa_nudge_dismissed_at": client.mfa_nudge_dismissed_at,
        "created_at":     client.created_at,
        "orgs":           orgs,
    }


# ---------------------------------------------------------------------------
# GET /auth/orgs — list the current client's organisations (for the switcher)
# ---------------------------------------------------------------------------

@router.get("/orgs")
async def list_orgs(
    request: Request,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    last_org_id = request.cookies.get("last_org_id")
    memberships = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.client_id == client.id)
        .all()
    )
    org_ids = [m.org_id for m in memberships]
    orgs_by_id = {
        o.id: o for o in db.query(Organization).filter(Organization.id.in_(org_ids)).all()
    } if org_ids else {}

    return [
        {
            "id":           m.org_id,
            "company_name": orgs_by_id[m.org_id].company_name if m.org_id in orgs_by_id else None,
            "role":         m.role,
            "active":       m.org_id == last_org_id,
        }
        for m in memberships
    ]


class SwitchOrgBody(BaseModel):
    # Phase 14 (F-008): typed as a UUID so a malformed id is a 422, not a 500
    # from comparing text to a UUID column.
    org_id: uuid.UUID


@router.post("/switch-org")
async def switch_org(
    body: SwitchOrgBody,
    request: Request,
    response: Response,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    org_id = str(body.org_id)
    membership = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.client_id == client.id,
            OrganizationMember.org_id == org_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="You are not a member of that organisation.")

    _issue_tokens(response, db, client, request, org_id=org_id)
    return {"message": "Switched organisation.", "org_id": org_id}


# ---------------------------------------------------------------------------
# POST /auth/forgot-password
# ---------------------------------------------------------------------------

@router.post("/forgot-password")
@limiter.limit("10/hour")  # IP; tighter per-email limit below
async def forgot_password(
    request: Request,
    body: ForgotPasswordBody,
    db: Session = Depends(get_db),
):
    remote_ip = request.client.host if request.client else None
    if not verify_turnstile_token(body.captcha_token, remote_ip):
        raise HTTPException(status_code=400, detail=_CAPTCHA_FAILED_DETAIL)

    if not _check_email_rate(body.email, limit=3, window=3600, prefix="rl:forgot"):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    # Always 200 — never confirm whether the email is registered.
    client = db.query(Client).filter(Client.email == body.email.strip().lower()).first()
    if client:
        otp = generate_otp()
        now = datetime.now(timezone.utc)
        client.reset_token_hash       = await ahash_password(otp)
        client.reset_token_expires_at = now + timedelta(seconds=_OTP_EXPIRE_SECONDS)
        db.commit()
        send_password_reset_email(client.email, otp)

    return {"message": "If that email is registered, a reset code was sent."}


# ---------------------------------------------------------------------------
# POST /auth/reset-password
# ---------------------------------------------------------------------------

@router.post("/reset-password")
@limiter.limit("10/15minutes")  # IP fallback; per-email handled below
async def reset_password(
    request: Request,
    response: Response,
    body: ResetPasswordBody,
    db: Session = Depends(get_db),
):
    if not _check_email_rate(body.email, limit=5, window=900, prefix="rl:reset"):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    # Phase 14 (F-002): the same 8 to 128 rule as change-password.
    check_password(body.new_password)

    _bad = HTTPException(status_code=400, detail="Invalid or expired code.")

    client = db.query(Client).filter(Client.email == body.email.strip().lower()).first()
    if not client or not client.reset_token_hash or not client.reset_token_expires_at:
        raise _bad
    if client.reset_token_expires_at < datetime.now(timezone.utc):
        raise _bad
    if not await averify_password(body.code, client.reset_token_hash):
        raise _bad

    client.password_hash          = await ahash_password(body.new_password)
    client.reset_token_hash       = None
    client.reset_token_expires_at = None
    db.commit()

    # Revoke ALL existing sessions — if an attacker triggered the reset,
    # any active session they have is now invalidated.
    db.query(RefreshToken).filter(
        RefreshToken.client_id == client.id
    ).update({"revoked": True})
    db.commit()

    send_password_changed_email(client.email)

    if client.mfa_enabled:
        # Controlling the mailbox is not the second factor: still require the
        # TOTP/backup-code challenge before issuing a session, same as /auth/login.
        return {"code": "MFA_REQUIRED", "mfa_token": _create_mfa_challenge(client.id)}

    _issue_tokens(response, db, client, request)
    return {"message": "Password reset. You are now logged in."}


# ---------------------------------------------------------------------------
# POST /auth/change-password: item 22's Settings > Security section
# ---------------------------------------------------------------------------

@router.post("/change-password")
async def change_password(
    body: ChangePasswordBody,
    request: Request,
    response: Response,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    if not client.password_hash:
        raise HTTPException(
            status_code=400,
            detail="This account has no password set.",
        )
    if not await averify_password(body.current_password, client.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters.")
    check_password(body.new_password)  # Phase 14 (F-002): adds the 128 character maximum

    client.password_hash = await ahash_password(body.new_password)
    db.commit()

    # Same precedent as /auth/reset-password (item 7a): revoke every other
    # active session so a stolen session token can't outlive the change.
    # Unlike reset-password (an anonymous OTP flow), this is an authenticated
    # in-session action, reissue a fresh pair so the current device isn't
    # logged out by its own password change.
    db.query(RefreshToken).filter(
        RefreshToken.client_id == client.id
    ).update({"revoked": True})
    db.commit()
    _issue_tokens(response, db, client, request)

    send_password_changed_email(client.email)
    # Phase 14 (F-011): a signed-in device keeps its 15 minute access token
    # until it expires, only its refresh stops working, so say that.
    return {"message": "Password changed. Other sessions are signed out and lose access within 15 minutes."}


# ---------------------------------------------------------------------------
# POST /auth/delete-account: item 40, DPDP Act right-to-erasure
#
# Soft-delete only: sets deleted_at + anonymizes the email so it can be
# re-registered. A daily Beat task (purge_deleted_accounts) hard-deletes
# rows where deleted_at is older than 30 days.
#
# If the client owns an organisation, that whole organisation (and every
# other member's access to it) is soft-deleted too. An owner who wants to
# keep the org going should use POST /org/members/{id}/transfer-ownership
# first (org.py); this endpoint itself never transfers ownership, it just
# takes whatever orgs the caller still owns at deletion time with it.
# ---------------------------------------------------------------------------

@router.post("/delete-account")
async def delete_account(
    body: DeleteAccountBody,
    response: Response,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    if body.confirmation != "DELETE":
        raise HTTPException(status_code=400, detail='Type "DELETE" to confirm.')

    now = datetime.now(timezone.utc)

    owned_orgs = (
        db.query(Organization)
        .join(OrganizationMember, OrganizationMember.org_id == Organization.id)
        .filter(
            OrganizationMember.client_id == client.id,
            OrganizationMember.role == "owner",
            Organization.deleted_at.is_(None),
        )
        .all()
    )
    for org in owned_orgs:
        cancel_org_subscriptions_for_deletion(org, db)
        # Phase 14: deletion is a billing history entry like any other tier
        # change. Metrics ignore the name (it is not a plan or churn event);
        # the row survives the 30 day purge with org_id NULL.
        db.add(BillingEvent(
            org_id=org.id,
            event="account_deleted",
            from_tier=org.tier,
            to_tier=None,
            period=org.billing_period,
            created_at=now,
        ))
        org.deleted_at = now

    # Phase 14 (F-036): leave every org they were only a member of, so the
    # owner's team list does not keep a "deleted-<id>@deleted.clew" row.
    db.query(OrganizationMember).filter(
        OrganizationMember.client_id == client.id,
        OrganizationMember.role != "owner",
    ).delete(synchronize_session=False)

    client.deleted_at = now
    client.email = f"deleted-{client.id}@deleted.clew"

    db.query(RefreshToken).filter(
        RefreshToken.client_id == client.id
    ).update({"revoked": True})
    db.commit()

    clear_auth_cookies(response)
    return {"message": "Account deleted."}


# ---------------------------------------------------------------------------
# POST /auth/login/mfa — complete the MFA challenge after /auth/login
# ---------------------------------------------------------------------------

@router.post("/login/mfa")
@limiter.limit("10/15minutes")
async def login_mfa(
    request: Request,
    response: Response,
    body: MfaLoginBody,
    db: Session = Depends(get_db),
):
    """Validate the short-lived MFA challenge token, then verify TOTP code or
    a single-use backup code."""
    _bad = HTTPException(status_code=401, detail="Invalid or expired MFA token.")

    try:
        payload = _jose_jwt.decode(body.mfa_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except _JWTError:
        raise _bad

    if payload.get("type") != "mfa_challenge":
        raise _bad

    client_id = payload.get("sub")
    if not client_id:
        raise _bad

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client or not client.mfa_enabled or not client.mfa_secret:
        raise _bad

    # Item 6: same lockout counter as /auth/login — this step still guards
    # a brute-forceable secret (TOTP/backup code).
    if _is_login_locked_out(client.email):
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again in 15 minutes.",
        )

    code = body.code.strip().upper()

    # Try TOTP first, then backup code. Phase 14 (F-007): a TOTP step that
    # was already used is refused, and the challenge token is spent once the
    # login succeeds, so neither can be replayed.
    totp_secret = decrypt_secret(client.mfa_secret)
    if _totp_accepted(client.id, totp_secret, code):
        if not _claim_mfa_challenge(payload.get("jti")):
            raise _bad
        _reset_login_failures(client.email)
        _issue_tokens(response, db, client, request)
        return {"message": "Logged in."}

    # Check backup codes (hashed, single-use)
    backup_code_hash = hash_token(code.replace("-", ""))
    backup = (
        db.query(MfaBackupCode)
        .filter(
            MfaBackupCode.client_id == client.id,
            MfaBackupCode.code_hash == backup_code_hash,
            MfaBackupCode.used      == False,  # noqa: E712
        )
        .first()
    )
    if backup:
        if not _claim_mfa_challenge(payload.get("jti")):
            raise _bad
        backup.used = True
        db.commit()
        _reset_login_failures(client.email)
        _issue_tokens(response, db, client, request)
        return {"message": "Logged in via backup code."}

    _record_login_failure(client.email)
    # Item 13: distinguish "wrong code" from "no codes left" only when the
    # user was explicitly on the backup-code path — TOTP typos shouldn't
    # trigger this message.
    if body.is_backup_code:
        remaining = (
            db.query(MfaBackupCode)
            .filter(
                MfaBackupCode.client_id == client.id,
                MfaBackupCode.used      == False,  # noqa: E712
            )
            .count()
        )
        if remaining == 0:
            raise HTTPException(
                status_code=400,
                detail="All recovery codes have been used. Disable and re-enable MFA from your security settings to generate new codes.",
            )
    raise HTTPException(status_code=401, detail="Invalid authenticator code.")


# ---------------------------------------------------------------------------
# POST /auth/mfa/setup — generate a new TOTP secret (does not enable MFA yet)
# ---------------------------------------------------------------------------

@router.post("/mfa/setup")
async def mfa_setup(
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Generate a new TOTP secret and return the provisioning URI for QR code.
    MFA is not activated until the client confirms via POST /mfa/verify."""
    if client.mfa_enabled:
        raise HTTPException(
            status_code=400,
            detail="MFA is already enabled. Disable it first to reset.",
        )

    secret = pyotp.random_base32()
    uri    = pyotp.totp.TOTP(secret).provisioning_uri(
        name=client.email, issuer_name="Clew"
    )
    # Store encrypted; plaintext is only returned here so the UI can show QR
    client.mfa_secret = encrypt_secret(secret)
    db.commit()
    return {"secret": secret, "uri": uri}


# ---------------------------------------------------------------------------
# POST /auth/mfa/verify — confirm the first TOTP code to activate MFA
# ---------------------------------------------------------------------------

@router.post("/mfa/verify")
@limiter.limit("10/15minutes")
async def mfa_verify(
    request: Request,
    body: MfaVerifyBody,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    if client.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled.")
    if not client.mfa_secret:
        raise HTTPException(status_code=400, detail="Run /mfa/setup first.")

    totp_secret = decrypt_secret(client.mfa_secret)
    if not _totp_accepted(client.id, totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid authenticator code.")

    # Generate 10 single-use backup codes; store hashes, return plaintext once
    raw_codes = generate_backup_codes(10)
    # Delete any stale pending codes (shouldn't exist, but defensive)
    db.query(MfaBackupCode).filter(MfaBackupCode.client_id == client.id).delete()
    for code in raw_codes:
        db.add(MfaBackupCode(
            client_id=client.id,
            # Normalise: strip dash before hashing so login comparison is consistent
            code_hash=hash_token(code.replace("-", "")),
        ))

    client.mfa_enabled = True
    db.commit()
    send_mfa_enabled_email(client.email, enabled=True)
    return {"message": "MFA enabled.", "backup_codes": raw_codes}


# ---------------------------------------------------------------------------
# POST /auth/mfa/disable — disable MFA (requires current password)
# ---------------------------------------------------------------------------

@router.post("/mfa/disable")
async def mfa_disable(
    body: MfaDisableBody,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    if not client.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled.")
    if not client.password_hash:
        # OAuth-only accounts have no password — they can disable MFA via
        # support if needed; this keeps the flow simple.
        raise HTTPException(
            status_code=400,
            detail="Password confirmation is required but this account has no password set.",
        )
    if not await averify_password(body.password, client.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    client.mfa_enabled = False
    client.mfa_secret  = None
    db.query(MfaBackupCode).filter(MfaBackupCode.client_id == client.id).delete()
    db.commit()
    send_mfa_enabled_email(client.email, enabled=False)
    return {"message": "MFA disabled."}


# ---------------------------------------------------------------------------
# POST /auth/mfa/nudge-dismiss — item 10 Step 3, dismiss the MFA setup banner
# ---------------------------------------------------------------------------

@router.post("/mfa/nudge-dismiss")
async def mfa_nudge_dismiss(
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    client.mfa_nudge_dismissed_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "Dismissed."}


# ---------------------------------------------------------------------------
# GET /auth/sessions — list active sessions for the current client
# ---------------------------------------------------------------------------

@router.get("/sessions")
async def list_sessions(
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    rows = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.client_id == client.id,
            RefreshToken.revoked   == False,  # noqa: E712
            RefreshToken.expires_at >  now,
        )
        .order_by(RefreshToken.issued_at.desc())
        .all()
    )
    return [
        {
            "id":         row.id,
            "user_agent": row.user_agent,
            "ip":         row.ip,
            "issued_at":  row.issued_at,
            "expires_at": row.expires_at,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# DELETE /auth/sessions/{session_id} — revoke a specific session
# ---------------------------------------------------------------------------

@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: uuid.UUID,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    row = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.id        == str(session_id),
            RefreshToken.client_id == client.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Session not found.")
    row.revoked = True
    db.commit()
    return {"message": "Session revoked."}


# ---------------------------------------------------------------------------
# DELETE /auth/sessions — revoke ALL sessions for the current client
# ---------------------------------------------------------------------------

@router.delete("/sessions")
async def revoke_all_sessions(
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    (
        db.query(RefreshToken)
        .filter(
            RefreshToken.client_id == client.id,
            RefreshToken.revoked   == False,  # noqa: E712
        )
        .update({"revoked": True})
    )
    db.commit()
    return {"message": "All sessions revoked."}
