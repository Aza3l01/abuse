"""Phase 12: referrals on a credit ledger (api/referrals.py).

Unit tests on the ledger rules, the billing cycle timeline that walks a
referral from signup to an applied credit, the refund hook, the public code
check and the signup rules for a referral code.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from api import referrals
from api.billing_payments import apply_captured_payment
from api.billing_rules import ist_date, ist_midnight
from api.referrals import (
    FREE_BILL_KIND,
    REWARD_KIND,
    VELOCITY_HOLD_AFTER,
    approve_credit,
    apply_credits_to_bill,
    confirm_first_payment,
    revoke_credit,
    vest_one,
)
from api.routes.org import create_organization
from api.tests.billing_testkit import make_org
from api.tests.conftest import make_bill
from api.tiers import plan_price
from db.models import Bill, Client, Credit, Organization, Payment, PromoCode, PromoCodeRedemption
from workers.tasks import billing_cycle as cycle

BASIC_M = plan_price("INR", "basic", "monthly")
BASIC_A = plan_price("INR", "basic", "annual")
GROWTH_M = plan_price("INR", "growth", "monthly")
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


# --- helpers ---------------------------------------------------------------

def _referrer(db, **extra) -> tuple[Organization, PromoCode]:
    org = make_org(
        db, tier=extra.pop("tier", "basic"), period=extra.pop("period", "monthly"),
        name=extra.pop("name", "Referrer"), **extra,
    )
    code = PromoCode(code=f"REF-{uuid.uuid4().hex[:5].upper()}", kind="referral", owner_org_id=org.id, max_redemptions=0)
    db.add(code)
    db.commit()
    return org, code


def _referee(db, code: PromoCode, name: str = "Referee", **extra) -> Organization:
    org = make_org(
        db, tier="starter", period=None, name=name, referred_by_promo_code_id=code.id, **extra
    )
    db.add(PromoCodeRedemption(promo_code_id=code.id, redeemed_by_org_id=org.id, redeemed_at=NOW - timedelta(days=1)))
    db.commit()
    return org


def _payment(db, org, *, purpose="initial", tier="basic", period="monthly", amount=None, bill_ids=None,
             currency="INR") -> Payment:
    items = {"tier": tier, "period": period, "description": f"{tier} {period}"}
    if bill_ids:
        items["bill_ids"] = bill_ids
    p = Payment(
        org_id=org.id,
        org_name_snapshot=org.company_name,
        razorpay_order_id=f"order_{uuid.uuid4().hex[:12]}",
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        amount_paise=amount if amount is not None else plan_price(currency, tier, period),
        currency=currency,
        purpose=purpose,
        status="created",
        line_items=items,
        tos_accepted=True,
    )
    db.add(p)
    db.commit()
    return p


def _first_purchase(db, org, now=NOW, **kw) -> Payment:
    p = _payment(db, org, **kw)
    assert apply_captured_payment(p, db, now=now)
    db.commit()
    return p


def _pay_bill(db, org, bill: Bill, now: datetime) -> None:
    p = _payment(db, org, purpose="bill", tier=bill.tier, period=bill.period, amount=bill.amount_paise,
                 bill_ids=[bill.id])
    assert apply_captured_payment(p, db, now=now)
    db.commit()


def _credits(db, org, kind=REWARD_KIND) -> list[Credit]:
    return db.query(Credit).filter(Credit.org_id == org.id, Credit.kind == kind).order_by(Credit.earned_at).all()


def _available(db, org, amount=BASIC_M, *, vests_at=NOW, currency="INR", tier="basic", period="monthly") -> Credit:
    c = Credit(
        org_id=org.id, kind=REWARD_KIND, status="available", amount_paise=amount, currency=currency,
        basis_tier=tier, basis_period=period, earned_at=vests_at, vests_at=vests_at,
    )
    db.add(c)
    db.commit()
    return c


def _pending_for(db, referrer, referee) -> Credit:
    c = Credit(
        org_id=referrer.id, kind=REWARD_KIND, status="pending", amount_paise=BASIC_M, currency="INR",
        basis_tier="basic", basis_period="monthly", source_org_id=referee.id, earned_at=NOW,
    )
    db.add(c)
    db.commit()
    return c


# --- earning ---------------------------------------------------------------

def test_first_payment_of_a_referred_org_creates_one_pending_credit(db):
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    _first_purchase(db, referee)

    [credit] = _credits(db, referrer)
    assert (credit.status, credit.amount_paise, credit.currency) == ("pending", BASIC_M, "INR")
    assert credit.source_org_id == referee.id
    redemption = db.query(PromoCodeRedemption).one()
    assert redemption.first_payment_confirmed_at is not None
    assert _credits(db, referee) == []


def test_confirming_twice_leaves_one_credit(db):
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    p = _first_purchase(db, referee)
    confirm_first_payment(referee, db, p, NOW + timedelta(days=1))
    db.commit()
    assert len(_credits(db, referrer)) == 1


def test_an_org_that_was_not_referred_earns_nobody_anything(db):
    referrer, _ = _referrer(db)
    plain = make_org(db, tier="starter", period=None, name="Plain")
    _first_purchase(db, plain)
    assert db.query(Credit).count() == 0


def test_a_deleted_referrer_earns_nothing_but_the_referee_is_still_confirmed(db):
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    referrer.deleted_at = NOW
    db.commit()
    _first_purchase(db, referee)
    assert db.query(Credit).count() == 0
    assert db.query(PromoCodeRedemption).one().first_payment_confirmed_at is not None


def test_the_credit_is_capped_at_the_annual_price_of_the_referrers_tier(db):
    referrer, code = _referrer(db, tier="basic")
    referee = _referee(db, code)
    _first_purchase(db, referee, tier="pro", period="annual")
    [credit] = _credits(db, referrer)
    assert credit.amount_paise == BASIC_A < plan_price("INR", "pro", "annual")


def test_a_monthly_referrer_is_rewarded_in_full_for_an_annual_referee(db):
    referrer, code = _referrer(db, tier="basic", period="monthly")
    referee = _referee(db, code)
    _first_purchase(db, referee, tier="basic", period="annual")
    [credit] = _credits(db, referrer)
    assert credit.amount_paise == BASIC_A > BASIC_M


def test_a_referrer_on_a_cheaper_payment_gets_the_payment_amount(db):
    referrer, code = _referrer(db, tier="growth")
    referee = _referee(db, code)
    _first_purchase(db, referee, tier="basic", period="monthly")
    [credit] = _credits(db, referrer)
    assert credit.amount_paise == BASIC_M


def test_a_referrer_on_the_free_plan_is_not_capped(db):
    referrer, code = _referrer(db, tier="starter", period=None, billing_provider=None)
    referee = _referee(db, code)
    _first_purchase(db, referee, tier="growth", period="monthly")
    [credit] = _credits(db, referrer)
    assert credit.amount_paise == GROWTH_M


def test_credit_pct_scales_the_credit(db, monkeypatch):
    monkeypatch.setenv("REFERRAL_CREDIT_PCT", "50")
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    _first_purchase(db, referee)
    [credit] = _credits(db, referrer)
    assert credit.amount_paise == BASIC_M // 2


@pytest.mark.parametrize("raw,expected", [("", 100), ("abc", 100), ("150", 100), ("-5", 0), ("0", 0), ("25", 25)])
def test_credit_pct_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("REFERRAL_CREDIT_PCT", raw)
    assert referrals.credit_pct() == expected


def test_zero_percent_creates_no_credit(db, monkeypatch):
    monkeypatch.setenv("REFERRAL_CREDIT_PCT", "0")
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    _first_purchase(db, referee)
    assert db.query(Credit).count() == 0


def test_a_credit_in_another_currency_is_valued_at_list_price_not_converted(db):
    referrer, code = _referrer(db, billing_currency="USD", billing_country="US")
    referee = _referee(db, code)
    _first_purchase(db, referee)  # the referee pays in INR
    [credit] = _credits(db, referrer)
    assert credit.currency == "USD"
    assert credit.amount_paise == plan_price("USD", "basic", "monthly")


def test_a_referrer_with_no_currency_yet_gets_the_referees_currency(db):
    referrer, code = _referrer(db, tier="starter", period=None, billing_provider=None,
                               billing_country=None, billing_currency="USD")
    referee = _referee(db, code)
    _first_purchase(db, referee)
    [credit] = _credits(db, referrer)
    assert (credit.currency, credit.amount_paise) == ("INR", BASIC_M)


# --- vesting ---------------------------------------------------------------

LATER = NOW + timedelta(hours=73)


def test_vest_delay_matches_the_refund_window():
    from api.billing_payments import REFUND_WINDOW
    assert referrals.VEST_DELAY == REFUND_WINDOW


def test_a_credit_waits_for_the_refund_window_then_vests(db):
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    _first_purchase(db, referee)
    [credit] = _credits(db, referrer)

    assert vest_one(db, credit.id, NOW) == "waiting"
    assert vest_one(db, credit.id, NOW + timedelta(hours=71, minutes=59)) == "waiting"

    assert vest_one(db, credit.id, NOW + timedelta(hours=72)) == "vested"
    db.commit()
    db.refresh(credit)
    assert credit.status == "available" and credit.vests_at is not None
    assert vest_one(db, credit.id, LATER + timedelta(days=1)) == "waiting"  # idempotent


def test_a_refunded_first_payment_does_not_vest(db):
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    first = _first_purchase(db, referee)
    [credit] = _credits(db, referrer)
    first.status = "refunded"
    db.commit()
    assert vest_one(db, credit.id, LATER) == "waiting"


def test_a_deleted_referee_does_not_vest(db):
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    _first_purchase(db, referee)
    [credit] = _credits(db, referrer)
    referee.deleted_at = NOW + timedelta(hours=1)
    db.commit()
    assert vest_one(db, credit.id, LATER) == "waiting"


def test_the_fourth_credit_inside_30_days_is_held_and_approval_releases_it(db):
    referrer, code = _referrer(db)
    credits = []
    for i in range(VELOCITY_HOLD_AFTER + 1):
        referee = _referee(db, code, name=f"Referee {i}")
        _first_purchase(db, referee)
        credits.append(_credits(db, referrer)[-1])
    outcomes = []
    for i, c in enumerate(credits):
        outcomes.append(vest_one(db, c.id, LATER + timedelta(minutes=i)))
        db.commit()  # the cycle commits after each credit
    assert outcomes == ["vested"] * VELOCITY_HOLD_AFTER + ["held"]
    held = credits[-1]
    db.refresh(held)
    assert held.status == "held" and held.held_reason

    assert approve_credit(held, NOW + timedelta(days=60)) is True
    assert (held.status, held.held_reason) == ("available", None)
    assert approve_credit(held, NOW) is False  # no longer held


def test_vesting_older_than_the_window_does_not_count_toward_the_hold(db):
    referrer, code = _referrer(db)
    for i in range(VELOCITY_HOLD_AFTER):
        _available(db, referrer, vests_at=LATER - timedelta(days=45 + i))
    referee = _referee(db, code)
    _first_purchase(db, referee)
    credit = _credits(db, referrer)[-1]
    assert vest_one(db, credit.id, LATER) == "vested"


def test_revoke_only_touches_an_unused_credit(db):
    referrer, _ = _referrer(db)
    c = _available(db, referrer)
    assert revoke_credit(c, "x" * 300, NOW) is True
    assert c.status == "revoked" and len(c.revoked_reason) == 200
    assert revoke_credit(c, "again", NOW) is False
    applied = _available(db, referrer)
    applied.status = "applied"
    assert revoke_credit(applied, "no", NOW) is False


# --- applying credit to a bill ------------------------------------------------

def test_the_free_bill_is_the_first_bill_only_and_only_once(db):
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    _first_purchase(db, referee)

    first = make_bill(db, referee, amount=BASIC_M, start=date(2026, 12, 1))
    assert apply_credits_to_bill(db, referee, first, NOW) == BASIC_M
    db.commit()
    assert (first.status, first.amount_paise, first.credit_applied_paise) == ("paid", 0, BASIC_M)
    assert first.paid_at is not None and first.payment_id is None
    [free] = _credits(db, referee, FREE_BILL_KIND)
    assert (free.status, free.applied_bill_id) == ("applied", first.id)

    second = make_bill(db, referee, amount=BASIC_M, start=date(2027, 1, 1))
    assert apply_credits_to_bill(db, referee, second, NOW) == 0
    assert (second.status, second.amount_paise) == ("open", BASIC_M)


def test_an_annual_referee_gets_one_free_month_and_pays_the_rest(db):
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    _first_purchase(db, referee, tier="basic", period="annual")

    bill = make_bill(db, referee, period="annual", amount=BASIC_A, start=date(2027, 12, 1))
    assert apply_credits_to_bill(db, referee, bill, NOW) == BASIC_M
    db.commit()
    assert (bill.status, bill.amount_paise, bill.credit_applied_paise) == ("open", BASIC_A - BASIC_M, BASIC_M)
    assert bill.paid_at is None
    [free] = _credits(db, referee, FREE_BILL_KIND)
    assert (free.status, free.amount_paise, free.applied_bill_id) == ("applied", BASIC_M, bill.id)


def test_the_free_month_and_an_available_credit_stack_on_an_annual_bill(db):
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    _first_purchase(db, referee, tier="basic", period="annual")
    _available(db, referee, amount=100_000)

    bill = make_bill(db, referee, period="annual", amount=BASIC_A, start=date(2027, 12, 1))
    assert apply_credits_to_bill(db, referee, bill, NOW) == BASIC_M + 100_000
    assert bill.amount_paise == BASIC_A - BASIC_M - 100_000


def test_no_free_bill_before_the_first_payment_is_confirmed(db):
    referrer, code = _referrer(db)
    referee = _referee(db, code)  # never paid
    bill = make_bill(db, referee, amount=BASIC_M)
    assert apply_credits_to_bill(db, referee, bill, NOW) == 0
    assert bill.status == "open"


def test_an_org_that_already_has_a_bill_gets_no_free_bill(db):
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    _first_purchase(db, referee)
    make_bill(db, referee, amount=BASIC_M, status="void", start=date(2026, 11, 1))
    bill = make_bill(db, referee, amount=BASIC_M, start=date(2026, 12, 1))
    assert apply_credits_to_bill(db, referee, bill, NOW) == 0


def test_available_credit_pays_a_bill_in_full(db):
    org, _ = _referrer(db)
    credit = _available(db, org)
    bill = make_bill(db, org, amount=BASIC_M)
    assert apply_credits_to_bill(db, org, bill, NOW) == BASIC_M
    db.commit()
    assert (bill.status, bill.amount_paise, bill.credit_applied_paise) == ("paid", 0, BASIC_M)
    db.refresh(credit)
    assert (credit.status, credit.applied_bill_id) == ("applied", bill.id)


def test_credit_larger_than_the_bill_is_split_and_the_rest_stays_available(db):
    org, _ = _referrer(db, tier="basic")
    credit = _available(db, org, amount=BASIC_M + 50_000)
    bill = make_bill(db, org, amount=BASIC_M)
    assert apply_credits_to_bill(db, org, bill, NOW) == BASIC_M
    db.commit()
    db.refresh(credit)
    assert (credit.status, credit.amount_paise) == ("applied", BASIC_M)
    [rest] = db.query(Credit).filter(Credit.org_id == org.id, Credit.status == "available").all()
    assert rest.amount_paise == 50_000 and rest.kind == REWARD_KIND


def test_credit_smaller_than_the_bill_leaves_a_net_amount_to_pay(db):
    org, _ = _referrer(db)
    _available(db, org, amount=100_000)
    bill = make_bill(db, org, amount=BASIC_M)
    assert apply_credits_to_bill(db, org, bill, NOW) == 100_000
    assert (bill.status, bill.amount_paise, bill.credit_applied_paise) == ("open", BASIC_M - 100_000, 100_000)


def test_credits_are_used_oldest_first(db):
    org, _ = _referrer(db)
    newer = _available(db, org, amount=60_000, vests_at=NOW + timedelta(days=5))
    older = _available(db, org, amount=60_000, vests_at=NOW)
    bill = make_bill(db, org, amount=80_000)
    assert apply_credits_to_bill(db, org, bill, NOW) == 80_000
    db.commit()
    db.refresh(older)
    db.refresh(newer)
    assert older.status == "applied" and older.amount_paise == 60_000
    assert newer.status == "applied" and newer.amount_paise == 20_000


def test_a_bill_is_never_left_below_the_payment_minimum(db):
    org, _ = _referrer(db)
    credit = _available(db, org, amount=BASIC_M - 50)  # would leave 50 paise, below 100
    bill = make_bill(db, org, amount=BASIC_M)
    used = apply_credits_to_bill(db, org, bill, NOW)
    assert used == BASIC_M - 100
    assert bill.amount_paise == 100 and bill.status == "open"
    db.commit()
    db.refresh(credit)
    assert credit.status == "applied"


def test_a_credit_in_another_currency_is_revalued_and_the_rest_stays_available(db):
    org, _ = _referrer(db)  # bills in INR
    credit = _available(db, org, amount=plan_price("USD", "growth", "monthly"), currency="USD",
                        tier="growth", period="monthly")
    bill = make_bill(db, org, amount=BASIC_M)
    used = apply_credits_to_bill(db, org, bill, NOW)
    assert used == BASIC_M
    db.commit()
    db.refresh(credit)
    assert credit.currency == "INR" and credit.status == "applied"
    [rest] = db.query(Credit).filter(Credit.org_id == org.id, Credit.status == "available").all()
    assert (rest.currency, rest.amount_paise) == ("INR", GROWTH_M - BASIC_M)


def test_revoked_pending_and_held_credits_are_never_applied(db):
    org, _ = _referrer(db)
    for status in ("pending", "held", "revoked"):
        c = _available(db, org)
        c.status = status
    db.commit()
    bill = make_bill(db, org, amount=BASIC_M)
    assert apply_credits_to_bill(db, org, bill, NOW) == 0


# --- the billing cycle timeline -------------------------------------------------

def test_referral_timeline_from_signup_to_an_applied_credit(db):
    """Referee pays Nov 4 2026. The credit stays pending through the 72 hour
    refund window, vests on the next cycle after it, and the referrer's 1 Dec
    bill takes it. The referee's 1 Dec bill is its free month."""
    referrer, code = _referrer(
        db, next_bill=date(2026, 12, 1), first_charged_at=datetime(2026, 10, 4, tzinfo=timezone.utc)
    )
    referee = _referee(db, code)
    _first_purchase(db, referee, now=NOW)
    assert ist_date(db.get(Organization, referee.id).next_billing_date) == date(2026, 12, 1)
    [pending] = _credits(db, referrer)
    assert pending.status == "pending"
    rid, eid, cid = referrer.id, referee.id, pending.id

    def run(day):
        return cycle.run_billing_cycle(db, day, ist_midnight(day) + timedelta(minutes=30))

    for day in (date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 7)):
        assert run(day)["credits_vested"] == 0
        assert db.get(Credit, cid).status == "pending"

    assert run(date(2026, 11, 8))["credits_vested"] == 1
    assert db.get(Credit, cid).status == "available"

    stats = run(date(2026, 12, 1))
    assert stats["credits_applied"] == 2
    referrer_bill = db.query(Bill).filter(Bill.org_id == rid).one()
    assert (referrer_bill.status, referrer_bill.amount_paise, referrer_bill.credit_applied_paise) == ("paid", 0, BASIC_M)
    credit = db.get(Credit, cid)
    assert (credit.status, credit.applied_bill_id) == ("applied", referrer_bill.id)
    referee_bill = db.query(Bill).filter(Bill.org_id == eid).one()
    assert (referee_bill.status, referee_bill.amount_paise, referee_bill.credit_applied_paise) == ("paid", 0, BASIC_M)

    again = run(date(2026, 12, 2))
    assert again["credits_vested"] == 0 and again["credits_applied"] == 0

    stats = run(date(2027, 1, 1))
    jan = db.query(Bill).filter(Bill.org_id == eid, Bill.period_start == date(2027, 1, 1)).one()
    assert (jan.status, jan.amount_paise, jan.credit_applied_paise) == ("open", BASIC_M, 0)


