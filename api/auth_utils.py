"""
auth_utils.py — all auth primitives used by the auth router.

Responsibilities:
  - Password hashing / verification
  - JWT creation / decoding
  - Cookie setting / clearing
  - OTP generation
  - SES email dispatch
"""
import hashlib
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt as _bcrypt
import httpx
import resend
from cryptography.fernet import Fernet, InvalidToken as _FernetInvalidToken
from dotenv import load_dotenv
from jose import JWTError, jwt
from fastapi import Response

load_dotenv()

# ------------------------------------------------------------------
# Config from environment
# ------------------------------------------------------------------
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
# Item 25 — five sending identities, all on the email.clewsec.com subdomain
# (isolates transactional sending reputation from the root clewsec.com domain).
FROM_ADDRESS  = "Clew <noreply@email.clewsec.com>"
FROM_ALERTS   = "Clew Alerts <alerts@email.clewsec.com>"
FROM_BILLING  = "Clew Billing <billing@email.clewsec.com>"
FROM_TEAM     = "Clew Team <team@email.clewsec.com>"
REPLY_TO_ALERTS  = "alerts@email.clewsec.com"
REPLY_TO_BILLING = "billing@email.clewsec.com"
REPLY_TO_TEAM    = "team@email.clewsec.com"
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")
_TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Fernet key for encrypting TOTP secrets at rest.
# Must be a 32-byte URL-safe base64 key — generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Store in TOTP_ENCRYPTION_KEY env var.  If absent we raise loudly so it can't
# be silently skipped in production.
_TOTP_KEY_RAW = os.environ.get("TOTP_ENCRYPTION_KEY", "")
if _TOTP_KEY_RAW:
    _fernet = Fernet(_TOTP_KEY_RAW.encode())
else:
    _fernet = None  # dev fallback — encrypt/decrypt will raise if called


def encrypt_totp_secret(secret: str) -> str:
    """Encrypt a plaintext TOTP Base32 secret for storage."""
    if _fernet is None:
        raise RuntimeError("TOTP_ENCRYPTION_KEY is not set. Cannot encrypt TOTP secret.")
    return _fernet.encrypt(secret.encode()).decode()


def decrypt_totp_secret(ciphertext: str) -> str:
    """Decrypt a stored TOTP secret ciphertext back to the Base32 string."""
    if _fernet is None:
        raise RuntimeError("TOTP_ENCRYPTION_KEY is not set. Cannot decrypt TOTP secret.")
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except _FernetInvalidToken as exc:
        raise ValueError("TOTP secret decryption failed — key mismatch or corrupted data.") from exc

# ------------------------------------------------------------------
# Password hashing (bcrypt cost-12, SHA-256 pre-hash)
#
# bcrypt truncates at 72 bytes; bcrypt>=4.x raises on longer inputs.
# SHA-256 hex digest is always 64 bytes, safely under the limit, and
# preserves full password entropy.
# ------------------------------------------------------------------

