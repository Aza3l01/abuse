"""api/routes/billing.py: Stripe + Razorpay subscription management.

Stripe (USD, deferred to Month 2/3 per item 29, kept in place, untouched):
  GET  /billing/status    → current tier and subscription metadata
  POST /billing/checkout  → create Stripe Checkout Session, return redirect URL
  POST /billing/portal    → create Stripe Customer Portal Session, return redirect URL
  POST /billing/webhook   → Stripe signature-verified event handler (no auth cookie)

Razorpay (INR, item 29, MVP scope, primary provider for now):
  POST /billing/razorpay/create-subscription → create a Razorpay Subscription
  POST /billing/razorpay/verify-payment      → verify checkout.js callback, activate tier
  POST /billing/razorpay/webhook              → signature-verified event handler (no auth cookie)

Shared (item 29b):
  POST /billing/refund-eligibility → {eligible, reason, window_expires_at}
  POST /billing/cancel             → cancel, refunding only within the 72hr remorse window

Tier lifecycle (sole source of truth is this file + the two webhooks):
  signup                                    → tier = "starter" (trial, see item 11)
  checkout.session.completed (Stripe)       → tier = <purchased tier>
  razorpay verify-payment / subscription.activated → tier = <purchased tier>
  customer.subscription.updated/deleted (non-active) → tier = "free"
  razorpay subscription.cancelled                     → tier = "free"
  invoice.payment_failed / payment.failed             → logged + emailed only
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import razorpay
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth_utils import send_payment_failed_email
from api.deps import CurrentOrg, get_current_client, get_current_org, get_db, require_role
from db.models import Client, Organization, OrganizationMember
from db.session import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


# ---------------------------------------------------------------------------
# Stripe init
# ---------------------------------------------------------------------------

def _init_stripe() -> None:
    """Set stripe.api_key from env. Safe to call on every request."""
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise HTTPException(503, "Stripe is not configured on this server.")
    stripe.api_key = key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PRICE_ENV: dict[tuple[str, str], str] = {
    ("starter", "INR"): "STRIPE_PRICE_STARTER_INR",
    ("starter", "USD"): "STRIPE_PRICE_STARTER_USD",
    ("growth",  "INR"): "STRIPE_PRICE_GROWTH_INR",
    ("growth",  "USD"): "STRIPE_PRICE_GROWTH_USD",
    ("pro",     "INR"): "STRIPE_PRICE_PRO_INR",
    ("pro",     "USD"): "STRIPE_PRICE_PRO_USD",
}


def _price_id(tier: str, currency: str) -> str:
    env_var = _PRICE_ENV.get((tier.lower(), currency.upper()))
    if not env_var:
        raise HTTPException(400, f"Unknown tier/currency combination: {tier}/{currency}")
    pid = os.environ.get(env_var, "")
    if not pid:
        raise HTTPException(503, f"Stripe price not configured ({env_var}).")
    return pid


def _org_by_customer(customer_id: str, db: Session) -> Organization | None:
    return (
        db.query(Organization)
        .filter(Organization.stripe_customer_id == customer_id)
        .first()
    )


# ---------------------------------------------------------------------------
# GET /billing/status
#
# Billing is owner-only (item 8: admin has no billing tab).
# ---------------------------------------------------------------------------

class BillingStatusOut(BaseModel):
    tier: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    razorpay_subscription_id: str | None
    tier_expires_at: str | None
    trial_source: str | None
    trial_ends_at: str | None
    billing_provider: str | None
    payment_method_display: str | None
    next_billing_date: str | None


@router.get("/status", response_model=BillingStatusOut)
def billing_status(current_org: CurrentOrg = Depends(require_role("owner"))):
    org = current_org.organization
    return BillingStatusOut(
        tier=org.tier,
        stripe_customer_id=org.stripe_customer_id,
        stripe_subscription_id=org.stripe_subscription_id,
        razorpay_subscription_id=org.razorpay_subscription_id,
        tier_expires_at=(
            org.tier_expires_at.isoformat() if org.tier_expires_at else None
        ),
        trial_source=org.trial_source,
        trial_ends_at=org.trial_ends_at.isoformat() if org.trial_ends_at else None,
        billing_provider=org.billing_provider,
        payment_method_display=org.payment_method_display,
        next_billing_date=org.next_billing_date.isoformat() if org.next_billing_date else None,
    )


# ---------------------------------------------------------------------------
# POST /billing/checkout
# ---------------------------------------------------------------------------

class CheckoutBody(BaseModel):
    tier: str      # "starter" | "growth" | "pro"
    currency: str  # "INR" | "USD"


class UrlOut(BaseModel):
    url: str


@router.post("/checkout", response_model=UrlOut)
def create_checkout(
    body: CheckoutBody,
    current_org: CurrentOrg = Depends(require_role("owner")),
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    _init_stripe()
    org = current_org.organization
    price_id = _price_id(body.tier, body.currency)
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")

    # Reuse existing Stripe customer record if present
    customer_id = org.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            email=client.email,
            name=org.company_name,
            metadata={"clew_org_id": org.id},
        )
        customer_id = customer.id
        db.query(Organization).filter(Organization.id == org.id).update(
            {"stripe_customer_id": customer_id}
        )
        db.commit()

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{frontend_url}/dashboard/settings?upgraded=1",
        cancel_url=f"{frontend_url}/dashboard/settings",
        metadata={"clew_org_id": org.id, "tier": body.tier},
    )
    return UrlOut(url=session.url)


# ---------------------------------------------------------------------------
# POST /billing/portal
# ---------------------------------------------------------------------------

@router.post("/portal", response_model=UrlOut)
def create_portal(current_org: CurrentOrg = Depends(require_role("owner"))):
    _init_stripe()
    org = current_org.organization
    if not org.stripe_customer_id:
        raise HTTPException(400, "No active subscription to manage.")
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    session = stripe.billing_portal.Session.create(
        customer=org.stripe_customer_id,
        return_url=f"{frontend_url}/dashboard/settings",
    )
    return UrlOut(url=session.url)


# ---------------------------------------------------------------------------
# POST /billing/webhook  (no auth — called by Stripe, not the browser)
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def stripe_webhook(request: Request):
    _init_stripe()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        logger.error("STRIPE_WEBHOOK_SECRET not set — webhook rejected")
        raise HTTPException(500, "Webhook secret not configured.")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError:
        logger.warning("stripe_webhook: invalid signature")
        raise HTTPException(400, "Invalid webhook signature.")
    except ValueError as exc:
        logger.warning("stripe_webhook: invalid payload: %s", exc)
        raise HTTPException(400, "Invalid payload.")

    db: Session = SessionLocal()
    try:
        _handle_event(event, db)
    except Exception:
        db.rollback()
        logger.exception("stripe_webhook: error processing event %s", event.get("type"))
        raise HTTPException(500, "Internal error processing webhook.")
    finally:
        db.close()

    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Webhook event handler
# ---------------------------------------------------------------------------

def _handle_event(event: dict, db: Session) -> None:
    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        customer_id = obj.get("customer")
        tier = (obj.get("metadata") or {}).get("tier", "")
        sub_id = obj.get("subscription")
        if not (customer_id and tier and sub_id):
            return
        org = _org_by_customer(customer_id, db)
        if not org:
            logger.warning("billing: unknown Stripe customer %s from checkout", customer_id)
            return
        db.query(Organization).filter(Organization.id == org.id).update(
            {"tier": tier, "stripe_subscription_id": sub_id}
        )
        db.commit()
        logger.info("billing: org %s upgraded to %s", org.id, tier)

    elif etype in ("customer.subscription.updated", "customer.subscription.deleted"):
        customer_id = obj.get("customer")
        if not customer_id:
            return
        status = obj.get("status", "")
        org = _org_by_customer(customer_id, db)
        if not org:
            return
        if status not in ("active", "trialing"):
            # Subscription canceled, past_due, or unpaid — revert to free
            db.query(Organization).filter(Organization.id == org.id).update(
                {"tier": "free", "stripe_subscription_id": None, "tier_expires_at": None}
            )
            db.commit()
            logger.info(
                "billing: org %s downgraded to free (status=%s)", org.id, status
            )

    elif etype == "invoice.payment_failed":
        # Stripe auto-retries; actual downgrade fires via subscription.updated
        customer_id = obj.get("customer")
        if customer_id:
            org = _org_by_customer(customer_id, db)
            if org:
                logger.warning("billing: payment failed for org %s", org.id)


# ---------------------------------------------------------------------------
# Razorpay init + shared helpers
# ---------------------------------------------------------------------------

_RAZORPAY_PLAN_ENV: dict[tuple[str, str], str] = {
    ("starter", "monthly"): "RAZORPAY_PLAN_STARTER_MONTHLY_INR",
    ("starter", "annual"):  "RAZORPAY_PLAN_STARTER_ANNUAL_INR",
    ("growth",  "monthly"): "RAZORPAY_PLAN_GROWTH_MONTHLY_INR",
    ("growth",  "annual"):  "RAZORPAY_PLAN_GROWTH_ANNUAL_INR",
    ("pro",     "monthly"): "RAZORPAY_PLAN_PRO_MONTHLY_INR",
    ("pro",     "annual"):  "RAZORPAY_PLAN_PRO_ANNUAL_INR",
}

# Upgrade/downgrade decision (item 29): no plan-change endpoint exists on
# Razorpay subscriptions, so a tier change is always cancel-old + create-new.
_TIER_RANK = {"free": 0, "starter": 1, "growth": 2, "pro": 3}


def _init_razorpay() -> "razorpay.Client":
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not (key_id and key_secret):
        raise HTTPException(503, "Razorpay is not configured on this server.")
    return razorpay.Client(auth=(key_id, key_secret))


def _razorpay_plan_id(tier: str, period: str) -> str:
    env_var = _RAZORPAY_PLAN_ENV.get((tier.lower(), period.lower()))
    if not env_var:
        raise HTTPException(400, f"Unknown tier/period combination: {tier}/{period}")
    pid = os.environ.get(env_var, "")
    if not pid:
        raise HTTPException(503, f"Razorpay plan not configured ({env_var}).")
    return pid


def _org_by_razorpay_subscription(sub_id: str, db: Session) -> Organization | None:
    return (
        db.query(Organization)
        .filter(Organization.razorpay_subscription_id == sub_id)
        .first()
    )


def _owner_emails(db: Session, org_id: str) -> list[str]:
    rows = (
        db.query(Client.email)
        .join(OrganizationMember, OrganizationMember.client_id == Client.id)
        .filter(OrganizationMember.org_id == org_id, OrganizationMember.role == "owner")
        .all()
    )
    return [r[0] for r in rows]


def _next_calendar_anchor_start_at(now: datetime) -> int | None:
    """Item 29b: added on/before the 15th: charge immediately (None). Added
    after the 15th: defer to the 1st of next calendar month, 00:00 UTC."""
    if now.day <= 15:
        return None
    if now.month == 12:
        next_month_start = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        next_month_start = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(next_month_start.timestamp())


def _payment_method_display(payment: dict) -> str | None:
    method = payment.get("method", "")
    if method == "upi":
        vpa = payment.get("vpa", "")
        return f"UPI • {vpa}" if vpa else "UPI"
    if method == "card":
        card = payment.get("card") or {}
        network = card.get("network", "Card")
        last4 = card.get("last4", "")
        return f"{network} •••• {last4}" if last4 else network
    if method:
        return method.capitalize()
    return None


def _refund_eligibility(org: Organization) -> tuple[bool, str, datetime | None]:
    """Item 29b refund rules. Returns (eligible, reason, window_expires_at)."""
    if org.first_charged_at is None:
        return True, "pre_charge", None
    window_expires_at = org.first_charged_at + timedelta(hours=72)
    if datetime.now(timezone.utc) <= window_expires_at:
        return True, "remorse_window", window_expires_at
    return False, "not_eligible", None


# ---------------------------------------------------------------------------
# POST /billing/razorpay/create-subscription
# ---------------------------------------------------------------------------

class RazorpaySubscriptionBody(BaseModel):
    tier: str      # "starter" | "growth" | "pro"
    period: str    # "monthly" | "annual"
    gstin: str | None = None


class RazorpaySubscriptionOut(BaseModel):
    subscription_id: str
    key_id: str


@router.post("/razorpay/create-subscription", response_model=RazorpaySubscriptionOut)
def razorpay_create_subscription(
    body: RazorpaySubscriptionBody,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    tier = body.tier.lower()
    period = body.period.lower()
    if tier not in _TIER_RANK or tier == "free":
        raise HTTPException(400, f"Unknown tier: {body.tier}")
    if period not in ("monthly", "annual"):
        raise HTTPException(400, f"Unknown period: {body.period}")

    # Item 28: Growth requires the blocking TOS to already be accepted:
    # the frontend shows the modal and posts acceptance before calling here.
    if tier == "growth" and org.blocking_tos_accepted_at is None:
        raise HTTPException(403, "Accept the Growth Subscription Agreement before continuing.")

    rp = _init_razorpay()
    plan_id = _razorpay_plan_id(tier, period)

    is_first_payment_method = (
        org.razorpay_subscription_id is None and org.billing_provider in (None, "pilot")
    )

    old_sub_id = org.razorpay_subscription_id
    if is_first_payment_method:
        start_at = _next_calendar_anchor_start_at(datetime.now(timezone.utc))
    else:
        is_upgrade = _TIER_RANK.get(tier, 0) > _TIER_RANK.get(org.tier, 0)
        start_at = None
        if old_sub_id:
            try:
                old_sub = rp.subscription.fetch(old_sub_id)
            except Exception:
                logger.exception("billing: failed to fetch old Razorpay subscription %s", old_sub_id)
                old_sub = {}
            if is_upgrade:
                # Upgrade: new plan starts immediately, no refund on the old one.
                try:
                    rp.subscription.cancel(old_sub_id, {"cancel_at_cycle_end": 0})
                except Exception:
                    logger.exception("billing: failed to cancel old Razorpay subscription %s", old_sub_id)
            else:
                # Downgrade: old plan runs to cycle end, new one scheduled to start then.
                try:
                    rp.subscription.cancel(old_sub_id, {"cancel_at_cycle_end": 1})
                except Exception:
                    logger.exception("billing: failed to schedule cancel on Razorpay subscription %s", old_sub_id)
                start_at = old_sub.get("current_end")

    if body.gstin:
        org.gstin = body.gstin.strip()

    sub_params: dict = {
        "plan_id": plan_id,
        "customer_notify": 1,
        # Total billing cycles Razorpay will run before requiring renewal setup.
        "total_count": 120 if period == "monthly" else 10,
        "notes": {"clew_org_id": org.id, "tier": tier, "gstin": org.gstin or ""},
    }
    if start_at:
        sub_params["start_at"] = start_at

    try:
        subscription = rp.subscription.create(sub_params)
    except Exception:
        logger.exception("billing: Razorpay subscription creation failed for org %s", org.id)
        raise HTTPException(502, "Could not start Razorpay checkout. Please try again.")

    org.razorpay_subscription_id = subscription["id"]
    db.commit()

    return RazorpaySubscriptionOut(subscription_id=subscription["id"], key_id=os.environ.get("RAZORPAY_KEY_ID", ""))


# ---------------------------------------------------------------------------
# POST /billing/razorpay/verify-payment
# ---------------------------------------------------------------------------

class RazorpayVerifyBody(BaseModel):
    tier: str
    razorpay_payment_id: str
    razorpay_subscription_id: str
    razorpay_signature: str


@router.post("/razorpay/verify-payment", response_model=BillingStatusOut)
def razorpay_verify_payment(
    body: RazorpayVerifyBody,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    if body.razorpay_subscription_id != org.razorpay_subscription_id:
        raise HTTPException(400, "Subscription mismatch.")

    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not key_secret:
        raise HTTPException(503, "Razorpay is not configured on this server.")
    payload = f"{body.razorpay_payment_id}|{body.razorpay_subscription_id}"
    expected_signature = hmac.new(key_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, body.razorpay_signature):
        raise HTTPException(400, "Payment verification failed.")

    rp = _init_razorpay()
    now = datetime.now(timezone.utc)
    try:
        payment = rp.payment.fetch(body.razorpay_payment_id)
    except Exception:
        logger.exception("billing: failed to fetch Razorpay payment %s", body.razorpay_payment_id)
        payment = {}
    try:
        subscription = rp.subscription.fetch(body.razorpay_subscription_id)
    except Exception:
        logger.exception("billing: failed to fetch Razorpay subscription %s", body.razorpay_subscription_id)
        subscription = {}

    org.tier = body.tier.lower()
    org.billing_provider = "razorpay"
    org.payment_method_display = _payment_method_display(payment) or org.payment_method_display
    if payment.get("customer_id"):
        org.razorpay_customer_id = payment["customer_id"]
    if org.first_charged_at is None:
        org.first_charged_at = now
    current_end = subscription.get("current_end")
    if current_end:
        org.next_billing_date = datetime.fromtimestamp(current_end, tz=timezone.utc)
    db.commit()

    return BillingStatusOut(
        tier=org.tier,
        stripe_customer_id=org.stripe_customer_id,
        stripe_subscription_id=org.stripe_subscription_id,
        razorpay_subscription_id=org.razorpay_subscription_id,
        tier_expires_at=org.tier_expires_at.isoformat() if org.tier_expires_at else None,
        trial_source=org.trial_source,
        trial_ends_at=org.trial_ends_at.isoformat() if org.trial_ends_at else None,
        billing_provider=org.billing_provider,
        payment_method_display=org.payment_method_display,
        next_billing_date=org.next_billing_date.isoformat() if org.next_billing_date else None,
    )


# ---------------------------------------------------------------------------
# POST /billing/razorpay/webhook  (no auth, called by Razorpay, not the browser)
# ---------------------------------------------------------------------------

@router.post("/razorpay/webhook")
async def razorpay_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("x-razorpay-signature", "")
    webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not webhook_secret:
        logger.error("RAZORPAY_WEBHOOK_SECRET not set, webhook rejected")
        raise HTTPException(500, "Webhook secret not configured.")

    expected_signature = hmac.new(webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, sig_header):
        logger.warning("razorpay_webhook: invalid signature")
        raise HTTPException(400, "Invalid webhook signature.")

    try:
        event = json.loads(payload)
    except ValueError:
        raise HTTPException(400, "Invalid payload.")

    db: Session = SessionLocal()
    try:
        _handle_razorpay_event(event, db)
    except Exception:
        db.rollback()
        logger.exception("razorpay_webhook: error processing event %s", event.get("event"))
        raise HTTPException(500, "Internal error processing webhook.")
    finally:
        db.close()

    return Response(status_code=200)


def _handle_razorpay_event(event: dict, db: Session) -> None:
    etype = event.get("event", "")
    payload = event.get("payload", {})
    now = datetime.now(timezone.utc)

    if etype == "subscription.activated":
        entity = (payload.get("subscription") or {}).get("entity", {})
        sub_id = entity.get("id")
        if not sub_id:
            return
        org = _org_by_razorpay_subscription(sub_id, db)
        if not org:
            logger.warning("billing: unknown Razorpay subscription %s from webhook", sub_id)
            return
        tier = (entity.get("notes") or {}).get("tier")
        if tier:
            org.tier = tier
        org.billing_provider = "razorpay"
        current_end = entity.get("current_end")
        if current_end:
            org.next_billing_date = datetime.fromtimestamp(current_end, tz=timezone.utc)
        if org.first_charged_at is None:
            org.first_charged_at = now
        db.commit()
        logger.info("billing: org %s Razorpay subscription activated (tier=%s)", org.id, org.tier)

    elif etype == "subscription.halted":
        entity = (payload.get("subscription") or {}).get("entity", {})
        sub_id = entity.get("id")
        if not sub_id:
            return
        org = _org_by_razorpay_subscription(sub_id, db)
        if not org:
            return
        logger.warning("billing: Razorpay subscription %s halted for org %s", sub_id, org.id)
        for email in _owner_emails(db, org.id):
            send_payment_failed_email(email)

    elif etype == "subscription.cancelled":
        entity = (payload.get("subscription") or {}).get("entity", {})
        sub_id = entity.get("id")
        if not sub_id:
            return
        org = _org_by_razorpay_subscription(sub_id, db)
        if not org:
            return
        org.tier = "free"
        org.razorpay_subscription_id = None
        org.next_billing_date = None
        db.commit()
        logger.info("billing: org %s downgraded to free (Razorpay subscription cancelled)", org.id)

    elif etype == "payment.failed":
        entity = (payload.get("payment") or {}).get("entity", {})
        sub_id = entity.get("subscription_id") if entity else None
        if not sub_id:
            return
        org = _org_by_razorpay_subscription(sub_id, db)
        if org:
            logger.warning("billing: Razorpay payment failed for org %s", org.id)
            for email in _owner_emails(db, org.id):
                send_payment_failed_email(email)


# ---------------------------------------------------------------------------
# POST /billing/refund-eligibility, POST /billing/cancel   (item 29b)
# ---------------------------------------------------------------------------

class RefundEligibilityOut(BaseModel):
    eligible: bool
    reason: str  # "pre_charge" | "remorse_window" | "not_eligible"
    window_expires_at: str | None


@router.post("/refund-eligibility", response_model=RefundEligibilityOut)
def refund_eligibility(current_org: CurrentOrg = Depends(require_role("owner"))):
    eligible, reason, window_expires_at = _refund_eligibility(current_org.organization)
    return RefundEligibilityOut(
        eligible=eligible,
        reason=reason,
        window_expires_at=window_expires_at.isoformat() if window_expires_at else None,
    )


class CancelOut(BaseModel):
    status: str
    refunded: bool
    reason: str


def _cancel_razorpay_subscription_core(org: Organization, db: Session, *, immediate: bool) -> CancelOut:
    """Shared Razorpay cancel logic (item 29b), reused by both the self-serve
    POST /billing/cancel route and account deletion (item 40, `immediate=True`).

    `immediate=True` always cancels right away regardless of refund
    eligibility, since a deleted account shouldn't keep being billed until a
    cycle end its owner can no longer log in to see.
    """
    rp = _init_razorpay()
    eligible, reason, _ = _refund_eligibility(org)
    sub_id = org.razorpay_subscription_id
    refunded = False

    if reason == "pre_charge":
        # Nothing has ever been charged: cancel outright, nothing to refund.
        try:
            rp.subscription.cancel(sub_id, {"cancel_at_cycle_end": 0})
        except Exception:
            logger.exception("billing: failed to cancel pre-charge Razorpay subscription %s", sub_id)
        org.razorpay_subscription_id = None

    elif reason == "remorse_window":
        # Full refund on the first payment, one-time only (item 29b point 2).
        try:
            invoices = rp.invoice.all({"subscription_id": sub_id}).get("items", [])
            paid = [inv for inv in invoices if inv.get("status") == "paid" and inv.get("payment_id")]
            paid.sort(key=lambda inv: inv.get("paid_at") or 0, reverse=True)
            if paid:
                rp.payment.refund(paid[0]["payment_id"], {})
                refunded = True
            else:
                logger.warning("billing: remorse-window cancel for org %s found no paid invoice to refund, refund needs manual dashboard action", org.id)
        except Exception:
            logger.exception("billing: refund failed for org %s, refund needs manual dashboard action", org.id)
        try:
            rp.subscription.cancel(sub_id, {"cancel_at_cycle_end": 0})
        except Exception:
            logger.exception("billing: failed to cancel Razorpay subscription %s", sub_id)
        org.tier = "free"
        org.razorpay_subscription_id = None
        org.billing_provider = None
        org.next_billing_date = None

    else:
        # Past the remorse window, or a later renewal: no refund. Self-serve
        # cancel leaves access until the paid cycle ends; account deletion
        # always cancels right away instead.
        try:
            rp.subscription.cancel(sub_id, {"cancel_at_cycle_end": 0 if immediate else 1})
        except Exception:
            logger.exception("billing: failed to cancel Razorpay subscription %s", sub_id)
        if immediate:
            org.razorpay_subscription_id = None

    return CancelOut(status="cancelled", refunded=refunded, reason=reason)


@router.post("/cancel", response_model=CancelOut)
def cancel_subscription(
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    if not org.razorpay_subscription_id:
        raise HTTPException(400, "No active subscription to cancel.")

    result = _cancel_razorpay_subscription_core(org, db, immediate=False)
    db.commit()
    return result


def _cancel_stripe_subscription_now(org: Organization) -> None:
    """Immediate Stripe subscription cancel. Called directly (not via an
    authenticated HTTP route) by account deletion (item 40), since there is
    no self-serve Stripe cancel endpoint, Stripe subscribers otherwise manage
    cancellation via the customer portal instead."""
    if not org.stripe_subscription_id:
        return
    _init_stripe()
    try:
        stripe.Subscription.delete(org.stripe_subscription_id)
    except Exception:
        logger.exception(
            "billing: failed to cancel Stripe subscription %s for org %s",
            org.stripe_subscription_id, org.id,
        )
    org.stripe_subscription_id = None
    org.tier = "free"


def cancel_org_subscriptions_for_deletion(org: Organization, db: Session) -> None:
    """Item 40: cancel whatever active subscription an org has. Called
    directly by account deletion (api/routes/auth.py), not through the
    authenticated HTTP routes above."""
    if org.razorpay_subscription_id:
        _cancel_razorpay_subscription_core(org, db, immediate=True)
    if org.stripe_subscription_id:
        _cancel_stripe_subscription_now(org)