def test_a_refund_inside_the_window_keeps_the_credit_from_vesting_in_the_cycle(db):
    referrer, code = _referrer(db, next_bill=date(2026, 12, 1))
    referee = _referee(db, code)
    first = _first_purchase(db, referee)
    [credit] = _credits(db, referrer)
    referrals.revoke_for_refunded_referee(db, referee.id, NOW + timedelta(hours=2))
    first.status = "refunded"
    db.commit()
    day = date(2026, 11, 10)
    stats = cycle.run_billing_cycle(db, day, ist_midnight(day) + timedelta(minutes=30))
    db.refresh(credit)
    assert credit.status == "revoked" and stats["credits_vested"] == 0


def test_a_credit_vests_even_if_the_referee_never_pays_a_second_bill(db):
    referrer, code = _referrer(db, next_bill=date(2026, 12, 1))
    referee = _referee(db, code)
    _first_purchase(db, referee)
    [credit] = _credits(db, referrer)
    day = date(2026, 11, 20)
    cycle.run_billing_cycle(db, day, ist_midnight(day) + timedelta(minutes=30))
    db.refresh(credit)
    assert credit.status == "available"


# --- refunds ---------------------------------------------------------------

def _buy(env, org):
    order = env.create_order(purpose="initial", tier="basic", period="monthly", accept_blocking_tos=True).json()
    rz_id = env.rp.pay(order["order_id"])
    assert env.verify(order["order_id"], rz_id).status_code == 200
    return rz_id