def _prepare(plain: str) -> bytes:
    """SHA-256 hex-digest of the password, encoded to bytes (64 bytes)."""
    return hashlib.sha256(plain.encode()).hexdigest().encode()


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(_prepare(plain), _bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(_prepare(plain), hashed.encode())


# ------------------------------------------------------------------
# JWT
# ------------------------------------------------------------------
def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    """Create a short-lived access JWT. `subject` is the client UUID."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "type": "access"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """Create a long-lived refresh JWT stored as a hashed value in the DB."""
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": subject, "exp": expire, "type": "refresh", "jti": str(uuid.uuid4())}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Decode and validate an access JWT. Returns payload or None."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def decode_refresh_token(token: str) -> dict | None:
    """Decode and validate a refresh JWT. Returns payload or None."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            return None
        return payload
    except JWTError:
        return None


def hash_token(raw: str) -> str:
    """SHA-256 hash of a raw token — stored in DB, never the raw value."""
    return hashlib.sha256(raw.encode()).hexdigest()


# ------------------------------------------------------------------
# Cookies
# ------------------------------------------------------------------
# Local dev uses HTTP so secure=False; in production Nginx terminates TLS
# and we want secure=True. Use FRONTEND_URL to detect.
_IS_PROD = FRONTEND_URL.startswith("https")

# Optional shared-domain cookie scope (e.g. ".clewsec.com").
# Required in production so both api.clewsec.com and www.clewsec.com share
# cookies, allowing the Next.js middleware to read and forward the refresh token.
COOKIE_DOMAIN: str | None = os.environ.get("COOKIE_DOMAIN") or None


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    # Note: no path restriction on refresh_token — the browser-enforced
    # Path=/auth/refresh would prevent the cross-origin Next.js middleware from
    # reading it. The refresh token remains secure (httpOnly + signed + DB-hashed).
    shared: dict = dict(httponly=True, secure=_IS_PROD, samesite="lax")
    if COOKIE_DOMAIN:
        shared["domain"] = COOKIE_DOMAIN
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **shared,  # type: ignore[arg-type]
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        **shared,  # type: ignore[arg-type]
    )


def clear_auth_cookies(response: Response) -> None:
    kwargs: dict = {}
    if COOKIE_DOMAIN:
        kwargs["domain"] = COOKIE_DOMAIN
    response.delete_cookie("access_token", **kwargs)  # type: ignore[arg-type]
    response.delete_cookie("refresh_token", **kwargs)  # type: ignore[arg-type]
    response.delete_cookie("last_org_id", **kwargs)  # type: ignore[arg-type]


# Phase 2: remembers which org was last active so a returning multi-org user
# skips the /select-org screen. Not httponly — the frontend org switcher UI
# reads it directly. It is never trusted for authorization: get_current_org()
# always re-verifies against a live OrganizationMember row.
def set_last_org_cookie(response: Response, org_id: str | None) -> None:
    kwargs: dict = dict(httponly=False, secure=_IS_PROD, samesite="lax")
    if COOKIE_DOMAIN:
        kwargs["domain"] = COOKIE_DOMAIN
    if org_id:
        response.set_cookie(
            key="last_org_id",
            value=org_id,
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
            **kwargs,  # type: ignore[arg-type]
        )
    else:
        response.delete_cookie("last_org_id", **{k: v for k, v in kwargs.items() if k == "domain"})  # type: ignore[arg-type]


# ------------------------------------------------------------------
# OTP  (6-digit numeric code)
# ------------------------------------------------------------------
def generate_otp() -> str:
    """Return a cryptographically random 6-digit string."""
    return "".join(random.SystemRandom().choices(string.digits, k=6))


