"""api/referrals.py: Phase 12, referrals on a credit ledger.

The rules (docs and TODO.md Phase 12):
- A referred org (it registered with someone's REF- code) gets one month free
  on its second bill: the first Bill generated after its first payment is
  covered by a `referee_free_bill` credit worth one month of the bill's plan
  at list price. A monthly bill is covered in full and issued already paid. An
  annual bill keeps the rest payable.
- Its referrer earns a `referrer_reward` credit when the referee first pays.
  The credit starts `pending` and becomes `available` once the referee's first
  payment has stood for the 72 hour refund window without a refund. A refund
  inside the window revokes it while it is still pending.
- Available credit reduces the referrer's own next bills (apply_credits_to_bill,
  called by the daily billing cycle). It is never paid out as cash.
- The credit is worth REFERRAL_CREDIT_PCT percent (default 100) of
  min(the annual list price of the referrer's tier, the referee's first
  payment), so a referee on an annual plan earns more than a monthly one. A
  referrer on the free plan has no cap. No exchange rate is ever used: in
  another currency the credit is re-valued at list price (api/tiers.py).
- A referrer who vests more than VELOCITY_HOLD_AFTER credits inside
  VELOCITY_WINDOW has the extra ones held until staff approve them.

Kept in its own module, not api/tiers.py, since these functions need a DB
session and api/tiers.py is otherwise a plain-constants module. Nothing here
commits: the caller owns the transaction.
"""
import logging
import os
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.billing_rules import as_utc
from api.tiers import MIN_ORDER_MINOR, PAID_TIER_ORDER, plan_price
from db.models import Bill, Credit, Organization, Payment, PromoCode, PromoCodeRedemption

logger = logging.getLogger(__name__)

_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I, same alphabet as the ops panel pilot codes (api/staff_ops.py)

REWARD_KIND = "referrer_reward"
FREE_BILL_KIND = "referee_free_bill"

# Equal to api.billing_payments.REFUND_WINDOW (a test pins them together; that
# module imports this one, so it cannot be imported here).
VEST_DELAY = timedelta(hours=72)

# More than this many credits vesting for one referrer inside the window are
# held for staff review.
VELOCITY_HOLD_AFTER = 3
VELOCITY_WINDOW = timedelta(days=30)

# Referral codes have no redemption cap. PromoCode.max_redemptions is only
# enforced for admin codes, so new referral rows carry this placeholder.
REFERRAL_CODE_MAX_REDEMPTIONS = 0


def credit_pct() -> int:
    """Credit as a percent of the earning base. REFERRAL_CREDIT_PCT, 0 to 100,
    default 100. Read on every call so it can change without a code release."""
    raw = os.environ.get("REFERRAL_CREDIT_PCT", "").strip()
    if not raw:
        return 100
    try:
        return max(0, min(100, int(raw)))
    except ValueError:
        logger.warning("referrals: REFERRAL_CREDIT_PCT=%r is not an integer, using 100", raw)
        return 100


def generate_referral_code(db: Session) -> str:
    """REF-XXXXX, collision-checked against every existing code (admin and
    referral alike share one unique code namespace)."""
    while True:
        code = "REF-" + "".join(secrets.choice(_ALPHABET) for _ in range(5))
        if db.query(PromoCode).filter(PromoCode.code == code).first() is None:
            return code


def own_referral_code(org: Organization, db: Session) -> PromoCode | None:
    return (
        db.query(PromoCode)
        .filter(PromoCode.owner_org_id == org.id, PromoCode.kind == "referral")
        .first()
    )


def code_unavailable_reason(promo: PromoCode | None, db: Session) -> str | None:
    """Why a code cannot be used to register, or None when it can. An admin
    code must be unredeemed. A referral code needs a live owner: one whose
    org was purged (owner NULL) or is deleted refuses new signups, the
    existing referees keep their attribution."""
    if promo is None:
        return "not_found"
    if promo.kind == "admin":
        return "redeemed" if promo.redeemed_at is not None else None
    owner = db.get(Organization, promo.owner_org_id) if promo.owner_org_id else None
    if owner is None or owner.deleted_at is not None:
        return "owner_gone"
    return None


def _list_price(currency: str, tier: str | None, period: str | None) -> int | None:
    if not tier or not period:
        return None
    try:
        return plan_price(currency, tier, period)
    except ValueError:
        return None