def test_a_refund_inside_the_window_revokes_the_pending_credit(env, db):
    referrer, code = _referrer(db)
    referee = env.act_as(_referee(db, code))
    _buy(env, referee)
    db.expire_all()
    [credit] = _credits(db, referrer)
    assert credit.status == "pending"

    assert env.client.post("/billing/refund").status_code == 200
    db.expire_all()
    credit = db.get(Credit, credit.id)
    assert credit.status == "revoked" and credit.revoked_at is not None
    assert "refunded" in credit.revoked_reason


def test_the_refund_webhook_revokes_the_credit_too(env, db):
    referrer, code = _referrer(db)
    referee = env.act_as(_referee(db, code))
    rz_id = _buy(env, referee)
    hook = {
        "event": "refund.processed",
        "payload": {"refund": {"entity": {"payment_id": rz_id, "amount": BASIC_M}}},
    }
    assert env.webhook(hook).status_code == 200
    db.expire_all()
    assert _credits(db, referrer)[0].status == "revoked"


def test_an_available_credit_is_not_clawed_back_by_a_later_refund(db):
    referrer, code = _referrer(db)
    referee = _referee(db, code)
    credit = _available(db, referrer)
    credit.source_org_id = referee.id
    db.commit()
    assert referrals.revoke_for_refunded_referee(db, referee.id, NOW) == 0
    assert credit.status == "available"