# ------------------------------------------------------------------
# CAPTCHA (Cloudflare Turnstile) — item 38 spec, wired up early for item 10
# ------------------------------------------------------------------
def verify_turnstile_token(token: str, remote_ip: str | None = None) -> bool:
    """Server-side verification of a Turnstile widget response token.

    Fails closed: any missing config, network error, or non-success
    response is treated as a failed CAPTCHA.
    """
    if not TURNSTILE_SECRET_KEY or not token:
        return False
    payload: dict[str, Any] = {"secret": TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip
    try:
        resp = httpx.post(_TURNSTILE_VERIFY_URL, data=payload, timeout=10.0)
        resp.raise_for_status()
        return bool(resp.json().get("success"))
    except httpx.HTTPError:
        return False


# ------------------------------------------------------------------
# MFA backup codes
# ------------------------------------------------------------------
_BACKUP_CODE_CHARS = string.ascii_uppercase + string.digits

def generate_backup_codes(n: int = 10) -> list[str]:
    """
    Return n random 10-character alphanumeric backup codes (uppercase).
    Format: XXXXX-XXXXX for display; stored as SHA-256 hashes.
    """
    rng = random.SystemRandom()
    codes = []
    for _ in range(n):
        raw = "".join(rng.choices(_BACKUP_CODE_CHARS, k=10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


# ------------------------------------------------------------------
# Email via Resend
# ------------------------------------------------------------------
def send_email(
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    from_address: str | None = None,
    reply_to: str | None = None,
) -> bool:
    """
    Send a transactional email via Resend.
    Returns True on success, False on failure (caller logs + continues).
    Never raises — a failed email must not crash an auth flow.
    """
    try:
        if os.environ.get("LOG_EMAILS", "").lower() in ("1", "true", "yes"):
            print(f"\n{'='*60}")
            print(f"[EMAIL] To: {to}")
            print(f"[EMAIL] Subject: {subject}")
            print(f"[EMAIL] Body:\n{body_text}")
            print(f"{'='*60}\n")
            return True
        resend.api_key = RESEND_API_KEY
        params: resend.Emails.SendParams = {
            "from":    from_address or FROM_ADDRESS,
            "to":      [to],
            "subject": subject,
            "text":    body_text,
            "html":    body_html or f"<pre>{body_text}</pre>",
        }
        if reply_to:
            params["reply_to"] = reply_to
        resend.Emails.send(params)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------
# Shared HTML email layout
# ------------------------------------------------------------------
_LOGO_URL = "https://clewsec.com/clew-wordmark-light.png"


def _p(text: str) -> str:
    """Inline-styled paragraph for email body."""
    return (
        f'<p style="font-family:system-ui,-apple-system,BlinkMacSystemFont,sans-serif;'
        f'font-size:14px;color:#0D0D0D;line-height:1.6;margin:0 0 16px 0;">{text}</p>'
    )


def _otp_block(code: str) -> str:
    """Large monospace OTP display block."""
    return (
        '<div style="background:#F5F5F5;border:1px solid #D0D0D0;padding:24px;'
        'text-align:center;margin:24px 0;">'
        f'<span style="font-family:\'Courier New\',Courier,monospace;font-size:32px;'
        f'font-weight:700;color:#0D0D0D;letter-spacing:8px;">{code}</span>'
        '</div>'
    )


def _email_html(heading: str, body_html: str, footer_note: str = "") -> str:
    """Full HTML email using Clew design system (inline CSS only — Gmail-safe)."""
    note = footer_note or "If you did not request this, you can safely ignore this email."
    return (
        '<!DOCTYPE html><html lang="en">'
        '<head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '</head>'
        '<body style="margin:0;padding:0;background:#F5F5F5;">'
        '<div style="background:#F5F5F5;padding:40px 24px;'
        'font-family:system-ui,-apple-system,BlinkMacSystemFont,sans-serif;">'
        # Logo
        '<div style="margin-bottom:32px;">'
        f'<img src="{_LOGO_URL}" alt="Clew" width="80" '
        'style="display:block;border:0;">'
        '</div>'
        # Card
        '<div style="background:#EBEBEB;border:1px solid #D0D0D0;padding:32px;max-width:520px;">'
        f'<h1 style="font-family:\'Courier Prime\',Courier,\'Courier New\',monospace;'
        f'font-size:18px;font-weight:700;color:#0D0D0D;margin:0 0 20px 0;">{heading}</h1>'
        f'{body_html}'
        '</div>'
        # Footer
        f'<p style="font-family:system-ui,-apple-system,BlinkMacSystemFont,sans-serif;'
        f'font-size:12px;color:#5A5A5A;margin:24px 0 0 0;max-width:520px;">'
        f'{note}<br>'
        '&copy; 2026 Clew &middot; '
        '<a href="https://clewsec.com" style="color:#5A5A5A;">clewsec.com</a>'
        '</p>'
        '</div></body></html>'
    )


# ------------------------------------------------------------------
# Email templates
# ------------------------------------------------------------------
def send_verification_email(to: str, code: str) -> bool:
    body_text = (
        f"Your Clew verification code is: {code}\n\n"
        "Enter this code on the verification page. It expires in 15 minutes.\n\n"
        "If you didn't create a Clew account, ignore this email."
    )
    body_html = _email_html(
        heading="Verify your account",
        body_html=(
            _p("Enter the code below on the verification page. It expires in 15 minutes.")
            + _otp_block(code)
            + _p("If you did not create a Clew account, you can safely ignore this email.")
        ),
        footer_note="This code expires in 15 minutes and can only be used once.",
    )
    return send_email(to=to, subject="Verify your Clew account", body_text=body_text, body_html=body_html)


def send_password_reset_email(to: str, code: str) -> bool:
    body_text = (
        f"Your Clew password reset code is: {code}\n\n"
        "Enter this code on the reset page. It expires in 15 minutes.\n\n"
        "If you didn't request a password reset, ignore this email."
    )
    body_html = _email_html(
        heading="Reset your password",
        body_html=(
            _p("Enter the code below on the password reset page. It expires in 15 minutes.")
            + _otp_block(code)
            + _p("If you did not request a password reset, you can safely ignore this email.")
        ),
        footer_note="This code expires in 15 minutes and can only be used once.",
    )
    return send_email(to=to, subject="Reset your Clew password", body_text=body_text, body_html=body_html)


def send_login_lockout_email(to: str) -> bool:
    body_text = (
        "Someone is attempting to log in to your Clew account.\n\n"
        "Your account has been temporarily locked for 15 minutes.\n\n"
        "If this wasn't you, no action is needed — the lock will expire "
        "automatically and your password has not been changed."
    )
    body_html = _email_html(
        heading="Account temporarily locked",
        body_html=(
            _p("Someone is attempting to log in to your Clew account.")
            + _p("Your account has been temporarily locked for 15 minutes.")
            + _p(
                "If this wasn't you, no action is needed — the lock will expire "
                "automatically and your password has not been changed."
            )
        ),
        footer_note="This is a security notice for your Clew account.",
    )
    return send_email(to=to, subject="Your Clew account was temporarily locked", body_text=body_text, body_html=body_html)


def send_password_changed_email(to: str) -> bool:
    body_text = (
        "Your Clew account password was just changed.\n\n"
        "If this was you, no action is needed.\n"
        "If you did not make this change, contact support immediately."
    )
    body_html = _email_html(
        heading="Your password was changed",
        body_html=(
            _p("Your Clew account password was just changed.")
            + _p("If this was you, no action is needed.")
            + _p(
                'If you did not make this change, '
                '<a href="mailto:support@clewsec.com" style="color:#0D0D0D;">contact support</a> immediately.'
            )
        ),
        footer_note="This is a security notice for your Clew account.",
    )
    return send_email(to=to, subject="Your Clew password was changed", body_text=body_text, body_html=body_html)


def send_mfa_enabled_email(to: str, enabled: bool) -> bool:
    action = "enabled" if enabled else "disabled"
    body_text = (
        f"Two-factor authentication (TOTP) has been {action} on your Clew account.\n\n"
        "If you did not make this change, contact support immediately."
    )
    body_html = _email_html(
        heading=f"Two-factor authentication {action}",
        body_html=(
            _p(f"Two-factor authentication (TOTP) has been <strong>{action}</strong> on your Clew account.")
            + _p(
                'If you did not make this change, '
                '<a href="mailto:support@clewsec.com" style="color:#0D0D0D;">contact support</a> immediately.'
            )
        ),
        footer_note="This is a security notice for your Clew account.",
    )
    return send_email(
        to=to,
        subject=f"Two-factor authentication {action} on your Clew account",
        body_text=body_text,
        body_html=body_html,
    )


def send_trial_reminder_email(to: str, days_remaining: int, trial_days_total: int) -> bool:
    """Item 11 trial-expiry schedule. Sent from billing@ rather than noreply@."""
    body_text = (
        f"Your Clew {trial_days_total}-day trial ends in {days_remaining} day"
        f"{'s' if days_remaining != 1 else ''}.\n\n"
        "Add a payment method to keep scanning your logs without interruption.\n"
        f"{FRONTEND_URL}/dashboard/settings#billing"
    )
    body_html = _email_html(
        heading="Your Clew trial is ending soon",
        body_html=(
            _p(
                f"Your Clew {trial_days_total}-day trial ends in "
                f"<strong>{days_remaining} day{'s' if days_remaining != 1 else ''}</strong>."
            )
            + _p("Add a payment method to keep scanning your logs without interruption.")
            + _p(
                f'<a href="{FRONTEND_URL}/dashboard/settings#billing" style="color:#0D0D0D;">Add payment method &rarr;</a>'
            )
        ),
        footer_note="You are receiving this because your organisation has an active Clew trial.",
    )
    return send_email(
        to=to,
        subject=f"Your Clew trial ends in {days_remaining} day{'s' if days_remaining != 1 else ''}",
        body_text=body_text,
        body_html=body_html,
        from_address=FROM_BILLING,
        reply_to=REPLY_TO_BILLING,
    )


def send_payment_failed_email(to: str) -> bool:
    """Item 29: immediate Clew-branded notice on a Razorpay/Stripe payment
    failure, beyond whatever auto-retry the provider itself does."""
    body_text = (
        "A recent payment on your Clew subscription did not go through.\n\n"
        "Please update your payment method to avoid an interruption to your service.\n"
        f"{FRONTEND_URL}/dashboard/settings#billing"
    )
    body_html = _email_html(
        heading="Your Clew payment failed",
        body_html=(
            _p("A recent payment on your Clew subscription did not go through.")
            + _p("Please update your payment method to avoid an interruption to your service.")
            + _p(
                f'<a href="{FRONTEND_URL}/dashboard/settings#billing" style="color:#0D0D0D;">Update payment method &rarr;</a>'
            )
        ),
        footer_note="You are receiving this because your organisation has an active Clew subscription.",
    )
    return send_email(
        to=to,
        subject="Action needed: your Clew payment failed",
        body_text=body_text,
        body_html=body_html,
        from_address=FROM_BILLING,
        reply_to=REPLY_TO_BILLING,
    )


# ------------------------------------------------------------------
# Item 9 — organisation invite email
# ------------------------------------------------------------------
def send_org_invite_email(
    to: str,
    inviter_name: str,
    company_name: str,
    role: str,
    accept_url: str,
    existing_account: bool = False,
) -> bool:
    role_label = role.capitalize()
    existing_note = (
        f"You already have a Clew account with this email. Clicking accept will "
        f"add {company_name} to your organisations."
        if existing_account else ""
    )
    body_text = (
        f"{inviter_name} has invited you to join {company_name}'s security "
        f"dashboard on Clew as a {role_label}.\n\n"
        f"Accept the invitation: {accept_url}\n\n"
        "This invitation expires in 7 days.\n\n"
        + (existing_note + "\n\n" if existing_note else "")
        + "If you don't recognise this invitation, ignore this email — no "
        "account will be created."
    )
    body_html = _email_html(
        heading="You've been invited to Clew",
        body_html=(
            _p(
                f"<strong>{inviter_name}</strong> has invited you to join "
                f"<strong>{company_name}</strong>'s security dashboard on Clew "
                f"as a <strong>{role_label}</strong>."
            )
            + (_p(existing_note) if existing_note else "")
            + f'<div style="text-align:center;margin:24px 0;">'
              f'<a href="{accept_url}" style="display:inline-block;background:#0D0D0D;'
              f'color:#F5F5F5;padding:12px 24px;'
              f'font-family:system-ui,-apple-system,BlinkMacSystemFont,sans-serif;'
              f'font-size:14px;font-weight:600;text-decoration:none;">Accept Invitation</a>'
              f'</div>'
            + _p("This invitation expires in 7 days.")
            + _p("If you don't recognise this invitation, ignore this email — no account will be created.")
        ),
        footer_note="This invitation expires in 7 days and can only be used once.",
    )
    return send_email(
        to=to,
        subject=f"{inviter_name} invited you to join {company_name} on Clew",
        body_text=body_text,
        body_html=body_html,
        from_address=FROM_TEAM,
        reply_to=REPLY_TO_TEAM,
    )