def reward_terms(referrer: Organization, payment: Payment) -> tuple[int, str, str | None, str | None]:
    """(amount, currency, basis_tier, basis_period) of the credit the referrer
    earns for the referee's first `payment`. The amount is fixed here, at
    earn time. Amount 0 means no credit."""
    items = payment.line_items or {}
    tier, period = items.get("tier"), items.get("period")
    if referrer.billing_country:
        currency = referrer.billing_currency
        if payment.currency == currency:
            value = payment.amount_paise
        else:
            value = _list_price(currency, tier, period) or 0
        if referrer.tier in PAID_TIER_ORDER:
            cap = _list_price(currency, referrer.tier, "annual")
            if cap is not None:
                value = min(value, cap)
    else:
        # No currency chosen yet (the referrer never checked out). The credit
        # starts in the referee's currency and is re-valued at list price in
        # the currency of the referrer's first bill if that differs.
        currency = payment.currency
        value = payment.amount_paise
    return value * credit_pct() // 100, currency, tier, period


def confirm_first_payment(org: Organization, db: Session, payment: Payment, now: datetime) -> None:
    """Called exactly when an org's first-ever charge is captured, right
    alongside the first_charged_at-is-None guard in apply_captured_payment.
    For a referred org it marks the redemption confirmed and creates the
    referrer's pending credit. A no-op for an org that was not referred, and
    idempotent: one credit per referee, ever."""
    if org.referred_by_promo_code_id is None:
        return
    redemption = (
        db.query(PromoCodeRedemption)
        .filter(
            PromoCodeRedemption.promo_code_id == org.referred_by_promo_code_id,
            PromoCodeRedemption.redeemed_by_org_id == org.id,
        )
        .first()
    )
    if redemption is None:
        return
    if redemption.first_payment_confirmed_at is None:
        redemption.first_payment_confirmed_at = now
    promo = db.get(PromoCode, org.referred_by_promo_code_id)
    referrer = db.get(Organization, promo.owner_org_id) if promo is not None and promo.owner_org_id else None
    if referrer is None or referrer.deleted_at is not None or referrer.id == org.id:
        return
    already = (
        db.query(Credit.id)
        .filter(Credit.kind == REWARD_KIND, Credit.source_org_id == org.id)
        .first()
    )
    if already is not None:
        return
    amount, currency, tier, period = reward_terms(referrer, payment)
    if amount <= 0:
        return
    db.add(
        Credit(
            org_id=referrer.id,
            kind=REWARD_KIND,
            status="pending",
            amount_paise=amount,
            currency=currency,
            basis_tier=tier,
            basis_period=period,
            source_org_id=org.id,
            redemption_id=redemption.id,
            earned_at=now,
        )
    )


# ---------------------------------------------------------------------------
# Vesting
# ---------------------------------------------------------------------------

def pending_reward_ids(db: Session) -> list[str]:
    rows = (
        db.query(Credit.id)
        .filter(Credit.kind == REWARD_KIND, Credit.status == "pending")
        .order_by(Credit.earned_at)
        .all()
    )
    return [r[0] for r in rows]


def referee_cleared(db: Session, referee_id: str | None, now: datetime) -> bool:
    """True when the referee's first payment has been captured for the whole
    72 hour refund window and has not been refunded."""
    if referee_id is None:
        return False
    referee = db.get(Organization, referee_id)
    if referee is None or referee.deleted_at is not None:
        return False
    first = (
        db.query(Payment)
        .filter(Payment.org_id == referee_id, Payment.captured_at.isnot(None))
        .order_by(Payment.captured_at)
        .first()
    )
    if first is None or first.status != "captured":
        return False
    return as_utc(now) >= as_utc(first.captured_at) + VEST_DELAY