# --- read models -----------------------------------------------------------

def test_referral_status_route_shows_totals_by_currency_and_never_names_a_referee(env, db):
    referrer, code = _referrer(db)
    referee = _referee(db, code, name="Secret Customer Ltd")
    _pending_for(db, referrer, referee)
    _available(db, referrer, amount=1000)
    applied = _available(db, referrer, amount=500)
    applied.status = "applied"
    db.commit()
    env.act_as(referrer)

    data = env.client.get("/billing/referral-status").json()
    assert data["referral_code"] == code.code
    assert data["signups"] == 1 and data["paying"] == 0
    assert data["totals"]["INR"] == {"pending": BASIC_M, "available": 1000, "applied": 500}
    assert len(data["credits"]) == 3
    assert data["plan_monthly_paise"] == BASIC_M and data["plan_currency"] == "INR"
    pending = [c for c in data["credits"] if c["status"] == "pending"]
    assert len(pending) == 1 and pending[0]["releases_at"] is not None
    assert all(c["releases_at"] is None for c in data["credits"] if c["status"] != "pending")
    assert "Secret Customer" not in str(data) and referee.id not in str(data)


def test_referral_status_for_a_referred_org_tracks_its_free_bill(env, db):
    referrer, code = _referrer(db)
    referee = env.act_as(_referee(db, code))
    assert env.client.get("/billing/referral-status").json()["referred_state"] == "waiting_for_first_payment"
    _buy(env, referee)
    assert env.client.get("/billing/referral-status").json()["referred_state"] == "waiting_for_first_bill"
    db.expire_all()
    bill = make_bill(db, db.get(Organization, referee.id), amount=BASIC_M, start=date(2026, 12, 1))
    apply_credits_to_bill(db, db.get(Organization, referee.id), bill, NOW)
    db.commit()
    data = env.client.get("/billing/referral-status").json()
    assert data["referred_state"] == "applied" and data["free_bill_paise"] == BASIC_M


