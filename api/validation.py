"""api/validation.py: shared input checks (Phase 14).

Phase 13 found several routes that stored whatever they were sent: a password
of "a", an "email" with spaces or no @, a 300 character name that crashed on a
String(255) column (a 500). Every helper here raises HTTPException(422) with a
plain string detail, the shape the frontend already reads as `data.detail`.
"""
import re

from fastapi import HTTPException

EMAIL_MAX = 254
NAME_MAX = 255
PASSWORD_MIN = 8
PASSWORD_MAX = 128

# One @, no spaces or quote and bracket characters, a dot in the domain part.
# Deliberately loose: the real proof an address works is the email we send.
_BAD = r"\s@<>\"'(),;:\\\[\]\x00"
_EMAIL_RE = re.compile(rf"^[^{_BAD}]+@[^{_BAD}]+\.[^{_BAD}]{{2,}}$")


def clean_email(value: str, field: str = "Email") -> str:
    """Trimmed, lower-cased address, or a 422."""
    email = (value or "").strip().lower()
    if len(email) > EMAIL_MAX:
        raise HTTPException(status_code=422, detail=f"{field} must be at most {EMAIL_MAX} characters.")
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return email


def clean_text(value: str | None, field: str, max_len: int = NAME_MAX, required: bool = True) -> str:
    """Trimmed text of at most `max_len` characters. Empty is a 422 when required."""
    text = (value or "").strip()
    if required and not text:
        raise HTTPException(status_code=422, detail=f"{field} is required.")
    if len(text) > max_len:
        raise HTTPException(status_code=422, detail=f"{field} must be at most {max_len} characters.")
    if "\x00" in text:
        raise HTTPException(status_code=422, detail=f"{field} contains a character that is not allowed.")
    return text


def check_password(value: str) -> str:
    """The password itself is never trimmed. 8 to 128 characters, or a 422."""
    if value is None or len(value) < PASSWORD_MIN:
        raise HTTPException(status_code=422, detail=f"Password must be at least {PASSWORD_MIN} characters.")
    if len(value) > PASSWORD_MAX:
        raise HTTPException(status_code=422, detail=f"Password must be at most {PASSWORD_MAX} characters.")
    return value
