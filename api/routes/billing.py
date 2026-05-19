"""api/routes/billing.py — Stripe subscription management.

Four endpoints:
  GET  /billing/status    → current tier and subscription metadata
  POST /billing/checkout  → create Stripe Checkout Session, return redirect URL
  POST /billing/portal    → create Stripe Customer Portal Session, return redirect URL
  POST /billing/webhook   → Stripe signature-verified event handler (no auth cookie)

Tier lifecycle (sole source of truth is this file + the webhook):
  signup         → tier = "free"    (DB default)
  checkout.session.completed          → tier = <purchased tier>
  customer.subscription.updated/deleted (non-active status) → tier = "free"
  invoice.payment_failed              → logged only; Stripe retries automatically
"""
from __future__ import annotations

import logging
import os

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_current_client, get_db
from db.models import Client
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


def _client_by_customer(customer_id: str, db: Session) -> Client | None:
    return (
        db.query(Client)
        .filter(Client.stripe_customer_id == customer_id)
        .first()
    )


# ---------------------------------------------------------------------------
# GET /billing/status
# ---------------------------------------------------------------------------

class BillingStatusOut(BaseModel):
    tier: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    tier_expires_at: str | None


@router.get("/status", response_model=BillingStatusOut)
def billing_status(client: Client = Depends(get_current_client)):
    return BillingStatusOut(
        tier=client.tier,
        stripe_customer_id=client.stripe_customer_id,
        stripe_subscription_id=client.stripe_subscription_id,
        tier_expires_at=(
            client.tier_expires_at.isoformat() if client.tier_expires_at else None
        ),
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
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    _init_stripe()
    price_id = _price_id(body.tier, body.currency)
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")

    # Reuse existing Stripe customer record if present
    customer_id = client.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            email=client.email,
            name=client.company_name,
            metadata={"clew_client_id": client.id},
        )
        customer_id = customer.id
        db.query(Client).filter(Client.id == client.id).update(
            {"stripe_customer_id": customer_id}
        )
        db.commit()

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{frontend_url}/dashboard/settings?upgraded=1",
        cancel_url=f"{frontend_url}/dashboard/settings",
        metadata={"clew_client_id": client.id, "tier": body.tier},
    )
    return UrlOut(url=session.url)


# ---------------------------------------------------------------------------
# POST /billing/portal
# ---------------------------------------------------------------------------

@router.post("/portal", response_model=UrlOut)
def create_portal(client: Client = Depends(get_current_client)):
    _init_stripe()
    if not client.stripe_customer_id:
        raise HTTPException(400, "No active subscription to manage.")
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    session = stripe.billing_portal.Session.create(
        customer=client.stripe_customer_id,
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
        client = _client_by_customer(customer_id, db)
        if not client:
            logger.warning("billing: unknown Stripe customer %s from checkout", customer_id)
            return
        db.query(Client).filter(Client.id == client.id).update(
            {"tier": tier, "stripe_subscription_id": sub_id}
        )
        db.commit()
        logger.info("billing: client %s upgraded to %s", client.id, tier)

    elif etype in ("customer.subscription.updated", "customer.subscription.deleted"):
        customer_id = obj.get("customer")
        if not customer_id:
            return
        status = obj.get("status", "")
        client = _client_by_customer(customer_id, db)
        if not client:
            return
        if status not in ("active", "trialing"):
            # Subscription canceled, past_due, or unpaid — revert to free
            db.query(Client).filter(Client.id == client.id).update(
                {"tier": "free", "stripe_subscription_id": None, "tier_expires_at": None}
            )
            db.commit()
            logger.info(
                "billing: client %s downgraded to free (status=%s)", client.id, status
            )

    elif etype == "invoice.payment_failed":
        # Stripe auto-retries; actual downgrade fires via subscription.updated
        customer_id = obj.get("customer")
        if customer_id:
            client = _client_by_customer(customer_id, db)
            if client:
                logger.warning("billing: payment failed for client %s", client.id)