# --- codes and signup --------------------------------------------------------

def test_validate_code_reports_kind_for_a_live_code_only(env, db, monkeypatch):
    # The production limiter counts in Redis (20 per hour), which persists across test runs.
    from api.limiter import limiter
    monkeypatch.setattr(limiter, "enabled", False)
    referrer, code = _referrer(db)
    admin = PromoCode(code="CLEW-ABCDE", kind="admin", max_redemptions=1)
    db.add(admin)
    db.commit()
    get = lambda c: env.client.get("/auth/validate-code", params={"code": c}).json()  # noqa: E731
    assert get(code.code) == {"valid": True, "kind": "referral"}
    assert get(code.code.lower()) == {"valid": True, "kind": "referral"}
    assert get("CLEW-ABCDE") == {"valid": True, "kind": "admin"}
    assert get("REF-NOPE1") == {"valid": False, "kind": None}
    admin.redeemed_at = NOW
    db.commit()
    assert get("CLEW-ABCDE") == {"valid": False, "kind": None}
    referrer.deleted_at = NOW
    db.commit()
    assert get(code.code) == {"valid": False, "kind": None}


def _new_client(db, email: str) -> Client:
    c = Client(email=email, full_name="New", email_verified=True, password_hash="x")
    db.add(c)
    db.commit()
    return c


