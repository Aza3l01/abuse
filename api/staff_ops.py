"""api/staff_ops.py: the write actions of the Phase 6 ops panel.

Every billing action goes through the Phase 3 and 4 functions (a manual
payment is applied by apply_captured_payment, a reinstate is priced by
plan_for_order), never a parallel copy of the rules. Nothing here commits:
the route adds the audit row and commits once, so an action and its audit
record are saved together or not at all.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from api.billing_payments import (
    apply_captured_payment,
    on_paid_plan,
    open_bills,
    plan_for_order,
    plan_label,
)
from api.billing_rules import add_months, as_utc, ist_date, ist_midnight
from api.referrals import approve_credit, revoke_credit
from db.models import Bill, Credit, Organization, Payment, PromoCode

MIN_REASON_LENGTH = 10
PILOT_CODE_LIFETIME_CAP = 500
_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I


def clean_reason(reason: str | None) -> str:
    text = (reason or "").strip()
    if len(text) < MIN_REASON_LENGTH:
        raise HTTPException(400, f"A reason of at least {MIN_REASON_LENGTH} characters is required.")
    return text


def _now(now: datetime | None) -> datetime:
    return as_utc(now) if now is not None else datetime.now(timezone.utc)


def _manual_payment(
    db, org: Organization, purpose: str, amount: int, currency: str, items: dict, reference: str, moment: datetime
) -> Payment:
    """Record money received outside Razorpay (a bank transfer) as a Payment
    and apply it like any captured payment, so the customer gets a receipt."""
    payment = Payment(
        org_id=org.id,
        org_name_snapshot=org.company_name,
        razorpay_order_id=f"manual_{uuid.uuid4().hex}",
        amount_paise=amount,
        currency=currency,
        purpose=purpose,
        status="created",
        line_items={**items, "manual": True, "reference": reference},
        tos_accepted=False,
        gstin_snapshot=org.gstin,
        legal_name_snapshot=org.billing_legal_name,
        address_snapshot=org.billing_address,
        created_at=moment,
    )
    db.add(payment)
    db.flush()
    apply_captured_payment(payment, db, method_display="Bank transfer", now=moment)
    return payment


def mark_bill_paid(db, org: Organization, bill_id: str, reference: str, now: datetime | None = None) -> Payment:
    moment = _now(now)
    bill = db.query(Bill).filter(Bill.id == bill_id, Bill.org_id == org.id).first()
    if bill is None:
        raise HTTPException(404, "No bill with that id for this organisation.")
    if bill.status != "open":
        raise HTTPException(409, f"That bill is already {bill.status}.")
    if bill.currency != org.billing_currency:
        raise HTTPException(409, "That bill is not in the organisation's billing currency.")
    items = {
        "description": f"Bill for {plan_label(bill.tier, bill.period)}",
        "tier": bill.tier,
        "period": bill.period,
        "bill_ids": [bill.id],
    }
    payment = _manual_payment(db, org, "bill", bill.amount_paise, bill.currency, items, reference, moment)
    if bill.status != "paid":
        raise HTTPException(500, "The payment was recorded but the bill did not close.")
    return payment


def void_bill(db, org: Organization, bill_id: str) -> Bill:
    bill = db.query(Bill).filter(Bill.id == bill_id, Bill.org_id == org.id).first()
    if bill is None:
        raise HTTPException(404, "No bill with that id for this organisation.")
    if bill.status != "open":
        raise HTTPException(409, f"That bill is already {bill.status}.")
    bill.status = "void"
    return bill


def extend_period(db, org: Organization, months: int) -> dict:
    """Give `months` free months: the next bill date moves forward."""
    if not 1 <= months <= 12:
        raise HTTPException(400, "Months must be between 1 and 12.")
    if not on_paid_plan(org) or org.next_billing_date is None:
        raise HTTPException(409, "Only an organisation on a paid plan can be extended.")
    if open_bills(org.id, db):
        raise HTTPException(409, "This organisation has an open bill. Mark it paid or void it first.")
    before = ist_date(org.next_billing_date)
    after = add_months(before, months)
    org.next_billing_date = ist_midnight(after)
    return {"next_billing_date_before": before.isoformat(), "next_billing_date_after": after.isoformat()}


def pause_downgrade(db, org: Organization, days: int) -> dict:
    """Delay the non-payment downgrade of an org's open bills by `days`."""
    if not 1 <= days <= 30:
        raise HTTPException(400, "Days must be between 1 and 30.")
    if org.tier == "starter":
        raise HTTPException(409, "This organisation is already on the free tier.")
    bills = open_bills(org.id, db)
    if not bills:
        raise HTTPException(409, "This organisation has no open bill.")
    changes = []
    for bill in bills:
        old = bill.cancel_on
        bill.cancel_on = old + timedelta(days=days)
        changes.append({"bill_id": bill.id, "cancel_on_before": old.isoformat(), "cancel_on_after": bill.cancel_on.isoformat()})
    return {"bills": changes}


