"""api/billing_emails.py: Phase 5 billing emails (recipients, content, sending).

Everything is plain functions over an open SQLAlchemy session so it can be
tested without Celery or Resend. The Celery task in
workers/tasks/billing_emails.py is a thin wrapper around send_billing_emails.

Kinds (see api/billing_notify.py):
  ready, due_in_3, cancel_in_3, cancelled, payment_received, pilot_ended

Every email comes from FROM_BILLING, replies go to REPLY_TO_BILLING, and
carries one link: "View billing" to the dashboard billing section. No invoice
is inlined, the amounts quoted are the stored amounts in the stored currency.
"""
from __future__ import annotations

import html
import logging
from datetime import date

from api.auth_utils import (
    DASHBOARD_URL,
    FROM_BILLING,
    REPLY_TO_BILLING,
    _email_html,
    _p,
    send_email,
)
from api.billing_payments import plan_label
from db.models import Client, Organization, OrganizationMember

logger = logging.getLogger(__name__)

# These two always reach the owners, whatever the org's recipient setting.
ALWAYS_OWNER_KINDS = frozenset({"cancel_in_3", "cancelled", "pilot_ended"})

BILLING_URL = f"{DASHBOARD_URL}/settings#billing"

_SYMBOLS = {"INR": "\u20b9", "USD": "$"}


def format_money(amount_minor: int, currency: str) -> str:
    """An amount in minor units with its currency symbol: 199900 INR is
    "\u20b91,999", 4950 USD is "$49.50". Whole amounts drop the decimals.
    Western digit grouping for every currency, to match the dashboard."""
    symbol = _SYMBOLS.get(currency)
    if symbol is None:
        raise ValueError(f"no display symbol for currency {currency!r}")
    major, minor = divmod(amount_minor, 100)
    text = f"{major:,}" if minor == 0 else f"{major:,}.{minor:02d}"
    return f"{symbol}{text}"


def format_date(value: date) -> str:
    """20 December 2026"""
    return f"{value.day} {value.strftime('%B %Y')}"


# ---------------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------------

def resolve_billing_recipients(org: Organization, db, always_owners: bool = False) -> list[str]:
    """Email addresses that should receive a billing email for `org`.

    billing_emails_mode 'owner' is the owners, 'selected' is the members
    marked is_billing_contact, 'all' is every member. If 'selected' has nobody
    marked, the owners receive it, so a mail is never silently dropped.
    `always_owners` (the cancel warning and the cancelled notice) adds the
    owners whatever the mode. Deleted accounts are skipped, duplicates removed.
    """
    rows = (
        db.query(OrganizationMember.role, OrganizationMember.is_billing_contact, Client.email)
        .join(Client, Client.id == OrganizationMember.client_id)
        .filter(OrganizationMember.org_id == org.id, Client.deleted_at.is_(None))
        .order_by(OrganizationMember.created_at.asc())
        .all()
    )
    owners = [email for role, _contact, email in rows if role == "owner"]
    mode = org.billing_emails_mode
    if mode == "all":
        chosen = [email for _role, _contact, email in rows]
    elif mode == "selected":
        chosen = [email for _role, contact, email in rows if contact] or owners
    else:
        chosen = owners
    if always_owners:
        chosen = chosen + owners

    seen: set[str] = set()
    result: list[str] = []
    for email in chosen:
        key = email.lower()
        if key not in seen:
            seen.add(key)
            result.append(email)
    return result


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

def _link() -> str:
    return _p(f'<a href="{BILLING_URL}" style="color:#0D0D0D;">View billing &rarr;</a>')