def test_a_referral_code_has_no_signup_cap(db):
    referrer, code = _referrer(db)
    for i in range(15):
        org = create_organization(db, f"Org {i}", _new_client(db, f"u{i}@example.test"), promo_code=code.code)
        db.commit()
        assert org.referred_by_promo_code_id == code.id
        assert org.tier == "starter" and org.trial_ends_at is None
    assert db.query(PromoCodeRedemption).filter_by(promo_code_id=code.id).count() == 15


def test_every_new_org_gets_its_own_referral_code(db):
    org = create_organization(db, "Solo", _new_client(db, "solo@example.test"))
    db.commit()
    own = referrals.own_referral_code(org, db)
    assert own is not None and own.code.startswith("REF-")
    assert own.owner_org_id == org.id


def test_one_person_can_register_many_orgs_on_their_own_code(db):
    """Accepted by design (Phase 12 decision): no extra block."""
    person = _new_client(db, "founder@example.test")
    first = create_organization(db, "First", person)
    db.commit()
    code = referrals.own_referral_code(first, db)
    second = create_organization(db, "Second", person, promo_code=code.code)
    db.commit()
    assert second.referred_by_promo_code_id == code.id


@pytest.mark.parametrize("how", ["purged", "deleted"])
def test_a_code_whose_owner_is_gone_refuses_new_signups(db, how):
    referrer, code = _referrer(db)
    if how == "purged":
        code.owner_org_id = None
    else:
        referrer.deleted_at = NOW
    db.commit()
    with pytest.raises(HTTPException) as err:
        create_organization(db, "Late", _new_client(db, "late@example.test"), promo_code=code.code)
    assert err.value.status_code == 400


def test_an_unknown_code_is_refused(db):
    with pytest.raises(HTTPException) as err:
        create_organization(db, "Nope", _new_client(db, "nope@example.test"), promo_code="REF-ZZZZZ")
    assert err.value.status_code == 400


def test_an_admin_code_still_grants_the_pilot_and_is_single_use(db):
    db.add(PromoCode(code="CLEW-PILOT", kind="admin", max_redemptions=1))
    db.commit()
    org = create_organization(db, "Pilot", _new_client(db, "pilot@example.test"), promo_code="clew-pilot")
    db.commit()
    assert org.tier == "growth" and org.billing_provider == "pilot" and org.trial_ends_at is not None
    with pytest.raises(HTTPException):
        create_organization(db, "Pilot 2", _new_client(db, "pilot2@example.test"), promo_code="CLEW-PILOT")


def test_deleting_the_owner_org_keeps_the_code_row_orphaned_in_the_model(db):
    """owner_org_id is SET NULL on delete, so an orphaned code is a real state."""
    from db.models import PromoCode as PC

    fk = next(iter(PC.__table__.c.owner_org_id.foreign_keys))
    assert fk.ondelete == "SET NULL"