def vest_one(db: Session, credit_id: str, now: datetime) -> str:
    """Vest one pending referrer credit if its referee has cleared. Returns
    'vested', 'held' or 'waiting'. Idempotent: a credit that is no longer
    pending is left alone ('waiting')."""
    credit = (
        db.query(Credit)
        .filter(Credit.id == credit_id)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if credit is None or credit.status != "pending" or credit.kind != REWARD_KIND:
        return "waiting"
    if not referee_cleared(db, credit.source_org_id, now):
        return "waiting"
    recent = (
        db.query(func.count(Credit.id))
        .filter(
            Credit.org_id == credit.org_id,
            Credit.kind == REWARD_KIND,
            Credit.status.in_(("available", "applied")),
            Credit.vests_at >= now - VELOCITY_WINDOW,
        )
        .scalar()
    ) or 0
    if recent >= VELOCITY_HOLD_AFTER:
        credit.status = "held"
        credit.held_reason = (
            f"More than {VELOCITY_HOLD_AFTER} referral credits vested in {VELOCITY_WINDOW.days} days"
        )
        return "held"
    credit.status = "available"
    credit.vests_at = now
    return "vested"


# ---------------------------------------------------------------------------
# Revoke and approve (the refund hook and the staff panel)
# ---------------------------------------------------------------------------

REVOCABLE = ("pending", "held", "available")


def revoke_credit(credit: Credit, reason: str, now: datetime) -> bool:
    """Revoke a credit that has not been used. Applied and revoked credits are
    left alone (False)."""
    if credit.status not in REVOCABLE:
        return False
    credit.status = "revoked"
    credit.revoked_at = now
    credit.revoked_reason = reason[:200]
    return True


def approve_credit(credit: Credit, now: datetime) -> bool:
    """Release a held credit: it becomes available as if it had vested now."""
    if credit.status != "held":
        return False
    credit.status = "available"
    credit.vests_at = now
    credit.held_reason = None
    return True


def revoke_for_refunded_referee(db: Session, referee_id: str, now: datetime) -> int:
    """A refund inside the 72 hour window cancels the referrer's credit that
    this referee earned, while it is still unvested. Returns how many."""
    credits = (
        db.query(Credit)
        .filter(
            Credit.kind == REWARD_KIND,
            Credit.source_org_id == referee_id,
            Credit.status.in_(("pending", "held")),
        )
        .with_for_update()
        .all()
    )
    return sum(1 for c in credits if revoke_credit(c, "The referred account was refunded", now))


# ---------------------------------------------------------------------------
# Applying credit to a bill (the daily billing cycle)
# ---------------------------------------------------------------------------

def _free_bill_due(db: Session, org: Organization, bill: Bill) -> PromoCodeRedemption | None:
    """The redemption that entitles `org` to a free first bill, or None. Only
    the first Bill ever issued to a referred org whose first payment is
    confirmed, and only once."""
    if org.referred_by_promo_code_id is None:
        return None
    redemption = (
        db.query(PromoCodeRedemption)
        .filter(
            PromoCodeRedemption.promo_code_id == org.referred_by_promo_code_id,
            PromoCodeRedemption.redeemed_by_org_id == org.id,
            PromoCodeRedemption.first_payment_confirmed_at.isnot(None),
        )
        .first()
    )
    if redemption is None:
        return None
    if db.query(Credit.id).filter(Credit.org_id == org.id, Credit.kind == FREE_BILL_KIND).first() is not None:
        return None
    earlier = db.query(Bill.id).filter(Bill.org_id == org.id, Bill.id != bill.id).first()
    return None if earlier is not None else redemption


def _value_in(credit: Credit, bill: Bill) -> int | None:
    """What an available credit is worth against `bill`. In the bill's own
    currency it is worth its stored amount. In another it is re-valued at list
    price and never above the annual price of the bill's tier, the same cap a
    credit earned in that currency would have. None when it cannot be valued."""
    if credit.currency == bill.currency:
        return credit.amount_paise
    price = _list_price(bill.currency, credit.basis_tier, credit.basis_period)
    if price is None:
        return None
    value = price * credit_pct() // 100
    cap = _list_price(bill.currency, bill.tier, "annual")
    return min(value, cap) if cap is not None else value


def apply_credits_to_bill(db: Session, org: Organization, bill: Bill, now: datetime) -> int:
    """Reduce a freshly issued, still open `bill` by the org's credit and
    return the amount applied (minor units). The bill must already be in the
    session (flushed). First the referee's free month (one month of the bill's
    plan at list price, the whole bill when it is monthly), then available
    referrer credit, oldest first. A partly used credit is split. A bill is
    never left with an order total below the payment minimum: the credit
    applied is reduced to keep it payable. A bill covered in full is marked
    paid here, with no payment."""
    price = bill.amount_paise
    free = 0
    redemption = _free_bill_due(db, org, bill)
    if redemption is not None:
        month = _list_price(bill.currency, bill.tier, "monthly")
        free = min(price, month) if month is not None else price
        db.add(
            Credit(
                org_id=org.id,
                kind=FREE_BILL_KIND,
                status="applied",
                amount_paise=free,
                currency=bill.currency,
                basis_tier=bill.tier,
                basis_period=bill.period,
                redemption_id=redemption.id,
                earned_at=now,
                vests_at=now,
                applied_at=now,
                applied_bill_id=bill.id,
            )
        )
    left = price - free

    credits = (
        db.query(Credit)
        .filter(Credit.org_id == org.id, Credit.kind == REWARD_KIND, Credit.status == "available")
        .order_by(Credit.vests_at, Credit.earned_at)
        .with_for_update()
        .all()
    ) if left > 0 else []
    usable: list[Credit] = []
    for credit in credits:
        value = _value_in(credit, bill)
        if value is None or value <= 0:
            continue
        credit.currency = bill.currency
        credit.amount_paise = value
        usable.append(credit)

    use = min(sum(c.amount_paise for c in usable), left)
    net = left - use
    if 0 < net < MIN_ORDER_MINOR[bill.currency]:
        use = max(left - MIN_ORDER_MINOR[bill.currency], 0)
    if use <= 0 and free == 0:
        return 0

    remaining = use
    for credit in usable:
        if remaining <= 0:
            break
        if credit.amount_paise > remaining:
            db.add(
                Credit(
                    org_id=credit.org_id,
                    kind=credit.kind,
                    status="available",
                    amount_paise=credit.amount_paise - remaining,
                    currency=credit.currency,
                    basis_tier=credit.basis_tier,
                    basis_period=credit.basis_period,
                    source_org_id=credit.source_org_id,
                    redemption_id=credit.redemption_id,
                    earned_at=credit.earned_at,
                    vests_at=credit.vests_at,
                )
            )
            credit.amount_paise = remaining
        remaining -= credit.amount_paise
        credit.status = "applied"
        credit.applied_at = now
        credit.applied_bill_id = bill.id

    applied = free + use
    bill.credit_applied_paise = applied
    bill.amount_paise = price - applied
    if bill.amount_paise == 0:
        bill.status = "paid"
        bill.paid_at = now
    return applied


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------

def _money_totals(credits: list[Credit]) -> dict[str, dict[str, int]]:
    """Per currency totals by state. Held credits count as pending."""
    totals: dict[str, dict[str, int]] = {}
    for c in credits:
        if c.kind != REWARD_KIND or c.status == "revoked":
            continue
        bucket = totals.setdefault(c.currency, {"pending": 0, "available": 0, "applied": 0})
        key = "pending" if c.status in ("pending", "held") else c.status
        bucket[key] += c.amount_paise
    return totals


def referral_summary(org: Organization, db: Session) -> dict:
    """What the org owner sees: the shareable code, whether this org was
    itself referred and where its free bill stands, how many referrals have
    signed up and paid, and the credit ledger. Referees are never named."""
    code = own_referral_code(org, db)
    signups = paying = 0
    if code is not None:
        redemptions = (
            db.query(PromoCodeRedemption).filter(PromoCodeRedemption.promo_code_id == code.id).all()
        )
        signups = len(redemptions)
        paying = sum(1 for r in redemptions if r.first_payment_confirmed_at is not None)

    free_bill = (
        db.query(Credit)
        .filter(Credit.org_id == org.id, Credit.kind == FREE_BILL_KIND)
        .first()
    )
    referred_state = None
    if org.referred_by_promo_code_id is not None:
        referred_state = "applied" if free_bill is not None else (
            "waiting_for_first_bill" if org.first_charged_at is not None else "waiting_for_first_payment"
        )

    credits = (
        db.query(Credit)
        .filter(Credit.org_id == org.id, Credit.kind == REWARD_KIND)
        .order_by(Credit.earned_at.desc())
        .all()
    )
    plan_monthly = None
    if org.tier in PAID_TIER_ORDER and org.billing_country:
        plan_monthly = _list_price(org.billing_currency, org.tier, "monthly")
    return {
        "referral_code": code.code if code else None,
        "credit_pct": credit_pct(),
        "is_referred": org.referred_by_promo_code_id is not None,
        "referred_state": referred_state,
        "free_bill_paise": free_bill.amount_paise if free_bill is not None else None,
        "free_bill_currency": free_bill.currency if free_bill is not None else None,
        "plan_monthly_paise": plan_monthly,
        "plan_currency": org.billing_currency if plan_monthly is not None else None,
        "signups": signups,
        "paying": paying,
        "totals": _money_totals(credits),
        "credits": [
            {
                "id": c.id,
                "status": "pending" if c.status == "held" else c.status,
                "amount_paise": c.amount_paise,
                "currency": c.currency,
                "earned_at": c.earned_at.isoformat() if c.earned_at else None,
                "releases_at": (
                    (as_utc(c.earned_at) + VEST_DELAY).isoformat()
                    if c.status in ("pending", "held") and c.earned_at else None
                ),
                "vests_at": c.vests_at.isoformat() if c.vests_at else None,
                "applied_at": c.applied_at.isoformat() if c.applied_at else None,
            }
            for c in credits
        ],
    }


def staff_referral_summary(org: Organization, db: Session) -> dict:
    """Flat key/value view for the staff account page."""
    summary = referral_summary(org, db)
    parent = None
    if org.referred_by_promo_code_id is not None:
        promo = db.get(PromoCode, org.referred_by_promo_code_id)
        parent = promo.owner_org_id if promo is not None else None
    flat: dict = {
        "referral_code": summary["referral_code"],
        "referred_by_org_id": parent,
        "referred_state": summary["referred_state"],
        "signups": summary["signups"],
        "paying": summary["paying"],
        "credit_pct": summary["credit_pct"],
    }
    for currency, bucket in summary["totals"].items():
        for state, value in bucket.items():
            flat[f"credit_{state}_{currency.lower()}_minor"] = value
    flat["credits_held"] = db.query(Credit).filter(Credit.org_id == org.id, Credit.status == "held").count()
    return flat