def reinstate_org(
    db, org: Organization, tier: str, period: str, reference: str, now: datetime | None = None
) -> Payment:
    """Restore an org downgraded for non-payment, after a bank transfer for
    the restore amount (its open bills plus one new period) was received."""
    moment = _now(now)
    plan = plan_for_order(org, "restore", tier, period, None, False, db, moment)
    items = {**plan.line_items}
    payment = _manual_payment(db, org, "restore", plan.amount_paise, plan.currency, items, reference, moment)
    if org.tier != tier:
        raise HTTPException(500, "The payment was recorded but the plan was not restored.")
    return payment


def extend_pilot(db, org: Organization, days: int, now: datetime | None = None) -> dict:
    moment = _now(now)
    if not 1 <= days <= 90:
        raise HTTPException(400, "Days must be between 1 and 90.")
    if org.deleted_at is not None or org.billing_provider != "pilot" or org.trial_ends_at is None:
        raise HTTPException(409, "This organisation is not a pilot.")
    before = as_utc(org.trial_ends_at)
    org.trial_ends_at = max(before, moment) + timedelta(days=days)
    org.trial_reminder_5d_sent = False
    org.trial_reminder_2d_sent = False
    reactivated = False
    if org.tier == "starter":
        org.tier = "growth"
        org.retention_grace_tier = None
        org.retention_grace_until = None
        reactivated = True
    return {
        "trial_ends_at_before": before.isoformat(),
        "trial_ends_at_after": org.trial_ends_at.isoformat(),
        "reactivated": reactivated,
    }


def _locked_credit(db, credit_id: str) -> Credit:
    try:
        canonical = str(uuid.UUID(credit_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(404, "No credit with that id.")
    credit = (
        db.query(Credit).filter(Credit.id == canonical).populate_existing().with_for_update().first()
    )
    if credit is None:
        raise HTTPException(404, "No credit with that id.")
    return credit


def revoke_referral_credit(db, credit_id: str, reason: str, now: datetime | None = None) -> Credit:
    """Revoke a credit that has not been used (pending, held or available)."""
    credit = _locked_credit(db, credit_id)
    if not revoke_credit(credit, reason, _now(now)):
        raise HTTPException(409, f"A {credit.status} credit cannot be revoked.")
    return credit


def approve_referral_credit(db, credit_id: str, now: datetime | None = None) -> Credit:
    """Release a credit held for review: it becomes available."""
    credit = _locked_credit(db, credit_id)
    if not approve_credit(credit, _now(now)):
        raise HTTPException(409, f"Only a held credit can be approved, this one is {credit.status}.")
    return credit


def generate_pilot_codes(db, count: int) -> list[str]:
    """Single-use pilot codes (kind 'admin', 30 days of Growth at registration)."""
    if not 1 <= count <= 50:
        raise HTTPException(400, "Count must be between 1 and 50.")
    # Phase 14: the documented lifetime cap of 500 pilot codes.
    issued = db.query(PromoCode.id).filter(PromoCode.kind == "admin").count()
    if issued + count > PILOT_CODE_LIFETIME_CAP:
        raise HTTPException(
            400, f"Pilot code limit reached: {issued} of {PILOT_CODE_LIFETIME_CAP} codes already issued."
        )
    codes: list[str] = []
    while len(codes) < count:
        code = "CLEW-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(5))
        if code in codes or db.query(PromoCode.id).filter(PromoCode.code == code).first():
            continue
        codes.append(code)
    for code in codes:
        db.add(PromoCode(code=code, kind="admin", max_redemptions=1))
    return codes
