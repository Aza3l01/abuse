"""api/routes/billing.py: Stripe + Razorpay billing routes.

Stripe (USD, deferred, kept in place, untouched):
  POST /billing/checkout  → create Stripe Checkout Session, return redirect URL
  POST /billing/portal    → create Stripe Customer Portal Session, return redirect URL
  POST /billing/webhook   → Stripe signature-verified event handler (no auth cookie)

Razorpay (INR or USD, Orders API only, bill-then-pay; the rules live in
api/billing_payments.py and api/billing_rules.py):
  POST /billing/razorpay/create-order   → price a purchase server-side, create a Payment + order
  POST /billing/razorpay/verify-payment → check the checkout.js signature, apply the captured payment
  POST /billing/razorpay/webhook        → payment.captured / payment.failed / refund.processed

Owner-only plan management:
  GET  /billing/status             → plan, currency, open bills, payment history, details, refund eligibility
  GET  /billing/payments/{id}      → receipt data for one captured or refunded payment
  POST /billing/quote              → the exact amount a purchase would charge, nothing is created
  PUT  /billing/details            → billing legal name, address, GSTIN, billing country (set once)
  GET/PUT /billing/notifications   → who receives billing emails, and whether routine reminders are on
  POST /billing/schedule-downgrade → lower tier or annual to monthly, applied at the next bill
  POST /billing/cancel             → cancel at the end of the paid period
  POST /billing/undo-pending       → withdraw a scheduled cancel or downgrade
  POST /billing/refund-eligibility → {eligible, reason, window_expires_at}
  POST /billing/refund             → full refund inside the 72 hour window

Any member (viewers included):
  GET  /billing/banner             → the small subset the dashboard banner needs

Referrals (api/referrals.py, a credit ledger, no discount on charges):
  GET /billing/referral-status → this org's own code, its free bill state and its referral credits
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Literal

import razorpay
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.billing_notify import notify
from api.billing_payments import (
    REFUND_WINDOW,
    apply_captured_payment,
    bill_summary,
    lock_billing_currency,
    min_order_minor,
    on_paid_plan,
    open_bills,
    plan_for_order,
    plan_label,
    refund_window,
    resolve_currency,
)
from api.billing_rules import PERIODS, classify_change, today_ist
from api.deps import CurrentOrg, get_current_client, get_current_org, get_db, require_role
from api.referrals import referral_summary, revoke_for_refunded_referee
from api.tiers import PURCHASABLE_PLANS, plan_price
from db.models import Client, Organization, Payment, ProcessedWebhookEvent
from db.session import SessionLocal
from workers.tasks.billing_cycle import downgrade_org

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
    ("basic",   "INR"): "STRIPE_PRICE_BASIC_INR",
    ("basic",   "USD"): "STRIPE_PRICE_BASIC_USD",
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
# GET /billing/status (owner only) and GET /billing/banner (any member)
#
# Billing is owner-only (item 8: admin has no billing tab). The banner shows
# the same states to every role, so its small subset sits on a route that only
# needs a logged-in member, never on the owner-only one.
# ---------------------------------------------------------------------------

def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


class RefundEligibilityOut(BaseModel):
    eligible: bool
    reason: str  # remorse_window | already_refunded | not_eligible | no_payment
    window_expires_at: str | None


class BillingStatusOut(BaseModel):
    tier: str
    billing_currency: str
    billing_country: str | None
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    tier_expires_at: str | None
    trial_source: str | None
    trial_ends_at: str | None
    billing_provider: str | None
    payment_method_display: str | None
    next_billing_date: str | None
    # What the next bill will be, in minor units of billing_currency, from the
    # plan that will be billed then (a scheduled downgrade counts). None when
    # nothing will be billed: no paid plan, or a cancel is scheduled.
    next_bill_amount_paise: int | None
    next_bill_plan: str | None
    billing_period: str | None
    cancel_at_period_end: bool
    pending_tier: str | None
    pending_period: str | None
    nonpayment_downgraded_at: str | None
    retention_grace_until: str | None
    open_bills: list[dict]
    payments: list[dict]
    billing_details: dict
    refund: RefundEligibilityOut


def _refund_out(org_id: str, db: Session) -> RefundEligibilityOut:
    window = refund_window(org_id, db)
    return RefundEligibilityOut(
        eligible=window.eligible,
        reason=window.reason,
        window_expires_at=_iso(window.expires_at),
    )


def _payment_row(p: Payment) -> dict:
    return {
        "id": p.id,
        "purpose": p.purpose,
        "description": (p.line_items or {}).get("description"),
        "amount_paise": p.amount_paise,
        "currency": p.currency,
        "status": p.status,
        "created_at": _iso(p.created_at),
        "captured_at": _iso(p.captured_at),
        "refunded_at": _iso(p.refunded_at),
    }


def _billing_details(org: Organization) -> dict:
    return {
        "legal_name": org.billing_legal_name,
        "address": org.billing_address,
        "gstin": org.gstin,
        "billing_country": org.billing_country,
    }


def _next_bill(org: Organization) -> tuple[int | None, str | None]:
    """(amount in minor units, plan label) of the next bill, or (None, None)."""
    if org.billing_provider == "stripe" or not on_paid_plan(org) or org.cancel_at_period_end:
        return None, None
    tier = org.pending_tier or org.tier
    period = org.pending_period or org.billing_period
    if (tier, period) not in PURCHASABLE_PLANS:
        return None, None
    return plan_price(org.billing_currency, tier, period), plan_label(tier, period)


@router.get("/status", response_model=BillingStatusOut)
def billing_status(
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    payments = (
        db.query(Payment)
        .filter(Payment.org_id == org.id, Payment.status.in_(("captured", "refunded", "failed")))
        .order_by(Payment.created_at.desc())
        .limit(50)
        .all()
    )
    next_amount, next_plan = _next_bill(org)
    return BillingStatusOut(
        tier=org.tier,
        billing_currency=org.billing_currency,
        billing_country=org.billing_country,
        stripe_customer_id=org.stripe_customer_id,
        stripe_subscription_id=org.stripe_subscription_id,
        tier_expires_at=_iso(org.tier_expires_at),
        trial_source=org.trial_source,
        trial_ends_at=_iso(org.trial_ends_at),
        billing_provider=org.billing_provider,
        payment_method_display=org.payment_method_display,
        next_billing_date=_iso(org.next_billing_date),
        next_bill_amount_paise=next_amount,
        next_bill_plan=next_plan,
        billing_period=org.billing_period,
        cancel_at_period_end=bool(org.cancel_at_period_end),
        pending_tier=org.pending_tier,
        pending_period=org.pending_period,
        nonpayment_downgraded_at=_iso(org.nonpayment_downgraded_at),
        retention_grace_until=_iso(org.retention_grace_until),
        open_bills=[bill_summary(b) for b in open_bills(org.id, db)],
        payments=[_payment_row(p) for p in payments],
        billing_details=_billing_details(org),
        refund=_refund_out(org.id, db),
    )


class BannerOut(BaseModel):
    tier: str
    role: str
    billing_currency: str
    billing_provider: str | None
    billing_period: str | None
    trial_ends_at: str | None
    next_billing_date: str | None
    cancel_at_period_end: bool
    nonpayment_downgraded_at: str | None
    retention_grace_until: str | None
    # Today's date in IST, so the banner never decides "overdue" from the
    # browser's clock or time zone (bills are due on IST calendar dates).
    today_ist: str
    open_bills: list[dict]


@router.get("/banner", response_model=BannerOut)
def billing_banner(
    current_org: CurrentOrg = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    return BannerOut(
        tier=org.tier,
        role=current_org.role,
        billing_currency=org.billing_currency,
        billing_provider=org.billing_provider,
        billing_period=org.billing_period,
        trial_ends_at=_iso(org.trial_ends_at),
        next_billing_date=_iso(org.next_billing_date),
        cancel_at_period_end=bool(org.cancel_at_period_end),
        nonpayment_downgraded_at=_iso(org.nonpayment_downgraded_at),
        retention_grace_until=_iso(org.retention_grace_until),
        today_ist=today_ist().isoformat(),
        open_bills=[bill_summary(b) for b in open_bills(org.id, db)],
    )


# ---------------------------------------------------------------------------
# GET /billing/referral-status (TODO.md priority item 5)
#
# Owner-only, same convention as every other billing route. Dashboard
# reads this live on every load, never caches slot count or discount.
# ---------------------------------------------------------------------------

class ReferralCreditOut(BaseModel):
    id: str
    status: str  # pending | available | applied
    amount_paise: int
    currency: str
    earned_at: str | None
    releases_at: str | None  # pending credits: when the referee's refund window ends
    vests_at: str | None
    applied_at: str | None


class ReferralTotalsOut(BaseModel):
    pending: int
    available: int
    applied: int


class ReferralStatusOut(BaseModel):
    referral_code: str | None
    credit_pct: int
    is_referred: bool
    referred_state: str | None  # waiting_for_first_payment | waiting_for_first_bill | applied
    free_bill_paise: int | None
    free_bill_currency: str | None
    plan_monthly_paise: int | None  # list price of this org's plan, None on the free plan
    plan_currency: str | None
    signups: int
    paying: int
    totals: dict[str, ReferralTotalsOut]  # by currency
    credits: list[ReferralCreditOut]


@router.get("/referral-status", response_model=ReferralStatusOut)
def billing_referral_status(
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    return ReferralStatusOut(**referral_summary(current_org.organization, db))


# ---------------------------------------------------------------------------
# POST /billing/checkout
# ---------------------------------------------------------------------------

class CheckoutBody(BaseModel):
    tier: str      # "basic" | "growth" | "pro"
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
    dashboard_url = os.environ.get("DASHBOARD_URL", "http://localhost:3000")

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
        success_url=f"{dashboard_url}/settings?upgraded=1",
        cancel_url=f"{dashboard_url}/settings",
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
    dashboard_url = os.environ.get("DASHBOARD_URL", "http://localhost:3000")
    session = stripe.billing_portal.Session.create(
        customer=org.stripe_customer_id,
        return_url=f"{dashboard_url}/settings",
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
        # Item 62: insert-before-dispatch idempotency guard. A verified
        # payload can still be replayed, and Stripe itself retries on a
        # non-2xx response, so re-applying the same event's side effects
        # (tier change, etc.) more than once is a real risk without this.
        if not _record_webhook_event(db, "stripe", event.get("id", "")):
            logger.info("stripe_webhook: duplicate event %s, skipping", event.get("id"))
            return Response(status_code=200)
        _handle_event(event, db)
        # Belt-and-suspenders: some event branches take no DB-writing action
        # of their own (no internal db.commit()), commit here too so the
        # processed-event row above is never silently rolled back on close.
        db.commit()
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

def _record_webhook_event(db: Session, provider: str, event_id: str) -> bool:
    """Item 62: replay/idempotency guard, insert-before-dispatch. Returns True
    if this event has not been processed before (caller should proceed to
    dispatch its side effects), False if it is a replay (caller should
    return 200 without re-applying anything). A verified payload can still
    be replayed verbatim, and both Razorpay and Stripe retry on a non-2xx
    response, so signature verification alone does not prevent double
    application of a tier change or other side effect.

    Uses the same db session/transaction the caller's _handle*_event will
    commit, so the inserted row and that event's side effects land together.
    """
    if not event_id:
        # No id to dedupe on: log and let it through rather than silently
        # dropping a potentially-real event with a missing identifier.
        logger.warning("%s webhook: event with no id, cannot dedupe", provider)
        return True
    try:
        db.add(ProcessedWebhookEvent(provider=provider, event_id=event_id))
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


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
                {"tier": "starter", "stripe_subscription_id": None, "tier_expires_at": None}
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

def _init_razorpay() -> "razorpay.Client":
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not (key_id and key_secret):
        raise HTTPException(503, "Razorpay is not configured on this server.")
    return razorpay.Client(auth=(key_id, key_secret))


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


# ---------------------------------------------------------------------------
# POST /billing/razorpay/create-order
# ---------------------------------------------------------------------------

# Item 6e: two digits (state code), ten characters (PAN), one character
# (entity number), the letter Z, one character (checksum).
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


class CreateOrderBody(BaseModel):
    purpose: str  # initial | upgrade | bill | restore
    tier: str | None = None
    period: str | None = None
    bill_id: str | None = None
    accept_blocking_tos: bool = False
    # Required for any annual purchase (initial, upgrade, restore): annual
    # plans are non-refundable. Recorded on the Payment as evidence.
    accept_annual_nonrefundable: bool = False
    gstin: str | None = None
    # ISO 3166-1 alpha-2. Required until the org's billing country is set by
    # its first checkout, then fixed (a different value is rejected).
    billing_country: str | None = Field(default=None, max_length=2)


class CreateOrderOut(BaseModel):
    order_id: str
    amount: int  # minor units of `currency` (paise or cents)
    currency: str
    key_id: str
    payment_id: str


def _clean_gstin(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    gstin = raw.strip().upper()
    if not _GSTIN_RE.match(gstin):
        raise HTTPException(400, "That doesn't look like a valid GSTIN. It should be 15 characters: state code, PAN, entity number, Z, and a checksum character.")
    return gstin


@router.post("/razorpay/create-order", response_model=CreateOrderOut)
def razorpay_create_order(
    body: CreateOrderBody,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    purpose = body.purpose.lower()
    tier = body.tier.lower() if body.tier else None
    period = body.period.lower() if body.period else None
    if period is not None and period not in PERIODS:
        raise HTTPException(400, f"Unknown period: {body.period}")
    gstin = _clean_gstin(body.gstin)

    if period == "annual" and purpose != "bill" and not body.accept_annual_nonrefundable:
        raise HTTPException(403, "Acknowledge that annual plans are non-refundable before continuing.")

    plan = plan_for_order(
        org, purpose, tier, period, body.bill_id, body.accept_blocking_tos, db,
        billing_country=body.billing_country,
    )
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")

    if plan.amount_paise < min_order_minor(plan.currency):
        logger.error("billing: computed amount %s %s below the minimum for org %s", plan.amount_paise, plan.currency, org.id)
        raise HTTPException(500, "Could not price this purchase.")

    rp = _init_razorpay()
    payment_id = str(uuid.uuid4())
    try:
        order = rp.order.create({
            "amount": plan.amount_paise,
            "currency": plan.currency,
            "receipt": payment_id,
            "notes": {"org_id": org.id, "purpose": purpose, "payment_id": payment_id},
        })
    except Exception:
        logger.exception("billing: Razorpay order creation failed for org %s", org.id)
        raise HTTPException(502, "Could not start Razorpay checkout. Please try again.")

    # The first checkout fixes the org's billing country and currency for good.
    if plan.billing_country:
        lock_billing_currency(org, plan.currency, plan.billing_country)

    line_items = dict(plan.line_items)
    if period == "annual" and purpose != "bill":
        line_items["annual_nonrefundable_accepted"] = True

    # The order id is required on the row, so the Payment is inserted right after the order exists.
    db.add(Payment(
        id=payment_id,
        org_id=org.id,
        org_name_snapshot=org.company_name,
        razorpay_order_id=order["id"],
        amount_paise=plan.amount_paise,
        currency=plan.currency,
        purpose=purpose,
        status="created",
        line_items=line_items,
        tos_accepted=purpose != "bill" and (body.accept_blocking_tos or org.blocking_tos_accepted_at is not None),
        gstin_snapshot=gstin or org.gstin,
        legal_name_snapshot=org.billing_legal_name,
        address_snapshot=org.billing_address,
    ))
    db.commit()

    return CreateOrderOut(
        order_id=order["id"],
        amount=plan.amount_paise,
        currency=plan.currency,
        key_id=key_id,
        payment_id=payment_id,
    )


# ---------------------------------------------------------------------------
# POST /billing/razorpay/verify-payment
#
# HMAC-SHA256(key_secret, order_id + "|" + payment_id) must match the
# signature from checkout.js. The payment is then fetched from Razorpay and
# must be captured for exactly the stored amount before anything is applied.
# ---------------------------------------------------------------------------

class VerifyPaymentBody(BaseModel):
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    razorpay_signature: str | None = None


class VerifyPaymentOut(BaseModel):
    status: str  # captured
    payment_id: str
    applied: bool  # False when the webhook (or an earlier call) already applied it


def _checkout_signature_ok(order_id: str, payment_id: str, signature: str) -> bool:
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    expected = hmac.new(key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/razorpay/verify-payment", response_model=VerifyPaymentOut)
def razorpay_verify_payment(
    body: VerifyPaymentBody,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    if not (body.razorpay_order_id and body.razorpay_payment_id and body.razorpay_signature):
        raise HTTPException(400, "Missing payment details.")
    if not os.environ.get("RAZORPAY_KEY_SECRET"):
        raise HTTPException(503, "Razorpay is not configured on this server.")
    if not _checkout_signature_ok(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        raise HTTPException(400, "Payment verification failed.")

    payment = (
        db.query(Payment)
        .filter(Payment.razorpay_order_id == body.razorpay_order_id, Payment.org_id == org.id)
        .first()
    )
    if payment is None:
        raise HTTPException(404, "Unknown order.")
    if payment.status in ("captured", "refunded"):
        return VerifyPaymentOut(status="captured", payment_id=payment.id, applied=False)

    rp = _init_razorpay()
    try:
        rz_payment = rp.payment.fetch(body.razorpay_payment_id)
    except Exception:
        logger.exception("billing: failed to fetch Razorpay payment %s", body.razorpay_payment_id)
        raise HTTPException(502, "Could not verify the payment with Razorpay. Please retry shortly.")

    if rz_payment.get("order_id") != body.razorpay_order_id:
        raise HTTPException(400, "Payment verification failed.")
    if rz_payment.get("status") != "captured":
        raise HTTPException(409, "The payment is not captured yet.")
    if rz_payment.get("amount") != payment.amount_paise or rz_payment.get("currency") != payment.currency:
        logger.error(
            "billing: payment %s mismatch, stored %s %s, Razorpay %s %s",
            payment.id, payment.amount_paise, payment.currency,
            rz_payment.get("amount"), rz_payment.get("currency"),
        )
        raise HTTPException(400, "Payment verification failed.")
    _flag_international(payment, rz_payment)

    applied = apply_captured_payment(
        payment, db,
        razorpay_payment_id=body.razorpay_payment_id,
        method_display=_payment_method_display(rz_payment),
    )
    db.commit()
    if applied:
        notify("payment_received", org, payment=payment)
    return VerifyPaymentOut(status="captured", payment_id=payment.id, applied=applied)


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
        # Item 62: same insert-before-dispatch guard as the Stripe webhook.
        # Razorpay sends the event id via the x-razorpay-event-id header.
        event_id = request.headers.get("x-razorpay-event-id", "")
        if not _record_webhook_event(db, "razorpay", event_id):
            logger.info("razorpay_webhook: duplicate event %s, skipping", event_id)
            return Response(status_code=200)
        applied_payment_ids = _handle_razorpay_event(event, db)
        # Belt-and-suspenders: some event branches take no DB-writing action
        # of their own (no internal db.commit()), commit here too so the
        # processed-event row above is never silently rolled back on close.
        db.commit()
        # Emails only after the commit, so they never describe a change that
        # was rolled back.
        for payment_id in applied_payment_ids:
            payment = db.get(Payment, payment_id)
            org = db.get(Organization, payment.org_id) if payment and payment.org_id else None
            if payment is not None and org is not None:
                notify("payment_received", org, payment=payment)
    except Exception:
        db.rollback()
        logger.exception("razorpay_webhook: error processing event %s", event.get("event"))
        raise HTTPException(500, "Internal error processing webhook.")
    finally:
        db.close()

    return Response(status_code=200)


def _payment_for_order(order_id: str | None, db: Session) -> Payment | None:
    if not order_id:
        return None
    return db.query(Payment).filter(Payment.razorpay_order_id == order_id).first()


def _flag_international(payment: Payment, rz_payment: dict) -> None:
    """An INR order paid with an international card is a possible sign of
    someone claiming India to get the INR price. Logged for review only: a
    real customer can have a foreign card, so nothing is blocked."""
    if payment.currency == "INR" and rz_payment.get("international") is True:
        logger.error(
            "billing: INR payment %s for org %s was paid with an international card, review",
            payment.id, payment.org_id,
        )


def _handle_razorpay_event(event: dict, db: Session) -> list[str]:
    """Orders model: only payment.captured, payment.failed and refund.processed
    matter. Every other event type is ignored. Nothing here commits, the
    webhook route does. Returns the ids of payments this call newly applied,
    so the route can send the payment emails after its commit."""
    etype = event.get("event", "")
    payload = event.get("payload", {})
    now = datetime.now(timezone.utc)
    applied_ids: list[str] = []

    if etype == "payment.captured":
        entity = (payload.get("payment") or {}).get("entity") or {}
        payment = _payment_for_order(entity.get("order_id"), db)
        if payment is None:
            logger.warning("billing: payment.captured for unknown order %s", entity.get("order_id"))
            return applied_ids
        if entity.get("amount") != payment.amount_paise or entity.get("currency") != payment.currency:
            logger.error(
                "billing: payment.captured mismatch for payment %s, stored %s %s, Razorpay %s %s",
                payment.id, payment.amount_paise, payment.currency,
                entity.get("amount"), entity.get("currency"),
            )
            return applied_ids
        _flag_international(payment, entity)
        applied = apply_captured_payment(
            payment, db,
            razorpay_payment_id=entity.get("id"),
            method_display=_payment_method_display(entity),
            now=now,
        )
        if applied:
            applied_ids.append(payment.id)
        logger.info("billing: payment.captured for payment %s (applied=%s)", payment.id, applied)

    elif etype == "payment.failed":
        # A failed attempt changes nothing on the org. The order stays usable,
        # so a later successful attempt is still applied.
        entity = (payload.get("payment") or {}).get("entity") or {}
        payment = _payment_for_order(entity.get("order_id"), db)
        if payment is not None and payment.status == "created":
            payment.status = "failed"
            logger.warning("billing: Razorpay payment failed for payment %s", payment.id)

    elif etype == "refund.processed":
        entity = (payload.get("refund") or {}).get("entity") or {}
        rz_payment_id = entity.get("payment_id")
        payment = (
            db.query(Payment).filter(Payment.razorpay_payment_id == rz_payment_id).first()
            if rz_payment_id else None
        )
        if payment is None:
            logger.warning("billing: refund.processed for unknown payment %s", rz_payment_id)
            return applied_ids
        if entity.get("amount") is not None and entity["amount"] < payment.amount_paise:
            logger.warning("billing: partial refund on payment %s ignored, needs manual handling", payment.id)
            return applied_ids
        newly_refunded = payment.status != "refunded"
        if newly_refunded:
            payment.status = "refunded"
        if payment.refunded_at is None:
            payment.refunded_at = now
        if newly_refunded and payment.org_id and payment.captured_at is not None:
            # Phase 12: a refund made outside POST /billing/refund (the Razorpay
            # dashboard) of a payment inside the 72 hour window also cancels
            # the referrer's unvested credit.
            refunded_org = db.get(Organization, payment.org_id)
            if (
                refunded_org is not None
                and refunded_org.first_charged_at is not None
                and payment.captured_at <= refunded_org.first_charged_at + REFUND_WINDOW
            ):
                revoke_for_refunded_referee(db, refunded_org.id, now)

    return applied_ids


# ---------------------------------------------------------------------------
# POST /billing/refund-eligibility, POST /billing/refund
# ---------------------------------------------------------------------------

@router.post("/refund-eligibility", response_model=RefundEligibilityOut)
def refund_eligibility(
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    return _refund_out(current_org.organization.id, db)


class RefundOut(BaseModel):
    status: str  # refunded
    refunded_paise: int
    failed_payments: int  # refunds Razorpay rejected, need manual dashboard action


@router.post("/refund", response_model=RefundOut)
def refund_first_payment(
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    """Full refund of every payment captured inside the 72 hour window after
    the org's first payment, then the org drops to free. The refund is
    finalised on the refund.processed webhook, which finds the payment already
    marked refunded and does nothing."""
    org = current_org.organization
    window = refund_window(org.id, db)
    if not window.eligible:
        raise HTTPException(409, f"Not eligible for a refund ({window.reason}).")

    # Lock the payment rows so a double click cannot refund twice.
    ids = [p.id for p in window.payments]
    locked = (
        db.query(Payment)
        .filter(Payment.id.in_(ids), Payment.status == "captured")
        .populate_existing()
        .with_for_update()
        .all()
    )
    if not locked:
        db.rollback()
        raise HTTPException(409, "Not eligible for a refund (already_refunded).")

    rp = _init_razorpay()
    now = datetime.now(timezone.utc)
    refunded = 0
    failed = 0
    for p in locked:
        try:
            rp.payment.refund(
                p.razorpay_payment_id,
                {"amount": p.amount_paise, "notes": {"payment_id": p.id, "reason": "remorse_window"}},
            )
        except Exception:
            failed += 1
            logger.exception("billing: refund failed for payment %s, needs manual dashboard action", p.id)
            continue
        p.status = "refunded"
        p.refunded_at = now
        refunded += p.amount_paise

    if refunded == 0:
        db.rollback()
        raise HTTPException(502, "Razorpay could not process the refund. Please retry shortly.")

    downgrade_org(org, db, "refund", now, amount_paise=refunded)
    # Phase 12: a refund inside the window cancels the referrer's unvested credit.
    revoke_for_refunded_referee(db, org.id, now)
    db.commit()
    return RefundOut(status="refunded", refunded_paise=refunded, failed_payments=failed)


# ---------------------------------------------------------------------------
# POST /billing/cancel, POST /billing/schedule-downgrade
#
# Both only record intent. The daily billing cycle (workers/tasks/
# billing_cycle.py) applies it at the next bill date. The latest request
# wins: scheduling a downgrade withdraws a pending cancel and vice versa.
# ---------------------------------------------------------------------------

class PlanChangeOut(BaseModel):
    status: str
    cancel_at_period_end: bool
    pending_tier: str | None
    pending_period: str | None
    next_billing_date: str | None


def _plan_change_out(org: Organization, status: str) -> PlanChangeOut:
    return PlanChangeOut(
        status=status,
        cancel_at_period_end=bool(org.cancel_at_period_end),
        pending_tier=org.pending_tier,
        pending_period=org.pending_period,
        next_billing_date=_iso(org.next_billing_date),
    )


def _require_razorpay_paid_plan(org: Organization) -> None:
    if org.billing_provider == "stripe":
        raise HTTPException(409, "This account is billed through Stripe. Use the billing portal.")
    if org.tier == "enterprise":
        raise HTTPException(409, "Enterprise plans are managed by Clew. Contact support.")
    if not on_paid_plan(org):
        raise HTTPException(400, "There is no paid plan to change.")


@router.post("/cancel", response_model=PlanChangeOut)
def cancel_subscription(
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    _require_razorpay_paid_plan(org)
    org.cancel_at_period_end = True
    org.pending_tier = None
    org.pending_period = None
    db.commit()
    return _plan_change_out(org, "cancel_scheduled")


class ScheduleDowngradeBody(BaseModel):
    tier: str
    period: str


@router.post("/schedule-downgrade", response_model=PlanChangeOut)
def schedule_downgrade(
    body: ScheduleDowngradeBody,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    _require_razorpay_paid_plan(org)
    tier, period = body.tier.lower(), body.period.lower()
    kind = classify_change((org.tier, org.billing_period), (tier, period))
    if kind != "downgrade":
        raise HTTPException(400, f"That change is not a downgrade ({kind}).")
    org.pending_tier = tier
    org.pending_period = period
    org.cancel_at_period_end = False
    db.commit()
    return _plan_change_out(org, "downgrade_scheduled")


@router.post("/undo-pending", response_model=PlanChangeOut)
def undo_pending_change(
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    """Withdraw a scheduled cancel or downgrade, so the plan simply carries on
    and is billed as normal at the next bill date. Harmless when nothing is
    scheduled."""
    org = current_org.organization
    _require_razorpay_paid_plan(org)
    had_pending = bool(org.cancel_at_period_end or org.pending_tier or org.pending_period)
    org.cancel_at_period_end = False
    org.pending_tier = None
    org.pending_period = None
    db.commit()
    return _plan_change_out(org, "pending_cleared" if had_pending else "nothing_pending")


# ---------------------------------------------------------------------------
# PUT /billing/details
# ---------------------------------------------------------------------------

class BillingDetailsBody(BaseModel):
    legal_name: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=1000)
    gstin: str | None = Field(default=None, max_length=20)
    # ISO 3166-1 alpha-2. Sets the billing country (and so the currency) once;
    # afterwards only the same value is accepted.
    billing_country: str | None = Field(default=None, max_length=2)


@router.put("/details")
def update_billing_details(
    body: BillingDetailsBody,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
) -> dict:
    """Only the fields present in the request change. An empty string clears a
    field. Details are printed on later receipts, past receipts keep the values
    snapshotted on their Payment. The billing country is the exception: it is
    set once and then fixed, a different value is a 409 (a support action)."""
    org = current_org.organization
    sent = body.model_fields_set
    gstin = _clean_gstin(body.gstin) if "gstin" in sent else None
    if "billing_country" in sent and body.billing_country and body.billing_country.strip():
        currency, country = resolve_currency(org, body.billing_country)
        lock_billing_currency(org, currency, country)
    if "legal_name" in sent:
        org.billing_legal_name = (body.legal_name or "").strip() or None
    if "address" in sent:
        org.billing_address = (body.address or "").strip() or None
    if "gstin" in sent:
        org.gstin = gstin
    db.commit()
    return _billing_details(org)


# ---------------------------------------------------------------------------
# POST /billing/quote: the exact amount a purchase would charge
#
# Runs the same plan_for_order as create-order, so what the dialog shows is
# what is charged. Creates nothing and locks nothing. The blocking agreement
# is not required here (the user has not ticked it yet), create-order checks it.
# ---------------------------------------------------------------------------

class QuoteOut(BaseModel):
    amount: int  # minor units of `currency`
    currency: str
    billing_country: str | None
    description: str


@router.post("/quote", response_model=QuoteOut)
def billing_quote(
    body: CreateOrderBody,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    purpose = body.purpose.lower()
    tier = body.tier.lower() if body.tier else None
    period = body.period.lower() if body.period else None
    if period is not None and period not in PERIODS:
        raise HTTPException(400, f"Unknown period: {body.period}")
    plan = plan_for_order(
        org, purpose, tier, period, body.bill_id, True, db,
        billing_country=body.billing_country,
    )
    return QuoteOut(
        amount=plan.amount_paise,
        currency=plan.currency,
        billing_country=plan.billing_country,
        description=plan.line_items.get("description", ""),
    )


# ---------------------------------------------------------------------------
# GET /billing/payments/{payment_id}: receipt data (owner only)
#
# A receipt, not a tax invoice. The customer details are the values snapshotted
# on the Payment when it was made, never the org's current details.
# ---------------------------------------------------------------------------

class ReceiptOut(BaseModel):
    id: str
    razorpay_payment_id: str | None
    status: str
    purpose: str
    currency: str
    amount_paise: int
    created_at: str | None
    captured_at: str | None
    refunded_at: str | None
    lines: list[dict]
    customer_name: str
    customer_address: str | None
    customer_gstin: str | None
    customer_country: str | None


def _receipt_lines(p: Payment) -> list[dict]:
    items = p.line_items or {}
    if p.purpose == "restore" and items.get("bills_paise") is not None:
        bills_paise = items["bills_paise"]
        count = len(items.get("bill_ids", []))
        return [
            {"description": f"Open bills ({count})", "amount_paise": bills_paise},
            {
                "description": f"{plan_label(items['tier'], items['period'])} (new period)",
                "amount_paise": p.amount_paise - bills_paise,
            },
        ]
    return [{"description": items.get("description") or "Clew", "amount_paise": p.amount_paise}]


@router.get("/payments/{payment_id}", response_model=ReceiptOut)
def billing_receipt(
    payment_id: str,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    p = (
        db.query(Payment)
        .filter(
            Payment.id == payment_id,
            Payment.org_id == org.id,
            Payment.status.in_(("captured", "refunded")),
        )
        .first()
    )
    if p is None:
        raise HTTPException(404, "Receipt not found.")
    return ReceiptOut(
        id=p.id,
        razorpay_payment_id=p.razorpay_payment_id,
        status=p.status,
        purpose=p.purpose,
        currency=p.currency,
        amount_paise=p.amount_paise,
        created_at=_iso(p.created_at),
        captured_at=_iso(p.captured_at),
        refunded_at=_iso(p.refunded_at),
        lines=_receipt_lines(p),
        customer_name=p.legal_name_snapshot or p.org_name_snapshot,
        customer_address=p.address_snapshot,
        customer_gstin=p.gstin_snapshot,
        customer_country=org.billing_country,
    )


# ---------------------------------------------------------------------------
# GET / PUT /billing/notifications: who gets billing emails (owner only)
# ---------------------------------------------------------------------------

class NotificationSettings(BaseModel):
    mode: str  # owner | selected | all
    reminders_enabled: bool


class NotificationSettingsBody(BaseModel):
    mode: Literal["owner", "selected", "all"]
    reminders_enabled: bool


@router.get("/notifications", response_model=NotificationSettings)
def get_notification_settings(current_org: CurrentOrg = Depends(require_role("owner"))):
    org = current_org.organization
    return NotificationSettings(
        mode=org.billing_emails_mode, reminders_enabled=bool(org.billing_reminders_enabled)
    )


@router.put("/notifications", response_model=NotificationSettings)
def put_notification_settings(
    body: NotificationSettingsBody,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    org.billing_emails_mode = body.mode
    org.billing_reminders_enabled = body.reminders_enabled
    db.commit()
    return NotificationSettings(mode=org.billing_emails_mode, reminders_enabled=body.reminders_enabled)


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
    org.tier = "starter"


def cancel_org_subscriptions_for_deletion(org: Organization, db: Session) -> None:
    """Item 40: cancel whatever active subscription an org has. Called
    directly by account deletion (api/routes/auth.py), not through the
    authenticated HTTP routes above. Razorpay needs no cancel (there is no
    subscription object), only Stripe does."""
    if org.stripe_subscription_id:
        _cancel_stripe_subscription_now(org)



