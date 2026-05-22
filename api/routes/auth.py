"""
api/routes/auth.py — All authentication endpoints.

Routes
------
POST   /auth/register
POST   /auth/verify-email
POST   /auth/resend-verification
POST   /auth/login
POST   /auth/login/mfa
POST   /auth/logout
POST   /auth/refresh
GET    /auth/me
POST   /auth/forgot-password
POST   /auth/reset-password
POST   /auth/mfa/setup
POST   /auth/mfa/verify
POST   /auth/mfa/disable
GET    /auth/sessions
DELETE /auth/sessions/{session_id}
DELETE /auth/sessions
GET    /auth/google
GET    /auth/google/callback
GET    /auth/github
GET    /auth/github/callback
GET    /auth/microsoft
GET    /auth/microsoft/callback
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
import redis as _redis_lib
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from jose import JWTError as _JWTError, jwt as _jose_jwt
import pyotp
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth_utils import (
    JWT_ALGORITHM,
    JWT_SECRET,
    REFRESH_TOKEN_EXPIRE_DAYS,
    clear_auth_cookies,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_backup_codes,
    generate_otp,
    hash_password,
    hash_token,
    send_mfa_enabled_email,
    send_oauth_linked_email,
    send_password_changed_email,
    send_password_reset_email,
    send_verification_email,
    set_auth_cookies,
    verify_password,
)
from api.deps import get_current_client, get_db
from api.limiter import limiter
from db.models import Client, MfaBackupCode, OAuthAccount, RefreshToken

router = APIRouter()

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.environ.get("GOOGLE_REDIRECT_URI", "")
GITHUB_CLIENT_ID     = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI  = os.environ.get("GITHUB_REDIRECT_URI", "")
MICROSOFT_CLIENT_ID     = os.environ.get("MICROSOFT_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET", "")
MICROSOFT_REDIRECT_URI  = os.environ.get("MICROSOFT_REDIRECT_URI", "")
FRONTEND_URL         = os.environ.get("FRONTEND_URL", "http://localhost:3000")
REDIS_URL            = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

_redis = _redis_lib.from_url(REDIS_URL, decode_responses=True)

_OTP_EXPIRE_SECONDS = 15 * 60  # 15 minutes


# ---------------------------------------------------------------------------
# Email-based rate limiting helper (used where slowapi can't key on body)
# ---------------------------------------------------------------------------

def _check_email_rate(email: str, limit: int, window: int, prefix: str) -> bool:
    """
    Increment a Redis counter for (prefix, email).
    Returns True if the request is within the limit, False if exceeded.
    Sets the TTL on first increment so the window resets automatically.
    """
    key = f"{prefix}:{email.lower()}"
    count = _redis.incr(key)
    if count == 1:
        _redis.expire(key, window)
    return count <= limit


# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------

class RegisterBody(BaseModel):
    email: str
    password: str
    company_name: str


class VerifyEmailBody(BaseModel):
    email: str
    code: str


class ResendVerificationBody(BaseModel):
    email: str


class LoginBody(BaseModel):
    email: str
    password: str


class ForgotPasswordBody(BaseModel):
    email: str


class ResetPasswordBody(BaseModel):
    email: str
    code: str
    new_password: str


class MfaVerifyBody(BaseModel):
    code: str


class MfaDisableBody(BaseModel):
    password: str


class MfaLoginBody(BaseModel):
    mfa_token: str
    code: str


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


def _issue_tokens(
    response: Response,
    db: Session,
    client: Client,
    request: Request,
) -> None:
    """Create an access+refresh token pair, persist the refresh hash, set cookies."""
    access_tok  = create_access_token(subject=client.id)
    refresh_tok = create_refresh_token(subject=client.id)
    _store_refresh_token(db, client.id, refresh_tok, request)
    set_auth_cookies(response, access_tok, refresh_tok)


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
    existing = db.query(Client).filter(Client.email == body.email.lower()).first()
    if existing:
        # Generic message — don't confirm whether the email is registered.
        raise HTTPException(
            status_code=400,
            detail="Registration failed. Please check your details.",
        )

    otp = generate_otp()
    now = datetime.now(timezone.utc)
    client = Client(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        company_name=body.company_name,
        email_verified=False,
        verify_token=hash_password(otp),  # bcrypt-hash the OTP before storage
        verify_token_expires_at=now + timedelta(seconds=_OTP_EXPIRE_SECONDS),
    )
    db.add(client)
    db.commit()

    send_verification_email(body.email.lower(), otp)
    return {"message": "Account created. Check your email for a verification code."}


# ---------------------------------------------------------------------------
# POST /auth/verify-email
# ---------------------------------------------------------------------------

@router.post("/verify-email")
async def verify_email(
    request: Request,
    response: Response,
    body: VerifyEmailBody,
    db: Session = Depends(get_db),
):
    client = db.query(Client).filter(Client.email == body.email.lower()).first()

    # Use a single generic error for all failure modes (token not found,
    # expired, wrong code) to prevent revealing account existence.
    _bad = HTTPException(status_code=400, detail="Invalid or expired code.")

    if not client or not client.verify_token or not client.verify_token_expires_at:
        raise _bad
    if client.verify_token_expires_at < datetime.now(timezone.utc):
        raise _bad
    if not verify_password(body.code, client.verify_token):
        raise _bad

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
    if not _check_email_rate(body.email, limit=3, window=3600, prefix="rl:resend"):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    # Always 200 — don't confirm whether the email is registered.
    client = db.query(Client).filter(Client.email == body.email.lower()).first()
    if client and not client.email_verified:
        otp = generate_otp()
        now = datetime.now(timezone.utc)
        client.verify_token            = hash_password(otp)
        client.verify_token_expires_at = now + timedelta(seconds=_OTP_EXPIRE_SECONDS)
        db.commit()
        send_verification_email(body.email.lower(), otp)

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
    # Tighter per-email limit (5/15 min) on top of the per-IP limit above.
    if not _check_email_rate(body.email, limit=5, window=900, prefix="rl:login"):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    client = db.query(Client).filter(Client.email == body.email.lower()).first()

    # Generic error — never reveal which field is wrong or whether the account exists.
    _creds = HTTPException(status_code=401, detail="Invalid credentials.")

    if not client or not client.password_hash:
        raise _creds
    if not verify_password(body.password, client.password_hash):
        raise _creds

    if not client.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Email not verified.",
            headers={"X-Error-Code": "EMAIL_NOT_VERIFIED"},
        )

    if client.mfa_enabled:
        # Return a short-lived challenge token so the frontend can present
        # the TOTP input and submit to POST /auth/login/mfa.
        expire = datetime.now(timezone.utc) + timedelta(minutes=5)
        mfa_token = _jose_jwt.encode(
            {"sub": client.id, "exp": expire, "type": "mfa_challenge"},
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        return {"code": "MFA_REQUIRED", "mfa_token": mfa_token}

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
async def me(client: Client = Depends(get_current_client)):
    return {
        "id":             client.id,
        "email":          client.email,
        "company_name":   client.company_name,
        "email_verified": client.email_verified,
        "mfa_enabled":    client.mfa_enabled,
        "tier":           client.tier,
        "created_at":     client.created_at,
    }


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
    if not _check_email_rate(body.email, limit=3, window=3600, prefix="rl:forgot"):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    # Always 200 — never confirm whether the email is registered.
    client = db.query(Client).filter(Client.email == body.email.lower()).first()
    if client:
        otp = generate_otp()
        now = datetime.now(timezone.utc)
        client.reset_token_hash       = hash_password(otp)
        client.reset_token_expires_at = now + timedelta(seconds=_OTP_EXPIRE_SECONDS)
        db.commit()
        send_password_reset_email(body.email.lower(), otp)

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

    _bad = HTTPException(status_code=400, detail="Invalid or expired code.")

    client = db.query(Client).filter(Client.email == body.email.lower()).first()
    if not client or not client.reset_token_hash or not client.reset_token_expires_at:
        raise _bad
    if client.reset_token_expires_at < datetime.now(timezone.utc):
        raise _bad
    if not verify_password(body.code, client.reset_token_hash):
        raise _bad

    client.password_hash          = hash_password(body.new_password)
    client.reset_token_hash       = None
    client.reset_token_expires_at = None
    db.commit()

    # Revoke ALL existing sessions — if an attacker triggered the reset,
    # any active session they have is now invalidated.
    db.query(RefreshToken).filter(
        RefreshToken.client_id == client.id
    ).update({"revoked": True})
    db.commit()

    _issue_tokens(response, db, client, request)
    send_password_changed_email(client.email)
    return {"message": "Password reset. You are now logged in."}


# ---------------------------------------------------------------------------
# GET /auth/google — redirect to Google consent page
# ---------------------------------------------------------------------------

@router.get("/google")
@limiter.limit("20/hour")
async def google_login(request: Request):
    state = secrets.token_urlsafe(32)
    _redis.setex(f"oauth_state:{state}", 600, "1")

    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id":     GOOGLE_CLIENT_ID,
            "redirect_uri":  GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope":         "openid email profile",
            "state":         state,
            "access_type":   "online",
        }
    )
    return RedirectResponse(url)


# ---------------------------------------------------------------------------
# GET /auth/google/callback
# ---------------------------------------------------------------------------

@router.get("/google/callback")
async def google_callback(
    request: Request,
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if error or not code or not state:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_cancelled")

    state_key = f"oauth_state:{state}"
    if not _redis.get(state_key):
        return RedirectResponse(f"{FRONTEND_URL}/login?error=invalid_state")
    _redis.delete(state_key)

    async with httpx.AsyncClient() as http:
        token_resp = await http.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  GOOGLE_REDIRECT_URI,
                "grant_type":    "authorization_code",
            },
        )

    if token_resp.status_code != 200:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_failed")

    access_tok = token_resp.json().get("access_token")
    if not access_tok:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_failed")

    async with httpx.AsyncClient() as http:
        profile_resp = await http.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_tok}"},
        )

    if profile_resp.status_code != 200:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_failed")

    profile     = profile_resp.json()
    provider_id = str(profile.get("sub", ""))
    email       = profile.get("email", "")

    if not provider_id or not email:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_no_email")

    return await _handle_oauth_sign_in(
        db=db,
        response=response,
        request=request,
        provider="google",
        provider_id=provider_id,
        email=email.lower(),
        company_name=profile.get("name") or email.split("@")[0],
    )


# ---------------------------------------------------------------------------
# GET /auth/github — redirect to GitHub consent page
# ---------------------------------------------------------------------------

@router.get("/github")
@limiter.limit("20/hour")
async def github_login(request: Request):
    state = secrets.token_urlsafe(32)
    _redis.setex(f"oauth_state:{state}", 600, "1")

    url = "https://github.com/login/oauth/authorize?" + urlencode(
        {
            "client_id":    GITHUB_CLIENT_ID,
            "redirect_uri": GITHUB_REDIRECT_URI,
            "scope":        "read:user user:email",
            "state":        state,
        }
    )
    return RedirectResponse(url)


# ---------------------------------------------------------------------------
# GET /auth/github/callback
# ---------------------------------------------------------------------------

@router.get("/github/callback")
async def github_callback(
    request: Request,
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if error or not code or not state:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_cancelled")

    state_key = f"oauth_state:{state}"
    if not _redis.get(state_key):
        return RedirectResponse(f"{FRONTEND_URL}/login?error=invalid_state")
    _redis.delete(state_key)

    gh_headers = {
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient() as http:
        token_resp = await http.post(
            "https://github.com/login/oauth/access_token",
            data={
                "code":          code,
                "client_id":     GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "redirect_uri":  GITHUB_REDIRECT_URI,
            },
            headers={"Accept": "application/json"},
        )

    if token_resp.status_code != 200:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_failed")

    access_tok = token_resp.json().get("access_token")
    if not access_tok:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_failed")

    gh_headers["Authorization"] = f"Bearer {access_tok}"

    async with httpx.AsyncClient() as http:
        profile_resp = await http.get("https://api.github.com/user", headers=gh_headers)

    if profile_resp.status_code != 200:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_failed")

    profile     = profile_resp.json()
    provider_id = str(profile.get("id", ""))
    email: Optional[str] = profile.get("email")

    # GitHub sometimes hides the email — fetch from the emails endpoint.
    if not email:
        async with httpx.AsyncClient() as http:
            emails_resp = await http.get(
                "https://api.github.com/user/emails", headers=gh_headers
            )
        if emails_resp.status_code == 200:
            for entry in emails_resp.json():
                if entry.get("primary") and entry.get("verified"):
                    email = entry["email"]
                    break

    if not provider_id or not email:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_no_email")

    return await _handle_oauth_sign_in(
        db=db,
        response=response,
        request=request,
        provider="github",
        provider_id=provider_id,
        email=email.lower(),
        company_name=profile.get("name") or profile.get("login") or email.split("@")[0],
    )


# ---------------------------------------------------------------------------
# Shared OAuth sign-in logic (Google + GitHub share this)
# ---------------------------------------------------------------------------

async def _handle_oauth_sign_in(
    db: Session,
    response: Response,
    request: Request,
    provider: str,
    provider_id: str,
    email: str,
    company_name: str,
) -> RedirectResponse:
    """
    Find or create the client row, link the OAuth account if needed,
    and issue auth cookies. Used by both Google and GitHub callbacks.

    Identity resolution order:
      1. Match on (provider, provider_id) — stable even if user changes email.
      2. Match on email — silently link to an existing credentials account.
      3. Neither found — create a new client + oauth row.
    """
    oauth_acc = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.provider    == provider,
            OAuthAccount.provider_id == provider_id,
        )
        .first()
    )

    if oauth_acc:
        client = db.query(Client).filter(Client.id == oauth_acc.client_id).first()
        if not client:
            return RedirectResponse(f"{FRONTEND_URL}/login?error=account_error")

    else:
        client = db.query(Client).filter(Client.email == email).first()

        if client:
            # Link this OAuth provider to the existing credentials account.
            db.add(
                OAuthAccount(
                    client_id=client.id,
                    provider=provider,
                    provider_id=provider_id,
                    email=email,
                )
            )
            db.commit()
            send_oauth_linked_email(client.email, provider)

        else:
            # Brand-new user — create client and oauth_account together.
            client = Client(
                email=email,
                password_hash=None,   # OAuth-only; password_hash stays NULL
                company_name=company_name,
                email_verified=True,  # Provider already verified the email
            )
            db.add(client)
            db.flush()  # populate client.id without committing yet
            db.add(
                OAuthAccount(
                    client_id=client.id,
                    provider=provider,
                    provider_id=provider_id,
                    email=email,
                )
            )
            db.commit()

    _issue_tokens(response, db, client, request)
    return RedirectResponse(f"{FRONTEND_URL}/dashboard")


# ---------------------------------------------------------------------------
# GET /auth/microsoft — redirect to Microsoft Entra consent page
#
# App registration in Azure Portal:
#   https://portal.azure.com → Entra ID → App registrations → New registration
#   Supported account types: "Accounts in any organizational directory
#     (Any Azure AD tenant – Multitenant) and personal Microsoft accounts"
#   Redirect URI (Web): https://api.clewsec.com/auth/microsoft/callback
# ---------------------------------------------------------------------------

@router.get("/microsoft")
@limiter.limit("20/hour")
async def microsoft_login(request: Request):
    state = secrets.token_urlsafe(32)
    _redis.setex(f"oauth_state:{state}", 600, "1")

    url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?" + urlencode(
        {
            "client_id":     MICROSOFT_CLIENT_ID,
            "redirect_uri":  MICROSOFT_REDIRECT_URI,
            "response_type": "code",
            "scope":         "openid email profile User.Read",
            "state":         state,
            "response_mode": "query",
        }
    )
    return RedirectResponse(url)


# ---------------------------------------------------------------------------
# GET /auth/microsoft/callback
# ---------------------------------------------------------------------------

@router.get("/microsoft/callback")
async def microsoft_callback(
    request: Request,
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if error or not code or not state:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_cancelled")

    state_key = f"oauth_state:{state}"
    if not _redis.get(state_key):
        return RedirectResponse(f"{FRONTEND_URL}/login?error=invalid_state")
    _redis.delete(state_key)

    async with httpx.AsyncClient() as http:
        token_resp = await http.post(
            "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            data={
                "code":          code,
                "client_id":     MICROSOFT_CLIENT_ID,
                "client_secret": MICROSOFT_CLIENT_SECRET,
                "redirect_uri":  MICROSOFT_REDIRECT_URI,
                "grant_type":    "authorization_code",
                "scope":         "openid email profile User.Read",
            },
        )

    if token_resp.status_code != 200:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_failed")

    access_tok = token_resp.json().get("access_token")
    if not access_tok:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_failed")

    async with httpx.AsyncClient() as http:
        profile_resp = await http.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_tok}"},
        )

    if profile_resp.status_code != 200:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_failed")

    profile = profile_resp.json()
    provider_id = str(profile.get("id", ""))
    # Prefer 'mail' (real email) over 'userPrincipalName' which can be a
    # tenant UPN like user@contoso.onmicrosoft.com for corporate accounts.
    email: Optional[str] = profile.get("mail") or profile.get("userPrincipalName")

    if not provider_id or not email:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_no_email")

    display_name: str = profile.get("displayName") or email.split("@")[0]

    return await _handle_oauth_sign_in(
        db=db,
        response=response,
        request=request,
        provider="microsoft",
        provider_id=provider_id,
        email=email.lower(),
        company_name=display_name,
    )


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

    code = body.code.strip().upper()

    # Try TOTP first, then backup code
    totp_secret = decrypt_totp_secret(client.mfa_secret)
    totp = pyotp.TOTP(totp_secret)
    if totp.verify(code, valid_window=2):
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
        backup.used = True
        db.commit()
        _issue_tokens(response, db, client, request)
        return {"message": "Logged in via backup code."}

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
    client.mfa_secret = encrypt_totp_secret(secret)
    db.commit()
    return {"secret": secret, "uri": uri}


# ---------------------------------------------------------------------------
# POST /auth/mfa/verify — confirm the first TOTP code to activate MFA
# ---------------------------------------------------------------------------

@router.post("/mfa/verify")
async def mfa_verify(
    body: MfaVerifyBody,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    if client.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled.")
    if not client.mfa_secret:
        raise HTTPException(status_code=400, detail="Run /mfa/setup first.")

    totp_secret = decrypt_totp_secret(client.mfa_secret)
    totp = pyotp.TOTP(totp_secret)
    if not totp.verify(body.code.strip(), valid_window=2):
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
    if not verify_password(body.password, client.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    client.mfa_enabled = False
    client.mfa_secret  = None
    db.query(MfaBackupCode).filter(MfaBackupCode.client_id == client.id).delete()
    db.commit()
    send_mfa_enabled_email(client.email, enabled=False)
    return {"message": "MFA disabled."}


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
    session_id: str,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    row = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.id        == session_id,
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
