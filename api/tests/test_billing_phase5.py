"""Phase 5: USD and INR billing, the currency lock, quote, receipts, notification
settings, undo-pending, billing contacts and the billing emails.

Uses the same env fixture as test_billing_routes.py: the real FastAPI app, an
in-memory SQLite database and a fake Razorpay, so nothing touches a network.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from api.billing_emails import (
    format_date,
    format_money,
    render_billing_email,
    resolve_billing_recipients,
    send_billing_emails,
)
from api.billing_notify import NOTIFY_KINDS, notify
from api.tests.billing_testkit import make_org
from api.tests.conftest import make_bill
from api.tiers import plan_price
from db.models import Bill, Client, Organization, OrganizationMember, Payment

EM_DASH = "\u2014"


def _fresh_org(db, **extra) -> Organization:
    """A free org that has not chosen a billing country yet."""
    return make_org(db, tier="free", period=None, billing_country=None, billing_currency="USD", **extra)


def _order(env, *, country=None, tier="starter", period="monthly", **extra):
    body = {"purpose": "initial", "tier": tier, "period": period, "accept_blocking_tos": True}
    if country is not None:
        body["billing_country"] = country
    body.update(extra)
    return env.create_order(**body)


# --- currency choice and lock ----------------------------------------------

def test_an_org_with_no_country_must_send_one(env, db):
    env.act_as(_fresh_org(db))
    assert _order(env).status_code == 400
    assert env.rp.orders == {}


def test_india_is_charged_in_inr_and_locks_the_org(env, db):
    org = env.act_as(_fresh_org(db))
    resp = _order(env, country="in")
    assert resp.status_code == 200
    assert resp.json()["currency"] == "INR"
    assert resp.json()["amount"] == plan_price("INR", "starter", "monthly")
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.billing_currency, org.billing_country) == ("INR", "IN")
    assert db.query(Payment).one().currency == "INR"


def test_any_other_country_is_charged_in_usd(env, db):
    org = env.act_as(_fresh_org(db))
    resp = _order(env, country="US")
    assert resp.status_code == 200
    data = resp.json()
    assert data["currency"] == "USD"
    assert data["amount"] == 4900
    assert env.rp.orders[data["order_id"]]["currency"] == "USD"
    db.expire_all()
    assert db.get(Organization, org.id).billing_country == "US"
    assert db.query(Payment).one().currency == "USD"


def test_the_amount_in_usd_follows_the_published_cents(env, db):
    env.act_as(_fresh_org(db))
    for tier, period, cents in [("growth", "monthly", 12900), ("pro", "monthly", 24900), ("pro", "annual", 149400)]:
        extra = {"accept_annual_nonrefundable": True} if period == "annual" else {}
        resp = _order(env, country="GB", tier=tier, period=period, **extra)
        assert resp.status_code == 200, resp.text
        assert resp.json()["amount"] == cents


def test_a_locked_org_cannot_switch_country_or_currency(env, db):
    org = env.act_as(make_org(db, tier="free", period=None, billing_country="US", billing_currency="USD"))
    resp = _order(env, country="IN")
    assert resp.status_code == 409
    assert env.rp.orders == {}
    # The same country is fine, and so is leaving it out.
    assert _order(env, country="US").status_code == 200
    assert _order(env).status_code == 200
    db.expire_all()
    assert db.get(Organization, org.id).billing_currency == "USD"


def test_a_locked_org_is_charged_in_its_own_currency_whatever_the_client_says(env, db):
    env.act_as(make_org(db, tier="free", period=None, billing_country="IN", billing_currency="INR"))
    resp = _order(env, currency="USD", amount=1)
    assert resp.status_code == 200
    assert resp.json()["currency"] == "INR"
    assert resp.json()["amount"] == plan_price("INR", "starter", "monthly")


def test_the_country_must_be_two_letters(env, db):
    env.act_as(_fresh_org(db))
    assert _order(env, country="USA").status_code in (400, 422)
    assert _order(env, country="1!").status_code == 400


def test_a_failed_razorpay_order_does_not_lock_the_currency(env, db, monkeypatch):
    org = env.act_as(_fresh_org(db))

    def boom(_data):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(env.rp.order, "create", boom)
    assert _order(env, country="US").status_code == 502
    db.expire_all()
    assert db.get(Organization, org.id).billing_country is None


def test_mixed_currency_open_bills_are_refused(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    make_bill(db, org, currency="USD", amount=4900)
    resp = env.create_order(purpose="upgrade", tier="growth", period="monthly", accept_blocking_tos=True)
    assert resp.status_code == 409


def test_paying_an_open_bill_uses_the_bill_currency(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly", billing_country="US", billing_currency="USD"))
    bill = make_bill(db, org, currency="USD", amount=4900)
    resp = env.create_order(purpose="bill", bill_id=bill.id)
    assert resp.status_code == 200
    assert resp.json()["currency"] == "USD"
    assert resp.json()["amount"] == 4900


# --- annual acknowledgement --------------------------------------------------

def test_annual_needs_the_non_refundable_acknowledgement(env, db):
    env.act_as(make_org(db, tier="free", period=None))
    resp = _order(env, period="annual")
    assert resp.status_code == 403
    assert env.rp.orders == {}


def test_annual_acknowledgement_is_recorded_on_the_payment(env, db):
    env.act_as(make_org(db, tier="free", period=None))
    resp = _order(env, period="annual", accept_annual_nonrefundable=True)
    assert resp.status_code == 200
    assert db.query(Payment).one().line_items["annual_nonrefundable_accepted"] is True


def test_monthly_orders_do_not_need_the_acknowledgement(env, db):
    env.act_as(make_org(db, tier="free", period=None))
    assert _order(env).status_code == 200


# --- verify and webhook: amount and currency are both checked ----------------

def _usd_order(env, db):
    org = env.act_as(_fresh_org(db))
    order = _order(env, country="US").json()
    return org, order


def test_verify_accepts_a_usd_payment_and_applies_it(env, db):
    org, order = _usd_order(env, db)
    rz_id = env.rp.pay(order["order_id"])
    assert env.verify(order["order_id"], rz_id).status_code == 200
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.tier, org.billing_currency) == ("starter", "USD")


def test_verify_rejects_a_payment_in_the_wrong_currency(env, db):
    org, order = _usd_order(env, db)
    rz_id = env.rp.pay(order["order_id"], currency="INR")
    assert env.verify(order["order_id"], rz_id).status_code == 400
    db.expire_all()
    assert db.get(Organization, org.id).tier == "free"
    assert db.query(Payment).one().status == "created"


def test_webhook_ignores_a_payment_in_the_wrong_currency(env, db):
    org, order = _usd_order(env, db)
    rz_id = env.rp.pay(order["order_id"], currency="INR")
    assert env.webhook(env.captured_event(rz_id)).status_code == 200
    db.expire_all()
    assert db.get(Organization, org.id).tier == "free"
    assert db.query(Payment).one().status == "created"


def test_webhook_applies_a_usd_payment(env, db):
    org, order = _usd_order(env, db)
    rz_id = env.rp.pay(order["order_id"])
    assert env.webhook(env.captured_event(rz_id)).status_code == 200
    db.expire_all()
    assert db.get(Organization, org.id).tier == "starter"


def test_an_international_card_on_an_inr_order_is_logged_not_blocked(env, db, caplog):
    org = env.act_as(make_org(db, tier="free", period=None))
    order = _order(env).json()
    rz_id = env.rp.pay(order["order_id"])
    env.rp.payments[rz_id]["international"] = True
    with caplog.at_level("ERROR"):
        assert env.verify(order["order_id"], rz_id).status_code == 200
    assert any("international card" in r.getMessage() for r in caplog.records)
    db.expire_all()
    assert db.get(Organization, org.id).tier == "starter"


# --- payment_received is queued once, after the commit -----------------------

def test_a_captured_payment_queues_one_payment_received_email(env, db, notifications):
    org = env.act_as(make_org(db, tier="free", period=None))
    order = _order(env).json()
    rz_id = env.rp.pay(order["order_id"])
    assert env.verify(order["order_id"], rz_id).status_code == 200
    payment = db.query(Payment).one()
    assert notifications == [("payment_received", org.id, None, payment.id)]
    # The webhook for the same payment finds it already applied: no second email.
    assert env.webhook(env.captured_event(rz_id)).status_code == 200
    assert len(notifications) == 1


def test_the_webhook_alone_queues_payment_received(env, db, notifications):
    org = env.act_as(make_org(db, tier="free", period=None))
    order = _order(env).json()
    rz_id = env.rp.pay(order["order_id"])
    assert env.webhook(env.captured_event(rz_id)).status_code == 200
    assert [n[0] for n in notifications] == ["payment_received"]
    # A redelivery of the same event id is skipped, and verify finds it applied.
    assert env.verify(order["order_id"], rz_id).status_code == 200
    assert len(notifications) == 1


def test_a_failed_verification_queues_nothing(env, db, notifications):
    env.act_as(make_org(db, tier="free", period=None))
    order = _order(env).json()
    rz_id = env.rp.pay(order["order_id"], status="failed")
    assert env.verify(order["order_id"], rz_id).status_code == 409
    assert notifications == []


# --- quote ---------------------------------------------------------------------

def test_quote_matches_create_order_and_creates_nothing(env, db):
    env.act_as(_fresh_org(db))
    quote = env.client.post("/billing/quote", json={
        "purpose": "initial", "tier": "growth", "period": "monthly", "billing_country": "US",
    })
    assert quote.status_code == 200
    data = quote.json()
    assert (data["amount"], data["currency"], data["billing_country"]) == (12900, "USD", "US")
    assert env.rp.orders == {}
    assert db.query(Payment).count() == 0
    db.expire_all()
    assert db.query(Organization).one().billing_country is None
    order = _order(env, country="US", tier="growth").json()
    assert order["amount"] == data["amount"]


def test_quote_for_an_upgrade_with_the_bill_open_is_refused(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    make_bill(db, org)
    resp = env.client.post("/billing/quote", json={"purpose": "upgrade", "tier": "growth", "period": "monthly"})
    assert resp.status_code == 409


def test_quote_for_an_upgrade_with_nothing_open_is_the_difference(env, db):
    env.act_as(make_org(db, tier="starter", period="monthly"))
    data = env.client.post("/billing/quote", json={"purpose": "upgrade", "tier": "pro", "period": "monthly"}).json()
    assert data["amount"] == plan_price("INR", "pro", "monthly") - plan_price("INR", "starter", "monthly")
    assert data["currency"] == "INR"


def test_quote_is_owner_only_and_rejects_bad_input(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"), role="admin")
    assert env.client.post("/billing/quote", json={"purpose": "upgrade", "tier": "pro", "period": "monthly"}).status_code == 403
    env.act_as(org, role="owner")
    assert env.client.post("/billing/quote", json={"purpose": "upgrade", "tier": "pro", "period": "weekly"}).status_code == 400
    assert env.client.post("/billing/quote", json={"purpose": "nope", "tier": "pro", "period": "monthly"}).status_code == 400


# --- details: billing country ----------------------------------------------------

def test_details_can_set_the_country_once(env, db):
    org = env.act_as(_fresh_org(db))
    resp = env.client.put("/billing/details", json={"billing_country": "de"})
    assert resp.status_code == 200
    assert resp.json()["billing_country"] == "DE"
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.billing_country, org.billing_currency) == ("DE", "USD")
    assert env.client.put("/billing/details", json={"billing_country": "IN"}).status_code == 409
    assert env.client.put("/billing/details", json={"billing_country": "DE"}).status_code == 200


# --- status, banner, receipts ----------------------------------------------------

def test_status_and_banner_carry_the_currency(env, db):
    env.act_as(make_org(db, tier="free", period=None, billing_country="US", billing_currency="USD"))
    status = env.client.get("/billing/status").json()
    assert (status["billing_currency"], status["billing_country"]) == ("USD", "US")
    banner = env.client.get("/billing/banner").json()
    assert banner["billing_currency"] == "USD"
    assert banner["role"] == "owner"
    assert banner["today_ist"]


def test_status_next_bill_follows_the_plan_that_will_be_billed(env, db):
    org = env.act_as(make_org(db, tier="growth", period="monthly", billing_country="US", billing_currency="USD"))
    status = env.client.get("/billing/status").json()
    assert (status["next_bill_amount_paise"], status["next_bill_plan"]) == (12900, "Growth monthly")

    org.pending_tier, org.pending_period = "starter", "monthly"
    db.commit()
    status = env.client.get("/billing/status").json()
    assert (status["next_bill_amount_paise"], status["next_bill_plan"]) == (4900, "Basic monthly")

    org.pending_tier = org.pending_period = None
    org.cancel_at_period_end = True
    db.commit()
    status = env.client.get("/billing/status").json()
    assert (status["next_bill_amount_paise"], status["next_bill_plan"]) == (None, None)


def test_status_next_bill_is_none_without_a_paid_plan(env, db):
    env.act_as(make_org(db, tier="free", period=None))
    status = env.client.get("/billing/status").json()
    assert status["next_bill_amount_paise"] is None and status["next_bill_plan"] is None


def test_bill_summaries_carry_their_currency(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly", billing_country="US", billing_currency="USD"))
    make_bill(db, org, currency="USD", amount=4900)
    bills = env.client.get("/billing/status").json()["open_bills"]
    assert [(b["currency"], b["amount_paise"]) for b in bills] == [("USD", 4900)]


def test_payment_rows_carry_their_currency(env, db):
    org, order = _usd_order(env, db)
    env.verify(order["order_id"], env.rp.pay(order["order_id"]))
    rows = env.client.get("/billing/status").json()["payments"]
    assert [(r["currency"], r["amount_paise"]) for r in rows] == [("USD", 4900)]


def test_receipt_shows_the_snapshot_not_the_current_details(env, db):
    org = env.act_as(make_org(db, tier="free", period=None, billing_legal_name="Acme Pvt Ltd", billing_address="1 Road"))
    order = _order(env).json()
    env.verify(order["order_id"], env.rp.pay(order["order_id"]))
    payment = db.query(Payment).one()
    env.client.put("/billing/details", json={"legal_name": "Renamed Ltd", "address": "2 Street"})
    resp = env.client.get(f"/billing/payments/{payment.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["customer_name"] == "Acme Pvt Ltd"
    assert data["customer_address"] == "1 Road"
    assert data["currency"] == "INR"
    assert data["lines"] == [{"description": "Basic monthly", "amount_paise": plan_price("INR", "starter", "monthly")}]


def test_restore_receipt_splits_bills_and_the_new_period(env, db):
    org = env.act_as(make_org(db, tier="free", period=None, nonpayment_downgraded_at=datetime.now(timezone.utc)))
    bill = make_bill(db, org)
    resp = env.create_order(purpose="restore", tier="starter", period="monthly", accept_blocking_tos=True)
    assert resp.status_code == 200, resp.text
    order = resp.json()
    env.verify(order["order_id"], env.rp.pay(order["order_id"]))
    payment = db.query(Payment).one()
    lines = env.client.get(f"/billing/payments/{payment.id}").json()["lines"]
    assert [l["amount_paise"] for l in lines] == [bill.amount_paise, plan_price("INR", "starter", "monthly")]
    assert lines[0]["description"] == "Open bills (1)"


def test_receipts_are_owner_only_and_never_cross_orgs(env, db):
    org = env.act_as(make_org(db, tier="free", period=None))
    order = _order(env).json()
    env.verify(order["order_id"], env.rp.pay(order["order_id"]))
    payment = db.query(Payment).one()
    env.act_as(org, role="admin")
    assert env.client.get(f"/billing/payments/{payment.id}").status_code == 403
    other = env.act_as(make_org(db, name="Other", tier="free", period=None))
    assert other.id != org.id
    assert env.client.get(f"/billing/payments/{payment.id}").status_code == 404


def test_an_unpaid_order_has_no_receipt(env, db):
    env.act_as(make_org(db, tier="free", period=None))
    _order(env)
    payment = db.query(Payment).one()
    assert payment.status == "created"
    assert env.client.get(f"/billing/payments/{payment.id}").status_code == 404


# --- undo pending ------------------------------------------------------------------

def test_undo_pending_clears_a_scheduled_cancel_and_downgrade(env, db):
    org = env.act_as(make_org(db, tier="growth", period="monthly", cancel_at_period_end=True))
    resp = env.client.post("/billing/undo-pending")
    assert resp.status_code == 200 and resp.json()["status"] == "pending_cleared"
    db.expire_all()
    assert db.get(Organization, org.id).cancel_at_period_end is False

    org.pending_tier, org.pending_period = "starter", "monthly"
    db.commit()
    assert env.client.post("/billing/undo-pending").json()["status"] == "pending_cleared"
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.pending_tier, org.pending_period) == (None, None)


def test_undo_pending_with_nothing_scheduled_is_harmless(env, db):
    env.act_as(make_org(db, tier="growth", period="monthly"))
    resp = env.client.post("/billing/undo-pending")
    assert resp.status_code == 200 and resp.json()["status"] == "nothing_pending"


def test_undo_pending_is_owner_only(env, db):
    env.act_as(make_org(db, tier="growth", period="monthly", cancel_at_period_end=True), role="admin")
    assert env.client.post("/billing/undo-pending").status_code == 403


# --- notification settings ----------------------------------------------------------

def test_notification_settings_default_and_update(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    assert env.client.get("/billing/notifications").json() == {"mode": "owner", "reminders_enabled": True}
    resp = env.client.put("/billing/notifications", json={"mode": "all", "reminders_enabled": False})
    assert resp.status_code == 200
    assert resp.json() == {"mode": "all", "reminders_enabled": False}
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.billing_emails_mode, org.billing_reminders_enabled) == ("all", False)


def test_notification_settings_reject_unknown_modes_and_non_owners(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    assert env.client.put("/billing/notifications", json={"mode": "everyone", "reminders_enabled": True}).status_code == 422
    env.act_as(org, role="admin")
    assert env.client.get("/billing/notifications").status_code == 403
    assert env.client.put("/billing/notifications", json={"mode": "all", "reminders_enabled": True}).status_code == 403


# --- members and billing contacts -----------------------------------------------------

def _member(db, org, email, role="viewer", contact=False, name="A Person", deleted=False) -> OrganizationMember:
    client = Client(
        email=email,
        full_name=name,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(client)
    db.commit()
    member = OrganizationMember(client_id=client.id, org_id=org.id, role=role, is_billing_contact=contact)
    db.add(member)
    db.commit()
    return member


def test_member_list_has_names_and_the_billing_contact_flag(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    _member(db, org, "owner@example.com", role="owner", name="Olive Owner")
    _member(db, org, "view@example.com", contact=True, name="Vi Viewer")
    members = {m["email"]: m for m in env.client.get("/org/members").json()}
    assert members["owner@example.com"]["full_name"] == "Olive Owner"
    assert members["owner@example.com"]["is_billing_contact"] is False
    assert members["view@example.com"]["is_billing_contact"] is True


def test_the_owner_can_mark_and_unmark_a_billing_contact(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    member = _member(db, org, "view@example.com")
    url = f"/org/members/{member.id}/billing-contact"
    assert env.client.patch(url, json={"is_billing_contact": True}).json() == {"is_billing_contact": True}
    db.expire_all()
    assert db.get(OrganizationMember, member.id).is_billing_contact is True
    assert env.client.patch(url, json={"is_billing_contact": False}).json() == {"is_billing_contact": False}


def test_billing_contact_is_owner_only_and_org_scoped(env, db):
    org = env.act_as(make_org(db, tier="starter", period="monthly"))
    member = _member(db, org, "view@example.com")
    other_org = make_org(db, name="Other", tier="starter", period="monthly")
    foreign = _member(db, other_org, "foreign@example.com")
    url = f"/org/members/{member.id}/billing-contact"
    assert env.client.patch(f"/org/members/{foreign.id}/billing-contact", json={"is_billing_contact": True}).status_code == 404
    env.act_as(org, role="admin")
    assert env.client.patch(url, json={"is_billing_contact": True}).status_code == 403


# --- recipients -----------------------------------------------------------------------

@pytest.fixture
def team(db):
    org = make_org(db, tier="starter", period="monthly")
    _member(db, org, "owner@example.com", role="owner")
    _member(db, org, "admin@example.com", role="admin")
    _member(db, org, "finance@example.com", role="viewer", contact=True)
    _member(db, org, "gone@example.com", role="viewer", contact=True, deleted=True)
    return org


def test_owner_mode_goes_to_owners_only(db, team):
    assert resolve_billing_recipients(team, db) == ["owner@example.com"]


def test_selected_mode_goes_to_marked_members_not_deleted_ones(db, team):
    team.billing_emails_mode = "selected"
    db.commit()
    assert resolve_billing_recipients(team, db) == ["finance@example.com"]


def test_selected_mode_with_nobody_marked_falls_back_to_owners(db):
    org = make_org(db, tier="starter", period="monthly", billing_emails_mode="selected")
    _member(db, org, "owner@example.com", role="owner")
    _member(db, org, "viewer@example.com", role="viewer")
    assert resolve_billing_recipients(org, db) == ["owner@example.com"]


def test_all_mode_goes_to_every_live_member(db, team):
    team.billing_emails_mode = "all"
    db.commit()
    assert sorted(resolve_billing_recipients(team, db)) == [
        "admin@example.com", "finance@example.com", "owner@example.com",
    ]


def test_always_owners_adds_the_owner_without_duplicates(db, team):
    team.billing_emails_mode = "selected"
    db.commit()
    assert resolve_billing_recipients(team, db, always_owners=True) == ["finance@example.com", "owner@example.com"]
    team.billing_emails_mode = "owner"
    db.commit()
    assert resolve_billing_recipients(team, db, always_owners=True) == ["owner@example.com"]


# --- email content ----------------------------------------------------------------------

def _bill(currency="INR", amount=199900):
    return SimpleNamespace(
        id="b1", tier="starter", period="monthly", amount_paise=amount, currency=currency,
        due_date=date(2026, 12, 20), cancel_on=date(2027, 1, 1),
    )


def _payment(currency="INR", amount=199900):
    return SimpleNamespace(
        id="p1", amount_paise=amount, currency=currency, razorpay_payment_id="pay_x1",
        line_items={"description": "Basic monthly"},
    )


@pytest.mark.parametrize("kind", ["ready", "due_in_3", "cancel_in_3", "cancelled"])
@pytest.mark.parametrize("currency, amount, shown", [("INR", 199900, "\u20b91,999"), ("USD", 4900, "$49")])
def test_bill_emails_show_the_right_amount_dates_and_no_em_dash(kind, currency, amount, shown):
    org = SimpleNamespace(company_name="Acme")
    subject, text, body_html = render_billing_email(kind, org, bill=_bill(currency, amount))
    for part in (subject, text, body_html):
        assert EM_DASH not in part
    if kind in ("ready", "due_in_3"):
        assert "20 December 2026" in text
    if kind in ("ready", "due_in_3", "cancel_in_3"):
        assert "1 January 2027" in text
    assert shown in text


def test_payment_received_email_content():
    org = SimpleNamespace(company_name="Acme")
    subject, text, body_html = render_billing_email("payment_received", org, payment=_payment("USD", 4900))
    assert subject == "We received your payment of $49"
    assert "pay_x1" in text and "Basic monthly" in text
    assert EM_DASH not in subject + text + body_html


def test_voluntary_cancelled_email_needs_no_bill():
    org = SimpleNamespace(company_name="Acme")
    subject, text, _html = render_billing_email("cancelled", org)
    assert "as you asked" in text
    assert EM_DASH not in subject + text


def test_company_name_is_escaped_in_the_html_footer():
    org = SimpleNamespace(company_name="<b>x</b>")
    _s, _t, body_html = render_billing_email("ready", org, bill=_bill())
    assert "<b>x</b>" not in body_html
    assert "&lt;b&gt;x&lt;/b&gt;" in body_html


def test_render_rejects_a_missing_bill_payment_or_unknown_kind():
    org = SimpleNamespace(company_name="Acme")
    for kind in ("ready", "due_in_3", "cancel_in_3"):
        with pytest.raises(ValueError):
            render_billing_email(kind, org)
    with pytest.raises(ValueError):
        render_billing_email("payment_received", org)
    with pytest.raises(ValueError):
        render_billing_email("nope", org)


def test_format_money_and_date():
    assert format_money(199900, "INR") == "\u20b91,999"
    assert format_money(1199400, "INR") == "\u20b911,994"
    assert format_money(4900, "USD") == "$49"
    assert format_money(4950, "USD") == "$49.50"
    assert format_money(149400, "USD") == "$1,494"
    with pytest.raises(ValueError):
        format_money(100, "EUR")
    assert format_date(date(2026, 12, 1)) == "1 December 2026"


# --- sending ------------------------------------------------------------------------------

@pytest.fixture
def outbox(monkeypatch):
    import api.billing_emails as billing_emails

    sent: list[dict] = []

    def fake_send_email(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(billing_emails, "send_email", fake_send_email)
    return sent


def test_each_recipient_gets_one_email_and_the_cancel_notice_always_reaches_the_owner(db, team, outbox):
    team.billing_emails_mode = "selected"
    db.commit()
    bill = make_bill(db, team)
    assert send_billing_emails(db, "ready", team, bill) == 1
    assert [m["to"] for m in outbox] == ["finance@example.com"]
    outbox.clear()
    assert send_billing_emails(db, "cancel_in_3", team, bill) == 2
    assert sorted(m["to"] for m in outbox) == ["finance@example.com", "owner@example.com"]


def test_sending_with_no_recipients_is_a_quiet_zero(db, outbox):
    org = make_org(db, tier="starter", period="monthly")
    assert send_billing_emails(db, "ready", org, _bill()) == 0
    assert outbox == []


def test_a_failed_send_is_counted_not_raised(db, team, monkeypatch):
    import api.billing_emails as billing_emails

    monkeypatch.setattr(billing_emails, "send_email", lambda **kw: False)
    assert send_billing_emails(db, "payment_received", team, payment=_payment()) == 0


def test_the_celery_task_loads_rows_and_sends(db, team, outbox, session_factory, monkeypatch):
    import workers.tasks.billing_emails as task_module

    monkeypatch.setattr(task_module, "SessionLocal", session_factory)
    bill = make_bill(db, team)
    assert task_module.send_billing_email("ready", team.id, bill.id, None) == 1
    assert task_module.send_billing_email("ready", "missing-org", None, None) == 0


def test_notify_validates_the_kind_and_swallows_queue_errors(db, monkeypatch):
    import api.billing_notify as billing_notify

    org = make_org(db, tier="starter", period="monthly")
    with pytest.raises(ValueError):
        notify("typo", org)

    def broken(*_args):
        raise ConnectionError("no broker")

    monkeypatch.setattr(billing_notify, "_enqueue", broken)
    for kind in NOTIFY_KINDS:
        notify(kind, org)
