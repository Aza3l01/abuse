"""api/referrals.py: TODO.md priority item 5, referral/pilot code system.

Pure discount-calculation and code-generation helpers, shared by
api/routes/org.py (redemption at registration, dashboard summary) and
api/routes/billing.py (applying the discount at checkout, marking a slot
live once a charge is confirmed). Kept in its own module, not api/tiers.py,
since these functions need a DB session and api/tiers.py is otherwise a
plain-constants module with no DB dependency.

All percentages are fixed constants, never configurable per code, and are
always applied against frontend/src/lib/pricing.ts's PRICING_TIERS-derived
price at calculation time, never stored as an absolute amount.
"""
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.models import Organization, PromoCode, PromoCodeRedemption

_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I, matches generate_promo_codes.py

REFERRAL_MAX_SLOTS = 5

# Monthly carries a tighter cap than annual: monthly is an open-ended
# recurring commitment with real churn risk, annual is prepaid and
# non-refundable beyond 72 hours, so a deeper discount there is against
# cash already collected and locked in for a year.
_RATES = {
    "monthly": {"referred_flat": 0.05, "per_slot": 0.05, "max_stacked": 0.30},
    "annual":  {"referred_flat": 0.10, "per_slot": 0.10, "max_stacked": 0.60},
}


def generate_referral_code(db: Session) -> str:
    """REF-XXXXX, collision-checked against every existing code (admin and
    referral alike share one unique code namespace)."""
    while True:
        code = "REF-" + "".join(secrets.choice(_ALPHABET) for _ in range(5))
        if db.query(PromoCode).filter(PromoCode.code == code).first() is None:
            return code


def live_slot_count(org: Organization, db: Session) -> int:
    """How many of this org's own referral-code slots are currently live:
    the referred org's first invoice was actually paid AND that org's
    subscription is still active (tier != 'free') and not deleted. Always
    re-derived from current state, never a stored counter, so a churned
    referral frees its slot the instant the referred org's tier reverts to
    free, with no separate bookkeeping step required anywhere.
    """
    own_code = (
        db.query(PromoCode)
        .filter(PromoCode.owner_org_id == org.id, PromoCode.kind == "referral")
        .first()
    )
    if own_code is None:
        return 0
    count = (
        db.query(PromoCodeRedemption)
        .join(Organization, Organization.id == PromoCodeRedemption.redeemed_by_org_id)
        .filter(
            PromoCodeRedemption.promo_code_id == own_code.id,
            PromoCodeRedemption.first_payment_confirmed_at.isnot(None),
            Organization.tier != "free",
            Organization.deleted_at.is_(None),
        )
        .count()
    )
    return min(count, REFERRAL_MAX_SLOTS)


def compute_referral_discount_pct(org: Organization, period: str, db: Session) -> float:
    """Total stacked discount percentage (0.0-0.60) for this org's own next
    charge. period is "monthly" or "annual". If org was itself referred,
    its flat discount and its own slot-based discount (as a referrer) stack
    additively, capped at the period's max. Always recomputed from current
    DB state, never cached or stored.
    """
    rates = _RATES.get(period.lower(), _RATES["monthly"])
    referred_flat = rates["referred_flat"] if org.referred_by_promo_code_id else 0.0
    referrer_pct = live_slot_count(org, db) * rates["per_slot"]
    return min(referred_flat + referrer_pct, rates["max_stacked"])


def referral_summary(org: Organization, db: Session) -> dict:
    """Dashboard-facing summary: this org's own shareable code, live slot
    count out of REFERRAL_MAX_SLOTS, whether this org itself was referred,
    and the currently-applicable discount for each billing period.
    """
    own_code = (
        db.query(PromoCode)
        .filter(PromoCode.owner_org_id == org.id, PromoCode.kind == "referral")
        .first()
    )
    return {
        "referral_code": own_code.code if own_code else None,
        "slots_filled": live_slot_count(org, db),
        "slots_total": REFERRAL_MAX_SLOTS,
        "is_referred": org.referred_by_promo_code_id is not None,
        "discount_pct_monthly": compute_referral_discount_pct(org, "monthly", db),
        "discount_pct_annual": compute_referral_discount_pct(org, "annual", db),
    }


def confirm_first_payment(org: Organization, db: Session) -> None:
    """Called exactly when an org's first-ever charge is confirmed
    (razorpay_verify_payment and the subscription.activated webhook, right
    alongside their own first_charged_at-is-None guard). If this org signed
    up via someone else's referral code, marks that redemption's slot live.
    A no-op for an org that was not referred, or whose slot is already
    marked (idempotent, mirrors the first_charged_at guard it sits next to).
    """
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
    if redemption is not None and redemption.first_payment_confirmed_at is None:
        redemption.first_payment_confirmed_at = datetime.now(timezone.utc)
