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
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt as _bcrypt
import boto3
from botocore.exceptions import ClientError
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
SES_FROM_ADDRESS = os.environ.get("SES_FROM_ADDRESS", "noreply@example.com")
SES_FROM_NAME = os.environ.get("SES_FROM_NAME", "Clew")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-south-1")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

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
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
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


# ------------------------------------------------------------------
# OTP  (6-digit numeric code)
# ------------------------------------------------------------------
def generate_otp() -> str:
    """Return a cryptographically random 6-digit string."""
    return "".join(random.SystemRandom().choices(string.digits, k=6))


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
# Email via SES
# ------------------------------------------------------------------
def send_email(to: str, subject: str, body_text: str, body_html: str | None = None) -> bool:
    """
    Send a transactional email via SES.
    Returns True on success, False on failure (caller logs + continues).
    Never raises — a failed email must not crash an auth flow.
    """
    try:
        if os.environ.get("LOG_EMAILS", "").lower() in ("1", "true", "yes"):
            # Dev mode: print to console instead of sending via SES
            print(f"\n{'='*60}")
            print(f"[EMAIL] To: {to}")
            print(f"[EMAIL] Subject: {subject}")
            print(f"[EMAIL] Body:\n{body_text}")
            print(f"{'='*60}\n")
            return True
        client = boto3.client("ses", region_name=AWS_REGION)
        message: dict = {
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": body_text}},
        }
        if body_html:
            message["Body"]["Html"] = {"Data": body_html}

        client.send_email(
            Source=f"{SES_FROM_NAME} <{SES_FROM_ADDRESS}>",
            Destination={"ToAddresses": [to]},
            Message=message,
        )
        return True
    except ClientError:
        # Log in production; for now a silent False keeps auth working locally
        # without SES configured.
        return False


# ------------------------------------------------------------------
# Email templates (plain text — keep simple until volume warrants HTML)
# ------------------------------------------------------------------
def send_verification_email(to: str, code: str) -> bool:
    return send_email(
        to=to,
        subject="Verify your Clew account",
        body_text=(
            f"Your Clew verification code is: {code}\n\n"
            f"Enter this code on the verification page. It expires in 15 minutes.\n\n"
            f"If you didn't create a Clew account, ignore this email."
        ),
    )


def send_password_reset_email(to: str, code: str) -> bool:
    return send_email(
        to=to,
        subject="Reset your Clew password",
        body_text=(
            f"Your Clew password reset code is: {code}\n\n"
            f"Enter this code on the reset page. It expires in 15 minutes.\n\n"
            f"If you didn't request a password reset, ignore this email."
        ),
    )


def send_password_changed_email(to: str) -> bool:
    return send_email(
        to=to,
        subject="Your Clew password was changed",
        body_text=(
            "Your Clew account password was just changed.\n\n"
            "If this was you, no action is needed.\n"
            "If you did not make this change, contact support immediately."
        ),
    )


def send_oauth_linked_email(to: str, provider: str) -> bool:
    provider_name = provider.capitalize()
    return send_email(
        to=to,
        subject=f"{provider_name} sign-in linked to your Clew account",
        body_text=(
            f"{provider_name} sign-in has been linked to your Clew account.\n\n"
            f"You can now sign in with {provider_name} or your email and password.\n\n"
            f"If you did not do this, contact support immediately."
        ),
    )


def send_mfa_enabled_email(to: str, enabled: bool) -> bool:
    action = "enabled" if enabled else "disabled"
    return send_email(
        to=to,
        subject=f"Two-factor authentication {action} on your Clew account",
        body_text=(
            f"Two-factor authentication (TOTP) has been {action} on your Clew account.\n\n"
            f"If you did not make this change, contact support immediately."
        ),
    )
