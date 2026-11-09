"""Phase 4: Razorpay Orders payment flow, end to end through the real routes
with a fake Razorpay client (see conftest.py)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from api.billing_rules import restore_amount_paise
from api.tests.billing_testkit import make_org
from api.tests.conftest import checkout_signature, make_bill
from api.tiers import plan_price
from db.models import Bill, BillingEvent, Organization, Payment

STARTER_M = plan_price("INR", "starter", "monthly")
GROWTH_M = plan_price("INR", "growth", "monthly")
STARTER_A = plan_price("INR", "starter", "annual")


def _buy(env, org, tier="starter", period="monthly", **extra):
    """create-order, pay on the fake gateway, verify. Returns (order, payment_id, verify response)."""
    resp = env.create_order(purpose="initial", tier=tier, period=period, accept_blocking_tos=True, **extra)
    assert resp.status_code == 200, resp.text
    order = resp.json()
    rz_id = env.rp.pay(order["order_id"])
    return order, rz_id, env.verify(order["order_id"], rz_id)


def _events(db, org, event=None):
    q = db.query(BillingEvent).filter(BillingEvent.org_id == org.id)
    if event:
        q = q.filter(BillingEvent.event == event)
    return q.all()


# --- create-order ----------------------------------------------------------

def test_create_order_amount_comes_from_the_server(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    resp = env.create_order(purpose="initial", tier="starter", period="monthly",
                            accept_blocking_tos=True, amount=1, amount_paise=1)
    assert resp.status_code == 200
    data = resp.json()
    assert data["amount"] == STARTER_M
    assert data["key_id"] == "rzp_test_unit"
    assert env.rp.orders[data["order_id"]]["amount"] == STARTER_M
    payment = db.query(Payment).one()
    assert payment.amount_paise == STARTER_M
    assert payment.status == "created"
    assert env.rp.orders[data["order_id"]]["receipt"] == payment.id
    # Nothing is applied by creating an order.
    db.refresh(org)
    assert org.tier == "free"
    assert org.blocking_tos_accepted_at is None


def test_tos_and_gstin_are_stamped_only_at_capture(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    gstin = "29ABCDE1234F1Z5"
    resp = env.create_order(purpose="initial", tier="starter", period="monthly",
                            accept_blocking_tos=True, gstin=gstin)
    assert resp.status_code == 200
    db.refresh(org)
    assert org.blocking_tos_accepted_at is None
    assert org.gstin is None
    order = resp.json()
    rz_id = env.rp.pay(order["order_id"])
    assert env.verify(order["order_id"], rz_id).status_code == 200
    db.refresh(org)
    assert org.blocking_tos_accepted_at is not None
    assert org.gstin == gstin


def test_blocking_agreement_required_for_blocking_tiers(env, db):
    env.act_as(make_org(db, tier="free", period=None))
    resp = env.create_order(purpose="initial", tier="starter", period="monthly")
    assert resp.status_code == 403
    assert db.query(Payment).count() == 0


def test_invalid_gstin_rejected_before_any_order(env, db):
    env.act_as(make_org(db, tier="free", period=None))
    resp = env.create_order(purpose="initial", tier="starter", period="monthly",
                            accept_blocking_tos=True, gstin="NOT-A-GSTIN")
    assert resp.status_code == 400
    assert env.rp.orders == {}


@pytest.mark.parametrize("body", [
    {"purpose": "nonsense", "tier": "starter", "period": "monthly"},
    {"purpose": "initial", "tier": "starter", "period": "weekly"},
    {"purpose": "initial", "tier": "enterprise", "period": "monthly"},
    {"purpose": "initial", "tier": "free", "period": "monthly"},
])
def test_create_order_rejects_unknown_plans(env, db, body):
    env.act_as(make_org(db, tier="free", period=None))
    assert env.create_order(accept_blocking_tos=True, **body).status_code == 400


def test_create_order_rejects_stripe_and_enterprise_orgs(env, db):
    org = env.act_as(make_org(db, tier="free", period=None, billing_provider="stripe"))
    assert env.create_order(purpose="initial", tier="starter", period="monthly",
                            accept_blocking_tos=True).status_code == 409
    org.billing_provider = None
    org.tier = "enterprise"
    db.commit()
    assert env.create_order(purpose="initial", tier="starter", period="monthly",
                            accept_blocking_tos=True).status_code == 409


def test_create_order_is_owner_only(env, db):
    env.act_as(make_org(db, tier="free", period=None), role="admin")
    assert env.create_order(purpose="initial", tier="starter", period="monthly",
                            accept_blocking_tos=True).status_code == 403


def test_initial_order_blocked_while_a_paid_plan_exists(env, db):
    env.act_as(make_org(db, tier="starter", period="monthly"))
    assert env.create_order(purpose="initial", tier="growth", period="monthly",
                            accept_blocking_tos=True).status_code == 409


# --- verify-payment --------------------------------------------------------

def test_verify_applies_the_plan_once(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order, rz_id, resp = _buy(env, org)
    assert resp.status_code == 200
    assert resp.json() == {"status": "captured", "payment_id": order["payment_id"], "applied": True}
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.tier, org.billing_period, org.billing_provider) == ("starter", "monthly", "razorpay")
    assert org.first_charged_at is not None
    assert org.next_billing_date is not None
    assert org.blocking_tos_accepted_at is not None
    assert org.payment_method_display == "Visa •••• 1007"
    payment = db.get(Payment, order["payment_id"])
    assert payment.status == "captured"
    assert payment.razorpay_payment_id == rz_id
    assert len(_events(db, org, "first_paid")) == 1


def test_verify_bad_signature_changes_nothing(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order = env.create_order(purpose="initial", tier="starter", period="monthly",
                             accept_blocking_tos=True).json()
    rz_id = env.rp.pay(order["order_id"])
    resp = env.verify(order["order_id"], rz_id, signature="0" * 64)
    assert resp.status_code == 400
    # A signature made with another secret is also rejected.
    resp = env.verify(order["order_id"], rz_id, signature=checkout_signature(order["order_id"], rz_id, "other"))
    assert resp.status_code == 400
    db.expire_all()
    assert db.get(Organization, org.id).tier == "free"
    assert db.get(Payment, order["payment_id"]).status == "created"


def test_verify_requires_all_fields(env, db):
    env.act_as(make_org(db, tier="free", period=None))
    resp = env.client.post("/billing/razorpay/verify-payment", json={"razorpay_order_id": "order_x"})
    assert resp.status_code == 400


def test_verify_rejects_an_amount_that_does_not_match(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order = env.create_order(purpose="initial", tier="starter", period="monthly",
                             accept_blocking_tos=True).json()
    rz_id = env.rp.pay(order["order_id"], amount=100)
    assert env.verify(order["order_id"], rz_id).status_code == 400
    db.expire_all()
    assert db.get(Organization, org.id).tier == "free"
    assert db.get(Payment, order["payment_id"]).status == "created"


def test_verify_requires_a_captured_payment(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order = env.create_order(purpose="initial", tier="starter", period="monthly",
                             accept_blocking_tos=True).json()
    rz_id = env.rp.pay(order["order_id"], status="authorized")
    assert env.verify(order["order_id"], rz_id).status_code == 409
    db.expire_all()
    assert db.get(Organization, org.id).tier == "free"


def test_verify_rejects_a_payment_for_a_different_order(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    a = env.create_order(purpose="initial", tier="starter", period="monthly", accept_blocking_tos=True).json()
    b = env.create_order(purpose="initial", tier="starter", period="monthly", accept_blocking_tos=True).json()
    rz_b = env.rp.pay(b["order_id"])
    # Signature is valid for (a, rz_b) but Razorpay says rz_b belongs to order b.
    assert env.verify(a["order_id"], rz_b).status_code == 400
    db.expire_all()
    assert db.get(Organization, org.id).tier == "free"


def test_verify_cannot_touch_another_orgs_order(env, db):
    owner = make_org(db, tier="free", period=None, name="A")
    other = make_org(db, tier="free", period=None, name="B")
    env.act_as(owner)
    order = env.create_order(purpose="initial", tier="starter", period="monthly",
                             accept_blocking_tos=True).json()
    rz_id = env.rp.pay(order["order_id"])
    env.act_as(other)
    assert env.verify(order["order_id"], rz_id).status_code == 404
    db.expire_all()
    assert db.get(Organization, other.id).tier == "free"
    assert db.get(Organization, owner.id).tier == "free"


# --- double delivery (verify plus webhook) ---------------------------------

def test_verify_then_webhook_credits_once(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order, rz_id, resp = _buy(env, org)
    assert resp.json()["applied"] is True
    assert env.webhook(env.captured_event(rz_id)).status_code == 200
    db.expire_all()
    assert len(_events(db, org, "first_paid")) == 1
    # And a second verify is a harmless no-op.
    again = env.verify(order["order_id"], rz_id)
    assert again.status_code == 200 and again.json()["applied"] is False


def test_webhook_then_verify_credits_once(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order = env.create_order(purpose="initial", tier="starter", period="monthly",
                             accept_blocking_tos=True).json()
    rz_id = env.rp.pay(order["order_id"])
    assert env.webhook(env.captured_event(rz_id)).status_code == 200
    db.expire_all()
    assert db.get(Organization, org.id).tier == "starter"
    resp = env.verify(order["order_id"], rz_id)
    assert resp.status_code == 200 and resp.json()["applied"] is False
    db.expire_all()
    assert len(_events(db, org, "first_paid")) == 1


def test_duplicate_webhook_event_id_is_skipped(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order = env.create_order(purpose="initial", tier="starter", period="monthly",
                             accept_blocking_tos=True).json()
    rz_id = env.rp.pay(order["order_id"])
    event = env.captured_event(rz_id)
    assert env.webhook(event, event_id="evt_same").status_code == 200
    assert env.webhook(event, event_id="evt_same").status_code == 200
    db.expire_all()
    assert len(_events(db, org, "first_paid")) == 1


# --- webhook ---------------------------------------------------------------

def test_webhook_rejects_a_bad_signature(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order = env.create_order(purpose="initial", tier="starter", period="monthly",
                             accept_blocking_tos=True).json()
    rz_id = env.rp.pay(order["order_id"])
    assert env.webhook(env.captured_event(rz_id), secret="wrong").status_code == 400
    db.expire_all()
    assert db.get(Organization, org.id).tier == "free"


def test_webhook_does_not_apply_a_mismatched_amount(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order = env.create_order(purpose="initial", tier="starter", period="monthly",
                             accept_blocking_tos=True).json()
    rz_id = env.rp.pay(order["order_id"], amount=100)
    assert env.webhook(env.captured_event(rz_id)).status_code == 200
    db.expire_all()
    assert db.get(Organization, org.id).tier == "free"
    assert db.get(Payment, order["payment_id"]).status == "created"


def test_webhook_ignores_unknown_orders_and_events(env, db):
    env.act_as(make_org(db, tier="free", period=None))
    stranger = {"event": "payment.captured", "payload": {"payment": {"entity": {"order_id": "order_nope", "amount": 1}}}}
    assert env.webhook(stranger).status_code == 200
    assert env.webhook({"event": "subscription.activated", "payload": {}}).status_code == 200


def test_failed_payment_changes_nothing_and_a_retry_still_applies(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order = env.create_order(purpose="initial", tier="starter", period="monthly",
                             accept_blocking_tos=True).json()
    failed = env.rp.pay(order["order_id"], status="failed")
    event = {"event": "payment.failed", "payload": {"payment": {"entity": env.rp.payments[failed]}}}
    assert env.webhook(event).status_code == 200
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.tier, org.billing_period, org.first_charged_at) == ("free", None, None)
    assert org.blocking_tos_accepted_at is None
    assert db.get(Payment, order["payment_id"]).status == "failed"
    assert _events(db, org) == []
    # A later successful attempt on the same order is applied.
    good = env.rp.pay(order["order_id"])
    assert env.verify(order["order_id"], good).status_code == 200
    db.expire_all()
    assert db.get(Organization, org.id).tier == "starter"


def test_refund_processed_marks_the_payment_refunded_once(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order, rz_id, _ = _buy(env, org)
    event = {"event": "refund.processed",
             "payload": {"refund": {"entity": {"payment_id": rz_id, "amount": STARTER_M}}}}
    assert env.webhook(event).status_code == 200
    db.expire_all()
    payment = db.get(Payment, order["payment_id"])
    assert payment.status == "refunded"
    first = payment.refunded_at
    assert first is not None
    assert env.webhook(event).status_code == 200
    db.expire_all()
    assert db.get(Payment, order["payment_id"]).refunded_at == first


def test_partial_refund_event_is_not_treated_as_a_full_refund(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order, rz_id, _ = _buy(env, org)
    event = {"event": "refund.processed", "payload": {"refund": {"entity": {"payment_id": rz_id, "amount": 100}}}}
    assert env.webhook(event).status_code == 200
    db.expire_all()
    assert db.get(Payment, order["payment_id"]).status == "captured"


# --- open-bill gating ------------------------------------------------------

def test_initial_blocked_by_open_bills_with_a_listing(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    bill = make_bill(db, org)
    resp = env.create_order(purpose="initial", tier="starter", period="monthly", accept_blocking_tos=True)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert [b["id"] for b in detail["open_bills"]] == [bill.id]
    assert env.rp.orders == {}


def test_upgrade_with_a_stale_open_bill_is_blocked(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    make_bill(db, org, start=datetime.now(timezone.utc).date() - timedelta(days=90))
    resp = env.create_order(purpose="upgrade", tier="growth", period="monthly", accept_blocking_tos=True)
    assert resp.status_code == 409
    assert resp.json()["detail"]["open_bills"]


def test_monthly_to_annual_with_an_open_bill_is_blocked(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    make_bill(db, org)
    resp = env.create_order(purpose="upgrade", tier="starter", period="annual", accept_blocking_tos=True,
                            accept_annual_nonrefundable=True)
    assert resp.status_code == 409


def test_tier_upgrade_with_the_current_bill_open_is_blocked_until_it_is_paid(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    bill = make_bill(db, org)
    resp = env.create_order(purpose="upgrade", tier="growth", period="monthly", accept_blocking_tos=True)
    assert resp.status_code == 409
    assert [b["id"] for b in resp.json()["detail"]["open_bills"]] == [bill.id]
    assert env.rp.orders == {}
    assert db.query(Payment).count() == 0
    db.expire_all()
    assert db.get(Organization, org.id).tier == "starter"
    assert db.get(Bill, bill.id).amount_paise == STARTER_M
    quote = env.client.post(
        "/billing/quote", json={"purpose": "upgrade", "tier": "growth", "period": "monthly"}
    )
    assert quote.status_code == 409


def test_upgrade_after_paying_the_open_bill_charges_the_difference(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    bill = make_bill(db, org)
    pay = env.create_order(purpose="bill", bill_id=bill.id).json()
    assert env.verify(pay["order_id"], env.rp.pay(pay["order_id"])).status_code == 200
    resp = env.create_order(purpose="upgrade", tier="growth", period="monthly", accept_blocking_tos=True)
    assert resp.status_code == 200
    assert resp.json()["amount"] == GROWTH_M - STARTER_M


def test_tier_upgrade_keeps_the_next_bill_date(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly", next_bill=date(2031, 3, 1)))
    before = db.get(Organization, org.id).next_billing_date
    order = env.create_order(purpose="upgrade", tier="growth", period="monthly", accept_blocking_tos=True).json()
    assert env.verify(order["order_id"], env.rp.pay(order["order_id"])).status_code == 200
    db.expire_all()
    assert db.get(Organization, org.id).next_billing_date == before


def test_upgrade_with_nothing_open_charges_the_difference(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    resp = env.create_order(purpose="upgrade", tier="growth", period="monthly", accept_blocking_tos=True)
    assert resp.status_code == 200
    order = resp.json()
    assert order["amount"] == GROWTH_M - STARTER_M
    rz_id = env.rp.pay(order["order_id"])
    assert env.verify(order["order_id"], rz_id).status_code == 200
    db.expire_all()
    org = db.get(Organization, org.id)
    assert org.tier == "growth"
    assert org.billing_period == "monthly"
    assert len(_events(db, org, "upgraded")) == 1


def test_monthly_to_annual_charges_the_full_annual_price(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    order = env.create_order(purpose="upgrade", tier="starter", period="annual", accept_blocking_tos=True,
                             accept_annual_nonrefundable=True).json()
    assert order["amount"] == STARTER_A
    rz_id = env.rp.pay(order["order_id"])
    assert env.verify(order["order_id"], rz_id).status_code == 200
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.tier, org.billing_period) == ("starter", "annual")


def test_annual_to_a_higher_annual_tier_charges_the_full_price_and_starts_a_new_year(env, db):
    org = env.act_as(make_org(db, tier="starter", period="annual", next_bill=date(2031, 3, 1)))
    before = db.get(Organization, org.id).next_billing_date
    order = env.create_order(purpose="upgrade", tier="growth", period="annual", accept_blocking_tos=True,
                             accept_annual_nonrefundable=True).json()
    assert order["amount"] == plan_price("INR", "growth", "annual")
    assert env.verify(order["order_id"], env.rp.pay(order["order_id"])).status_code == 200
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.tier, org.billing_period) == ("growth", "annual")
    assert org.next_billing_date != before


def test_upgrade_rejects_downgrades_and_double_changes(env, db):
    env.act_as(make_org(db, tier="growth", period="monthly"))
    assert env.create_order(purpose="upgrade", tier="starter", period="monthly",
                            accept_blocking_tos=True).status_code == 400
    assert env.create_order(purpose="upgrade", tier="pro", period="annual",
                            accept_blocking_tos=True, accept_annual_nonrefundable=True).status_code == 400


def test_an_upgrade_payment_for_a_stale_plan_leaves_the_org_alone(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    order = env.create_order(purpose="upgrade", tier="growth", period="monthly", accept_blocking_tos=True).json()
    org.tier = "pro"  # changed between order and capture
    db.commit()
    rz_id = env.rp.pay(order["order_id"])
    assert env.verify(order["order_id"], rz_id).status_code == 200
    db.expire_all()
    assert db.get(Organization, org.id).tier == "pro"
    assert db.get(Payment, order["payment_id"]).status == "captured"


def test_pay_a_bill_marks_it_paid(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    bill = make_bill(db, org)
    resp = env.create_order(purpose="bill", bill_id=bill.id)
    assert resp.status_code == 200
    order = resp.json()
    assert order["amount"] == bill.amount_paise
    rz_id = env.rp.pay(order["order_id"])
    assert env.verify(order["order_id"], rz_id).status_code == 200
    db.expire_all()
    paid = db.get(Bill, bill.id)
    assert paid.status == "paid" and paid.payment_id == order["payment_id"]
    assert paid.paid_at is not None


def test_pay_a_bill_needs_a_real_open_bill_of_this_org(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    other = make_org(db, tier="starter", period="monthly", name="Other")
    theirs = make_bill(db, other)
    assert env.create_order(purpose="bill").status_code == 400
    assert env.create_order(purpose="bill", bill_id=theirs.id).status_code == 404
    mine = make_bill(db, org, status="paid", start=datetime.now(timezone.utc).date() - timedelta(days=60))
    assert env.create_order(purpose="bill", bill_id=mine.id).status_code == 404


def test_bill_payment_blocked_on_a_cancelled_plan(env, db):
    org = env.act_as(make_org(db, tier="free", period=None, nonpayment_downgraded_at=datetime.now(timezone.utc)))
    bill = make_bill(db, org)
    assert env.create_order(purpose="bill", bill_id=bill.id).status_code == 409


def test_restore_pays_open_bills_plus_a_new_period(env, db):
    org = env.act_as(make_org(
        db, tier="free", period=None,
        nonpayment_downgraded_at=datetime.now(timezone.utc) - timedelta(days=3),
        retention_grace_tier="growth",
        retention_grace_until=datetime.now(timezone.utc) + timedelta(days=27),
    ))
    bill = make_bill(db, org, tier="growth", amount=GROWTH_M)
    order = env.create_order(purpose="restore", tier="starter", period="monthly", accept_blocking_tos=True).json()
    assert order["amount"] == restore_amount_paise([bill], "starter", "monthly", currency="INR") == GROWTH_M + STARTER_M
    rz_id = env.rp.pay(order["order_id"])
    assert env.verify(order["order_id"], rz_id).status_code == 200
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.tier, org.billing_period) == ("starter", "monthly")
    assert org.nonpayment_downgraded_at is None
    assert org.retention_grace_until is None and org.retention_grace_tier is None
    assert db.get(Bill, bill.id).status == "paid"
    assert len(_events(db, org, "restored")) == 1


def test_restore_only_after_a_nonpayment_downgrade(env, db):
    env.act_as(make_org(db, tier="free", period=None))
    assert env.create_order(purpose="restore", tier="starter", period="monthly",
                            accept_blocking_tos=True).status_code == 409


# --- refund ----------------------------------------------------------------

def test_refund_within_the_window_refunds_in_full_and_downgrades(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order, rz_id, _ = _buy(env, org)
    elig = env.client.post("/billing/refund-eligibility").json()
    assert elig["eligible"] is True and elig["reason"] == "remorse_window"

    resp = env.client.post("/billing/refund")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "refunded", "refunded_paise": STARTER_M, "failed_payments": 0}
    assert env.rp.refund_calls[0][0] == rz_id
    assert env.rp.refund_calls[0][1]["amount"] == STARTER_M
    db.expire_all()
    org = db.get(Organization, org.id)
    assert org.tier == "free" and org.billing_period is None
    assert org.nonpayment_downgraded_at is None
    payment = db.get(Payment, order["payment_id"])
    assert payment.status == "refunded" and payment.refunded_at is not None
    [event] = _events(db, org, "refunded")
    assert event.amount_paise == STARTER_M

    # The refund.processed webhook that follows finds it already refunded.
    hook = {"event": "refund.processed", "payload": {"refund": {"entity": {"payment_id": rz_id, "amount": STARTER_M}}}}
    assert env.webhook(hook).status_code == 200
    # And a second refund is refused.
    assert env.client.post("/billing/refund").status_code == 409
    assert len(env.rp.refund_calls) == 1
    assert env.client.post("/billing/refund-eligibility").json()["reason"] == "already_refunded"


def test_refund_after_the_window_is_refused(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order, _, _ = _buy(env, org)
    payment = db.get(Payment, order["payment_id"])
    payment.captured_at = datetime.now(timezone.utc) - timedelta(hours=72, seconds=1)
    db.commit()
    assert env.client.post("/billing/refund").status_code == 409
    assert env.rp.refund_calls == []
    db.expire_all()
    assert db.get(Organization, org.id).tier == "starter"


def test_refund_just_inside_the_window_is_allowed(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order, _, _ = _buy(env, org)
    payment = db.get(Payment, order["payment_id"])
    payment.captured_at = datetime.now(timezone.utc) - timedelta(hours=71, minutes=59)
    db.commit()
    assert env.client.post("/billing/refund").status_code == 200


def test_refund_failure_changes_nothing(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order, _, _ = _buy(env, org)
    env.rp.fail_refunds = True
    assert env.client.post("/billing/refund").status_code == 502
    db.expire_all()
    assert db.get(Organization, org.id).tier == "starter"
    assert db.get(Payment, order["payment_id"]).status == "captured"


def test_refund_without_any_payment_is_refused(env, db):
    env.act_as(make_org(db, tier="free", period=None))
    resp = env.client.post("/billing/refund")
    assert resp.status_code == 409
    assert env.client.post("/billing/refund-eligibility").json() == {
        "eligible": False, "reason": "no_payment", "window_expires_at": None,
    }


# --- cancel, schedule-downgrade, details -----------------------------------

def test_cancel_sets_cancel_at_period_end(env, db):
    org = env.act_as(make_org(db, tier="growth", period="monthly"))
    org.pending_tier, org.pending_period = "starter", "monthly"
    db.commit()
    resp = env.client.post("/billing/cancel")
    assert resp.status_code == 200
    db.expire_all()
    org = db.get(Organization, org.id)
    assert org.cancel_at_period_end is True
    assert org.pending_tier is None and org.pending_period is None
    assert org.tier == "growth"  # access continues until the period ends


def test_cancel_needs_a_paid_plan_and_owner_role(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    assert env.client.post("/billing/cancel").status_code == 400
    org.tier, org.billing_period = "starter", "monthly"
    db.commit()
    env.act_as(org, role="viewer")
    assert env.client.post("/billing/cancel").status_code == 403


def test_schedule_downgrade_sets_pending_fields(env, db):
    org = env.act_as(make_org(db, tier="growth", period="monthly", cancel_at_period_end=True))
    resp = env.client.post("/billing/schedule-downgrade", json={"tier": "starter", "period": "monthly"})
    assert resp.status_code == 200
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.pending_tier, org.pending_period) == ("starter", "monthly")
    assert org.cancel_at_period_end is False
    assert org.tier == "growth"


def test_schedule_downgrade_annual_to_monthly(env, db):
    org = env.act_as(make_org(db, tier="starter", period="annual"))
    assert env.client.post("/billing/schedule-downgrade",
                           json={"tier": "starter", "period": "monthly"}).status_code == 200


@pytest.mark.parametrize("body", [
    {"tier": "pro", "period": "monthly"},       # upgrade
    {"tier": "growth", "period": "monthly"},    # same plan
    {"tier": "starter", "period": "annual"},    # tier and period both change
    {"tier": "enterprise", "period": "monthly"},
])
def test_schedule_downgrade_rejects_anything_else(env, db, body):
    env.act_as(make_org(db, tier="growth", period="monthly"))
    assert env.client.post("/billing/schedule-downgrade", json=body).status_code == 400


def test_stripe_orgs_cannot_cancel_through_razorpay_routes(env, db):
    env.act_as(make_org(db, tier="starter", period="monthly", billing_provider="stripe"))
    assert env.client.post("/billing/cancel").status_code == 409


def test_update_billing_details(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    resp = env.client.put("/billing/details", json={"legal_name": " Acme Pvt Ltd ", "address": "1 Road, Pune"})
    assert resp.status_code == 200
    assert resp.json() == {"legal_name": "Acme Pvt Ltd", "address": "1 Road, Pune", "gstin": None, "billing_country": "IN"}
    # Only the fields sent change.
    resp = env.client.put("/billing/details", json={"gstin": "29abcde1234f1z5"})
    assert resp.json() == {"legal_name": "Acme Pvt Ltd", "address": "1 Road, Pune", "gstin": "29ABCDE1234F1Z5", "billing_country": "IN"}
    assert env.client.put("/billing/details", json={"gstin": "bad"}).status_code == 400
    resp = env.client.put("/billing/details", json={"address": ""})
    assert resp.json()["address"] is None
    env.act_as(org, role="admin")
    assert env.client.put("/billing/details", json={"legal_name": "x"}).status_code == 403


# --- status and banner -----------------------------------------------------

def test_status_is_owner_only_and_banner_is_open_to_viewers(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"), role="viewer")
    assert env.client.get("/billing/status").status_code == 403
    resp = env.client.get("/billing/banner")
    assert resp.status_code == 200
    assert resp.json()["tier"] == "starter"


def test_status_lists_bills_payments_and_details(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    _buy(env, org)
    bill = make_bill(db, org)
    data = env.client.get("/billing/status").json()
    assert data["tier"] == "starter" and data["billing_period"] == "monthly"
    assert [b["id"] for b in data["open_bills"]] == [bill.id]
    assert [p["status"] for p in data["payments"]] == ["captured"]
    assert data["refund"]["eligible"] is True
    assert "razorpay_subscription_id" not in data
    assert set(data["billing_details"]) == {"legal_name", "address", "gstin", "billing_country"}


# --- accept-blocking-tos gate ----------------------------------------------

def test_accept_blocking_tos_is_refused_for_a_free_org(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    assert env.client.post("/clients/me/accept-blocking-tos").status_code == 403
    db.expire_all()
    assert db.get(Organization, org.id).blocking_tos_accepted_at is None


def test_accept_blocking_tos_still_works_for_a_growth_pilot(env, db):
    org = env.act_as(make_org(db, tier="growth", period=None, billing_provider=None, trial_source="pilot"))
    resp = env.client.post("/clients/me/accept-blocking-tos")
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(Organization, org.id).blocking_tos_accepted_at is not None