def render_billing_email(kind: str, org: Organization, bill=None, payment=None) -> tuple[str, str, str]:
    """(subject, plain text, html) for one billing email."""
    if kind in ("ready", "due_in_3", "cancel_in_3"):
        if bill is None:
            raise ValueError(f"{kind} needs a bill")
        amount = format_money(bill.amount_paise, bill.currency)
        plan = plan_label(bill.tier, bill.period)
        due = format_date(bill.due_date)
        cancel = format_date(bill.cancel_on)
        if kind == "ready":
            subject = f"Your Clew bill for {plan} is ready"
            heading = "Your Clew bill is ready"
            lines = [
                f"Your {plan} bill of {amount} is ready. It is due on {due}.",
                f"If it is still unpaid on {cancel}, your plan will be cancelled.",
            ]
        elif kind == "due_in_3":
            subject = "Your Clew bill is due in 3 days"
            heading = "Your Clew bill is due in 3 days"
            lines = [
                f"Your {plan} bill of {amount} is due on {due}.",
                f"If it is still unpaid on {cancel}, your plan will be cancelled.",
            ]
        else:
            subject = "Your Clew plan will be cancelled in 3 days"
            heading = "Your Clew plan will be cancelled in 3 days"
            lines = [
                f"Your {plan} bill of {amount} is unpaid. Your plan will be cancelled on {cancel} unless it is paid.",
                "After that your organisation moves to the Starter plan.",
            ]
    elif kind == "cancelled":
        subject = "Your Clew plan was cancelled"
        heading = "Your Clew plan was cancelled"
        if bill is not None:
            amount = format_money(bill.amount_paise, bill.currency)
            plan = plan_label(bill.tier, bill.period)
            lines = [
                f"Your {plan} plan was cancelled because the bill of {amount} was not paid.",
                "Your organisation is now on the Starter plan. Your data keeps the retention of your "
                "previous plan for 30 days.",
                "You can pay your open bills and restore your plan from the billing page.",
            ]
        else:
            lines = [
                "Your plan was cancelled at the end of your billing period, as you asked.",
                "Your organisation is now on the Starter plan. Your data keeps the retention of your "
                "previous plan for 30 days.",
            ]
    elif kind == "pilot_ended":
        subject = "Your Clew pilot has ended"
        heading = "Your Clew pilot has ended"
        lines = [
            "Your Clew pilot has ended and your organisation is now on the Starter plan.",
            "Automatic blocking is switched off. IPs that are already blocked stay blocked, and you can "
            "still unblock them. Your data keeps the retention of your pilot plan for 30 days.",
            "To keep the Growth features, choose a plan from the billing page.",
        ]
    elif kind == "payment_received":
        if payment is None:
            raise ValueError("payment_received needs a payment")
        amount = format_money(payment.amount_paise, payment.currency)
        what = (payment.line_items or {}).get("description") or "your Clew plan"
        subject = f"We received your payment of {amount}"
        heading = "Payment received"
        lines = [f"We received your payment of {amount} for {what}. Thank you."]
        if payment.razorpay_payment_id:
            lines.append(f"Payment ID: {payment.razorpay_payment_id}")
        lines.append("Your receipt is in the billing page.")
    else:
        raise ValueError(f"unknown billing email kind: {kind!r}")

    text = "\n\n".join(lines) + f"\n\nView billing: {BILLING_URL}"
    body = "".join(_p(html.escape(line)) for line in lines) + _link()
    footer = f"You are receiving this as a billing contact for {html.escape(org.company_name or 'your organisation')}."
    return subject, text, _email_html(heading, body, footer_note=footer)


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_billing_emails(db, kind: str, org: Organization, bill=None, payment=None) -> int:
    """Render and send one billing email to every recipient. Returns how many
    were accepted for delivery. Never raises for a failed send."""
    recipients = resolve_billing_recipients(org, db, always_owners=kind in ALWAYS_OWNER_KINDS)
    if not recipients:
        logger.warning("billing email %s: org %s has no recipients", kind, org.id)
        return 0
    subject, text, body_html = render_billing_email(kind, org, bill, payment)
    sent = 0
    for address in recipients:
        ok = send_email(
            to=address,
            subject=subject,
            body_text=text,
            body_html=body_html,
            from_address=FROM_BILLING,
            reply_to=REPLY_TO_BILLING,
        )
        sent += 1 if ok else 0
        if not ok:
            logger.error("billing email %s to org %s recipient failed", kind, org.id)
    return sent
