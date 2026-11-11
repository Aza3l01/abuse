"""api/staff_auth.py: Phase 6 staff authentication for the internal ops panel.

Fully separate from customer auth: own table (staff_users), own cookie
(clew_staff), own JWT type and signing key, own dependency (require_staff) and
own Redis key prefixes, so a customer credential never works here and a staff
credential never works on a customer route (decode_access_token rejects any
token whose type is not "access").

Staff rows are created only by scripts/create_staff_user.py.
"""
import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

import pyotp
import redis as _redis_lib
from fastapi import Cookie, Depends, HTTPException, Request, Response
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from api.auth_utils import JWT_ALGORITHM, JWT_SECRET, _IS_PROD, hash_password, verify_password
from api.deps import get_db
from db.models import Organization, StaffAuditLog, StaffUser

STAFF_COOKIE = "clew_staff"
STAFF_TOKEN_TYPE = "staff_access"
STAFF_SESSION_MINUTES = 60
TOTP_STEP_SECONDS = 30

LOGIN_IP_LIMIT = 10
LOGIN_IP_WINDOW = 15 * 60
LOGIN_FAIL_LIMIT = 5
LOGIN_FAIL_WINDOW = 15 * 60

# A separate signing key derived from JWT_SECRET: even a bug in a type check
# could not make a customer token verify as a staff token or the reverse.
_STAFF_SECRET = hashlib.sha256(f"clew-staff:{JWT_SECRET}".encode()).hexdigest()

_redis = _redis_lib.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)

_dummy_hash: str | None = None


def _fail_closed_on_redis_error(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _redis_lib.exceptions.RedisError:
            raise HTTPException(503, "Staff login is temporarily unavailable.")
    return wrapper


def _fail_key(email: str, ip: str) -> str:
    # Phase 14: keyed on email AND source IP, so someone guessing from another
    # address cannot lock the real staff user out of their own login.
    ident = f"{email.lower()}|{ip}"
    return f"clew:staff_login_fail:{hashlib.sha256(ident.encode()).hexdigest()}"


@_fail_closed_on_redis_error
def ip_within_limit(ip: str) -> bool:
    """Count one login attempt from `ip`. False once the window's limit is passed."""
    key = f"clew:staff_login_ip:{ip}"
    count = _redis.incr(key)
    if count == 1:
        _redis.expire(key, LOGIN_IP_WINDOW)
    return count <= LOGIN_IP_LIMIT


@_fail_closed_on_redis_error
def is_locked_out(email: str, ip: str) -> bool:
    count = _redis.get(_fail_key(email, ip))
    return count is not None and int(count) >= LOGIN_FAIL_LIMIT


@_fail_closed_on_redis_error
def record_failure(email: str, ip: str) -> None:
    key = _fail_key(email, ip)
    count = _redis.incr(key)
    if count == 1:
        _redis.expire(key, LOGIN_FAIL_WINDOW)


@_fail_closed_on_redis_error
def reset_failures(email: str, ip: str) -> None:
    _redis.delete(_fail_key(email, ip))


def password_matches(staff: StaffUser | None, password: str) -> bool:
    """Verify a password. A missing account still costs one bcrypt check, so
    response time does not reveal which emails are staff."""
    global _dummy_hash
    if staff is None:
        if _dummy_hash is None:
            _dummy_hash = hash_password("clew-staff-dummy")
        verify_password(password, _dummy_hash)
        return False
    return verify_password(password, staff.password_hash)


def verify_totp(secret: str, code: str, last_step: int | None, now: float | None = None) -> int | None:
    """The time step `code` is valid for, or None. Accepts one step either
    side of now, and never a step at or before `last_step`, so a code cannot be
    used twice."""
    code = (code or "").strip()
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    current = int((time.time() if now is None else now) // TOTP_STEP_SECONDS)
    for step in (current - 1, current, current + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(totp.at(step * TOTP_STEP_SECONDS), code):
            return step
    return None


# ---------------------------------------------------------------------------
# Session token and cookie
# ---------------------------------------------------------------------------

def create_staff_token(staff_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=STAFF_SESSION_MINUTES)
    return jwt.encode(
        {"sub": staff_id, "exp": expire, "type": STAFF_TOKEN_TYPE},
        _STAFF_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_staff_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, _STAFF_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    return payload if payload.get("type") == STAFF_TOKEN_TYPE else None


def set_staff_cookie(response: Response, token: str) -> None:
    # Host-only (no Domain), strict same-site, absolute lifetime, no refresh.
    response.set_cookie(
        STAFF_COOKIE,
        token,
        max_age=STAFF_SESSION_MINUTES * 60,
        httponly=True,
        secure=_IS_PROD,
        samesite="strict",
        path="/",
    )


def clear_staff_cookie(response: Response) -> None:
    response.delete_cookie(STAFF_COOKIE, path="/")


def require_staff(
    clew_staff: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> StaffUser:
    """The staff dependency for every /internal route except login. Reads only
    the clew_staff cookie: the customer access_token is never consulted."""
    if not clew_staff:
        raise HTTPException(401, "Not authenticated")
    payload = decode_staff_token(clew_staff)
    if payload is None or not payload.get("sub"):
        raise HTTPException(401, "Invalid or expired session")
    staff = db.get(StaffUser, payload["sub"])
    if staff is None or not staff.is_active or not staff.totp_active:
        raise HTTPException(401, "Invalid or expired session")
    return staff


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host[:45]


def audit(
    db: Session,
    staff: StaffUser,
    action: str,
    *,
    org: Organization | None = None,
    reason: str | None = None,
    details: dict | None = None,
    request: Request | None = None,
) -> StaffAuditLog:
    """Add an audit row to the caller's transaction (no commit), so a write
    and its audit row are saved together or not at all."""
    row = StaffAuditLog(
        staff_id=staff.id,
        staff_email=staff.email,
        action=action,
        org_id=org.id if org is not None else None,
        org_name_snapshot=org.company_name if org is not None else None,
        reason=reason,
        details=details,
        ip=client_ip(request),
    )
    db.add(row)
    return row
