"""api/routes/newsletter.py: Phase 6 item 6d, double opt-in newsletter signup.

  POST /newsletter/subscribe
  POST /newsletter/confirm

No local subscriber table by design: Resend's own Segment is the single
source of truth for who is subscribed, so there is exactly one unsubscribe
list. Sent from the news.clewsec.com subdomain (FROM_NEWS), kept separate
from transactional mail so a newsletter broadcast's spam/complaint rate can
never touch verification/reset/alert deliverability.

Uses Resend's current global-Contacts model (`resend.Contacts.create`/`get`/
`update` with no `audience_id`, membership expressed via `segments`), not
the deprecated Audiences API. Resend retired Audiences in favour of
Contacts + Segments + Topics in November 2025; an account created or
migrated after that has no Audience to reference at all.

Confirmation state is carried in a signed, short-lived JWT (see
create_newsletter_confirm_token in auth_utils.py) instead of a DB row, since
there is deliberately no subscribers table.
"""
import logging
import os
import re

import resend
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from api.auth_utils import (
    FRONTEND_URL,
    FROM_NEWS,
    RESEND_API_KEY,
    create_newsletter_confirm_token,
    decode_newsletter_confirm_token,
    send_email,
)
from api.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/newsletter", tags=["newsletter"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Identical for every non-honeypot outcome (new signup, resubscribe after an
# unsubscribe, already-subscribed) so this form can never be used to probe
# whether an email is on the list.
_GENERIC_RESPONSE = {"message": "Check your email to confirm your subscription."}


class SubscribeBody(BaseModel):
    email: str
    # Hidden form field real users never see or fill; a non-empty value
    # means a bot filled every input on the form.
    website: str = ""

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v.lower().strip()


class ConfirmBody(BaseModel):
    token: str


def _segment_id() -> str:
    return os.environ.get("RESEND_SEGMENT_ID", "")


@router.post("/subscribe")
@limiter.limit("5/hour")
def subscribe(request: Request, body: SubscribeBody):
    if body.website:
        # Honeypot tripped: pretend success, don't tip the bot off.
        return _GENERIC_RESPONSE

    segment_id = _segment_id()
    if not segment_id:
        raise HTTPException(503, "Newsletter signups aren't set up yet.")

    resend.api_key = RESEND_API_KEY
    already_subscribed = False
    try:
        contact = resend.Contacts.get(email=body.email)
        already_subscribed = bool(contact) and not contact.get("unsubscribed", False)
    except Exception:
        pass  # not found, or a transient Resend error: treat as not subscribed

    if already_subscribed:
        return _GENERIC_RESPONSE

    token = create_newsletter_confirm_token(body.email)
    confirm_url = f"{FRONTEND_URL}/newsletter/confirm?token={token}"
    send_email(
        to=body.email,
        subject="Confirm your Clew newsletter subscription",
        body_text=(
            "Click to confirm your subscription to Clew's newsletter:\n\n"
            f"{confirm_url}\n\n"
            "If you didn't request this, you can ignore this email."
        ),
        from_address=FROM_NEWS,
    )
    return _GENERIC_RESPONSE


@router.post("/confirm")
def confirm(body: ConfirmBody):
    email = decode_newsletter_confirm_token(body.token)
    if not email:
        raise HTTPException(400, "This confirmation link is invalid or has expired.")

    segment_id = _segment_id()
    if not segment_id:
        raise HTTPException(503, "Newsletter signups aren't set up yet.")

    resend.api_key = RESEND_API_KEY
    try:
        resend.Contacts.create({
            "email": email,
            "unsubscribed": False,
            "segments": [{"id": segment_id}],
        })
    except Exception:
        try:
            resend.Contacts.update({"email": email, "unsubscribed": False})
        except Exception:
            logger.exception("newsletter: could not confirm subscription")
            raise HTTPException(502, "Could not confirm your subscription. Please try again.")
    return {"message": "You're subscribed. Thanks for joining."}
