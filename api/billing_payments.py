"""api/billing_payments.py: Phase 4 payment rules (what an order costs, what a
captured payment does, who may be refunded).

The routes in api/routes/billing.py are thin wrappers over this module.
apply_captured_payment is the single place a payment changes an org. Both the
browser callback (verify-payment) and the Razorpay webhook call it, so it is
idempotent and row-locked: whichever arrives first applies the payment, the
other sees status 'captured' and does nothing.

No function here commits. The caller owns the transaction, so the row locks
taken here are held until the caller's commit.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from api.billing_rules import (
    as_utc,
    classify_change,
    ist_midnight,
    next_bill_date_after_payment,
    restore_amount_paise,
    today_ist,
    upgrade_amount_paise,
)
from api.referrals import confirm_first_payment
from api.tiers import (
    MANUAL_BLOCK_TIERS,
    MIN_ORDER_MINOR,
    PAID_TIER_ORDER,
    PURCHASABLE_PLANS,
    currency_for_country,
    plan_price,
)
from db.models import Bill, BillingEvent, Organization, Payment

logger = logging.getLogger(__name__)

PURPOSES = ("initial", "upgrade", "bill", "restore")
REFUND_WINDOW = timedelta(hours=72)

_COUNTRY_RE = re.compile(r"[A-Z]{2}")

_TIER_LABELS = {"starter": "Basic", "growth": "Growth", "pro": "Pro"}


def plan_label(tier: str, period: str) -> str:
    return f"{_TIER_LABELS.get(tier, tier)} {period}"


def on_paid_plan(org: Organization) -> bool:
    return org.tier in PAID_TIER_ORDER and org.billing_period is not None


def open_bills(org_id: str, db) -> list[Bill]:
    return (
        db.query(Bill)
        .filter(Bill.org_id == org_id, Bill.status == "open")
        .order_by(Bill.period_start)
        .all()
    )


def bill_summary(bill: Bill) -> dict:
    return {
        "id": bill.id,
        "tier": bill.tier,
        "period": bill.period,
        "period_start": bill.period_start.isoformat(),
        "period_end": bill.period_end.isoformat(),
        "amount_paise": bill.amount_paise,
        "currency": bill.currency,
        "due_date": bill.due_date.isoformat(),
        "cancel_on": bill.cancel_on.isoformat(),
    }


def _bills_conflict(message: str, bills: list[Bill]) -> HTTPException:
    return HTTPException(
        409,
        detail={"message": message, "open_bills": [bill_summary(b) for b in bills]},
    )


# ---------------------------------------------------------------------------
# Currency (Phase 5 section C)
# ---------------------------------------------------------------------------

def min_order_minor(currency: str) -> int:
    """Smallest order Razorpay accepts in `currency`, in minor units."""
    return MIN_ORDER_MINOR[currency]


def resolve_currency(org: Organization, billing_country: str | None) -> tuple[str, str]:
    """The (currency, country) an order for `org` is charged in.

    An org that already has a billing country is locked to it: the stored
    currency is used, and a different country in the request is rejected
    (changing it is a support action). An org with no country yet takes the
    one in the request, which is required: INR for India, USD otherwise.
    Nothing here writes: lock_billing_currency stores the choice.
    """
    country = billing_country.strip().upper() if billing_country else None
    if country is not None and not _COUNTRY_RE.fullmatch(country):
        raise HTTPException(400, "Billing country must be a two letter ISO country code.")
    if org.billing_country:
        if country and country != org.billing_country:
            raise HTTPException(
                409,
                "The billing country of this organisation is already set and cannot be changed here. "
                "Contact support to change it.",
            )
        return org.billing_currency, org.billing_country
    if country is None:
        raise HTTPException(400, "Billing country is required.")
    return currency_for_country(country), country


def lock_billing_currency(org: Organization, currency: str, country: str) -> None:
    """Store the billing country and currency on an org that has none yet.
    A no-op once set: the currency never changes after the first checkout."""
    if org.billing_country:
        return
    org.billing_country = country
    org.billing_currency = currency


def _check_bills_currency(currency: str, bills: list[Bill]) -> None:
    """Open bills of one org are always in one currency. Anything else is bad
    data and is refused, never summed."""
    if any(b.currency != currency for b in bills):
        raise HTTPException(
            409,
            "This organisation has open bills in more than one currency. Contact support.",
        )


# ---------------------------------------------------------------------------
# Pricing an order
# ---------------------------------------------------------------------------

@dataclass
class OrderPlan:
    amount_paise: int            # minor units of `currency` (paise or cents)
    currency: str
    billing_country: str | None = None
    line_items: dict = field(default_factory=dict)


def plan_for_order(
    org: Organization,
    purpose: str,
    tier: str | None,
    period: str | None,
    bill_id: str | None,
    accept_tos: bool,
    db,
    now: datetime | None = None,
    billing_country: str | None = None,
) -> OrderPlan:
    """Validate a purchase and compute its amount from PLAN_PRICES and the
    rules in api/billing_rules.py, in the org's billing currency. The client
    never supplies an amount or a currency, only a billing country for an org
    that has none yet. Raises HTTPException for anything not allowed."""
    if purpose not in PURPOSES:
        raise HTTPException(400, f"Unknown purpose: {purpose}")
    if org.billing_provider == "stripe":
        raise HTTPException(409, "This account is billed through Stripe.")
    if org.tier == "enterprise":
        raise HTTPException(409, "Enterprise plans are invoiced by Clew. Contact support.")

    bills = open_bills(org.id, db)

    if purpose == "bill":
        return _plan_bill(org, bill_id, bills)

    if (tier, period) not in PURCHASABLE_PLANS:
        raise HTTPException(400, "Unknown plan.")
    if tier in MANUAL_BLOCK_TIERS and org.blocking_tos_accepted_at is None and not accept_tos:
        raise HTTPException(403, "Accept the Blocking Subscription Agreement before continuing.")

    currency, country = resolve_currency(org, billing_country)
    _check_bills_currency(currency, bills)

    if purpose == "initial":
        if on_paid_plan(org):
            raise HTTPException(409, "This account already has a paid plan. Use an upgrade or schedule a downgrade.")
        if bills:
            raise _bills_conflict("Pay or restore your open bills first.", bills)
        return OrderPlan(
            plan_price(currency, tier, period),
            currency,
            country,
            {"description": plan_label(tier, period), "tier": tier, "period": period},
        )

    if purpose == "restore":
        if org.tier != "free" or org.nonpayment_downgraded_at is None:
            raise HTTPException(409, "Restore is only available after a plan was cancelled for non-payment.")
        return OrderPlan(
            restore_amount_paise(bills, tier, period, currency=currency),
            currency,
            country,
            {
                "description": f"Restore {plan_label(tier, period)}",
                "tier": tier,
                "period": period,
                "bill_ids": [b.id for b in bills],
                "bills_paise": sum(b.amount_paise for b in bills),
            },
        )

    return _plan_upgrade(org, tier, period, bills, now, currency, country)


def _plan_bill(org: Organization, bill_id: str | None, bills: list[Bill]) -> OrderPlan:
    if not bill_id:
        raise HTTPException(400, "bill_id is required to pay a bill.")
    if org.tier == "free":
        raise HTTPException(409, "This plan was cancelled. Use restore to pay open bills and continue.")
    bill = next((b for b in bills if b.id == bill_id), None)
    if bill is None:
        raise HTTPException(404, "No open bill with that id.")
    # A bill is always charged in its own currency, which must be the org's.
    _check_bills_currency(org.billing_currency, [bill])
    return OrderPlan(
        bill.amount_paise,
        bill.currency,
        org.billing_country,
        {
            "description": f"Bill for {plan_label(bill.tier, bill.period)}",
            "tier": bill.tier,
            "period": bill.period,
            "bill_ids": [bill.id],
        },
    )


def _plan_upgrade(
    org: Organization,
    tier: str,
    period: str,
    bills: list[Bill],
    now: datetime | None,
    currency: str,
    country: str,
) -> OrderPlan:
    if not on_paid_plan(org):
        raise HTTPException(409, "There is no paid plan to upgrade. Choose a plan instead.")
    old = (org.tier, org.billing_period)
    new = (tier, period)
    kind = classify_change(old, new)
    if kind != "upgrade":
        raise HTTPException(400, f"That change is not an upgrade ({kind}).")

    # An upgrade is only for a plan that has been paid for: every open bill,
    # current period or older, is settled first (assumption 5).
    if bills:
        raise _bills_conflict("Pay your open bills before upgrading.", bills)

    amount = upgrade_amount_paise(old, new, currency=currency)
    items = {
        "description": f"Upgrade to {plan_label(tier, period)}",
        "tier": tier,
        "period": period,
        "from_tier": old[0],
        "from_period": old[1],
    }
    return OrderPlan(amount, currency, country, items)


# ---------------------------------------------------------------------------
# Applying a payment
# ---------------------------------------------------------------------------

def _event(db, org, event: str, from_tier, to_tier, period, amount, now) -> None:
    db.add(
        BillingEvent(
            org_id=org.id,
            event=event,
            from_tier=from_tier,
            to_tier=to_tier,
            period=period,
            amount_paise=amount,
            currency=org.billing_currency if amount is not None else None,
            created_at=now,
        )
    )


def _stamp(org: Organization, payment: Payment, method_display: str | None, now: datetime) -> None:
    """Things recorded only once money has actually been taken."""
    if payment.tos_accepted and org.blocking_tos_accepted_at is None:
        org.blocking_tos_accepted_at = now
    if payment.gstin_snapshot and org.gstin != payment.gstin_snapshot:
        org.gstin = payment.gstin_snapshot
    if method_display:
        org.payment_method_display = method_display


def _mark_bills_paid(db, org: Organization, bill_ids: list[str], payment: Payment, now: datetime) -> None:
    if not bill_ids:
        return
    bills = db.query(Bill).filter(Bill.id.in_(bill_ids), Bill.org_id == org.id).all()
    for bill in bills:
        if bill.status == "open":
            bill.status = "paid"
            bill.paid_at = now
            bill.payment_id = payment.id
        else:
            logger.warning(
                "billing: payment %s covers bill %s which is already %s, may need a manual refund",
                payment.id, bill.id, bill.status,
            )


def _apply_plan_purchase(db, org, payment, items: dict, now: datetime, restore: bool) -> None:
    if on_paid_plan(org):
        logger.error(
            "billing: payment %s (%s) captured for org %s that already has a paid plan, "
            "org left unchanged, needs a manual refund",
            payment.id, payment.purpose, org.id,
        )
        return
    tier, period = items["tier"], items["period"]
    first = org.first_charged_at is None
    old_tier = org.tier

    org.tier = tier
    org.billing_period = period
    org.billing_provider = "razorpay"
    org.next_billing_date = ist_midnight(next_bill_date_after_payment(today_ist(now), period))
    org.nonpayment_downgraded_at = None
    org.retention_grace_tier = None
    org.retention_grace_until = None
    org.cancel_at_period_end = False
    org.pending_tier = None
    org.pending_period = None
    if first:
        org.first_charged_at = now
        confirm_first_payment(org, db)
    if restore:
        _mark_bills_paid(db, org, items.get("bill_ids", []), payment, now)
    _event(
        db, org, "first_paid" if first and not restore else "restored",
        old_tier, tier, period, payment.amount_paise, now,
    )


def _apply_upgrade(db, org, payment, items: dict, now: datetime) -> None:
    old = (items["from_tier"], items["from_period"])
    if (org.tier, org.billing_period) != old:
        logger.error(
            "billing: upgrade payment %s captured but org %s is no longer on %s/%s, "
            "org left unchanged, needs a manual refund",
            payment.id, org.id, *old,
        )
        return
    tier, period = items["tier"], items["period"]
    old_tier = org.tier
    if period == "annual":
        # Any upgrade to an annual plan (monthly to annual, or annual to a
        # higher annual tier) pays the full annual price and starts a new
        # period now, re-anchored by the 15th/16th rule. The rest of the
        # paid monthly time or old year is forfeited (assumption 4).
        org.tier = tier
        org.billing_period = period
        org.next_billing_date = ist_midnight(next_bill_date_after_payment(today_ist(now), period))
    else:
        org.tier = tier
    org.pending_tier = None
    org.pending_period = None
    _event(db, org, "upgraded", old_tier, tier, period, payment.amount_paise, now)


def apply_captured_payment(
    payment: Payment,
    db,
    razorpay_payment_id: str | None = None,
    method_display: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Apply a captured payment to its org, exactly once. Returns True if this
    call applied it, False if it was already captured or refunded. Safe to
    call from the browser callback and the webhook at the same time: the
    Payment row is locked (SELECT ... FOR UPDATE) and the second caller sees
    the first caller's status. A payment that was marked failed can still be
    applied, since one Razorpay order allows several attempts.
    """
    moment = now or datetime.now(timezone.utc)
    locked = (
        db.query(Payment)
        .filter(Payment.id == payment.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    if locked.status in ("captured", "refunded"):
        return False

    locked.status = "captured"
    locked.captured_at = moment
    if razorpay_payment_id and not locked.razorpay_payment_id:
        locked.razorpay_payment_id = razorpay_payment_id

    org = None
    if locked.org_id is not None:
        org = (
            db.query(Organization)
            .filter(Organization.id == locked.org_id)
            .with_for_update()
            .one_or_none()
        )
    if org is None or org.deleted_at is not None:
        logger.warning("billing: payment %s captured for a missing or deleted org, no plan change", locked.id)
        return True

    items = locked.line_items or {}
    if locked.currency != org.billing_currency:
        logger.error(
            "billing: payment %s is in %s but org %s bills in %s, org left unchanged, "
            "needs a manual refund",
            locked.id, locked.currency, org.id, org.billing_currency,
        )
        return True
    if locked.purpose in ("initial", "restore"):
        _apply_plan_purchase(db, org, locked, items, moment, restore=locked.purpose == "restore")
    elif locked.purpose == "upgrade":
        _apply_upgrade(db, org, locked, items, moment)
    elif locked.purpose == "bill":
        _mark_bills_paid(db, org, items.get("bill_ids", []), locked, moment)
    else:
        logger.error("billing: payment %s has unknown purpose %r", locked.id, locked.purpose)
        return True

    _stamp(org, locked, method_display, moment)
    return True


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------

@dataclass
class RefundWindow:
    eligible: bool
    reason: str  # remorse_window | already_refunded | not_eligible | no_payment
    expires_at: datetime | None = None
    payments: list[Payment] = field(default_factory=list)  # still refundable


def refund_window(org_id: str, db, now: datetime | None = None) -> RefundWindow:
    """72 hours from capture of the org's first-ever payment (assumption: the
    window is strict, now < first + 72h). Every payment captured inside that
    window and not yet refunded is refundable together."""
    moment = as_utc(now) if now is not None else datetime.now(timezone.utc)
    paid = (
        db.query(Payment)
        .filter(Payment.org_id == org_id, Payment.captured_at.isnot(None))
        .order_by(Payment.captured_at)
        .all()
    )
    if not paid:
        return RefundWindow(False, "no_payment")
    expires = as_utc(paid[0].captured_at) + REFUND_WINDOW
    if moment >= expires:
        return RefundWindow(False, "not_eligible")
    refundable = [
        p for p in paid
        if p.status == "captured" and p.razorpay_payment_id and as_utc(p.captured_at) < expires
    ]
    if not refundable:
        return RefundWindow(False, "already_refunded")
    return RefundWindow(True, "remorse_window", expires, refundable)
