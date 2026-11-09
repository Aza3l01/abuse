"""pytest fixtures for api/tests.

`env` wires the real FastAPI app to an in-memory SQLite database and a fake
Razorpay client, so the billing routes run end to end with no network. The
fake never sees a real key: the key id and secret below are test values set
through monkeypatch.
"""
from __future__ import annotations

import hashlib
import hmac
import itertools
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.billing_rules import today_ist
from api.deps import CurrentOrg, get_current_org, get_db
from api.tests.billing_testkit import capture_notifications, make_org, make_session_factory
from db.models import Bill, Organization

KEY_ID = "rzp_test_unit"
KEY_SECRET = "unit_key_secret"
WEBHOOK_SECRET = "unit_webhook_secret"


class FakeRazorpay:
    """The slice of razorpay.Client the billing routes use."""

    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}
        self.refund_calls: list[tuple[str, dict]] = []
        self.fail_refunds = False
        self._ids = itertools.count(1)
        self.order = SimpleNamespace(create=self._order_create)
        self.payment = SimpleNamespace(fetch=self._payment_fetch, refund=self._payment_refund)

    def _order_create(self, data: dict) -> dict:
        order_id = f"order_fake{next(self._ids)}"
        self.orders[order_id] = data
        return {"id": order_id, **data}

    def _payment_fetch(self, payment_id: str) -> dict:
        return self.payments[payment_id]

    def _payment_refund(self, payment_id: str, data: dict) -> dict:
        if self.fail_refunds:
            raise RuntimeError("refund rejected")
        self.refund_calls.append((payment_id, data))
        return {"id": f"rfnd_fake{next(self._ids)}", "payment_id": payment_id, "amount": data.get("amount")}

    def pay(
        self, order_id: str, *, amount: int | None = None, status: str = "captured", currency: str | None = None
    ) -> str:
        """Record a customer's payment against an order and return its id."""
        payment_id = f"pay_fake{next(self._ids)}"
        self.payments[payment_id] = {
            "id": payment_id,
            "order_id": order_id,
            "amount": self.orders[order_id]["amount"] if amount is None else amount,
            "currency": self.orders[order_id]["currency"] if currency is None else currency,
            "international": False,
            "status": status,
            "method": "card",
            "card": {"network": "Visa", "last4": "1007"},
        }
        return payment_id


def checkout_signature(order_id: str, payment_id: str, secret: str = KEY_SECRET) -> str:
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


class Env:
    def __init__(self, client: TestClient, db, rp: FakeRazorpay, ctx: dict) -> None:
        self.client = client
        self.db = db
        self.rp = rp
        self._ctx = ctx
        self._event_ids = itertools.count(1)

    def act_as(self, org: Organization, role: str = "owner") -> Organization:
        self._ctx["org_id"] = org.id
        self._ctx["role"] = role
        return org

    def refresh(self, *objs) -> None:
        self.db.expire_all()

    def create_order(self, **body):
        return self.client.post("/billing/razorpay/create-order", json=body)

    def verify(self, order_id: str, payment_id: str, signature: str | None = None):
        return self.client.post(
            "/billing/razorpay/verify-payment",
            json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature or checkout_signature(order_id, payment_id),
            },
        )

    def webhook(self, event: dict, *, secret: str = WEBHOOK_SECRET, event_id: str | None = None):
        raw = json.dumps(event).encode()
        sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return self.client.post(
            "/billing/razorpay/webhook",
            content=raw,
            headers={
                "x-razorpay-signature": sig,
                "x-razorpay-event-id": event_id or f"evt_{next(self._event_ids)}",
                "content-type": "application/json",
            },
        )

    def captured_event(self, payment_id: str) -> dict:
        return {"event": "payment.captured", "payload": {"payment": {"entity": self.rp.payments[payment_id]}}}


@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    """Queued billing emails, recorded instead of sent (no broker in tests)."""
    return capture_notifications(monkeypatch)


@pytest.fixture
def session_factory():
    return make_session_factory()


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def env(db, session_factory, monkeypatch):
    from api.main import app
    import api.routes.billing as billing_routes

    monkeypatch.setenv("RAZORPAY_KEY_ID", KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", KEY_SECRET)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)

    rp = FakeRazorpay()
    monkeypatch.setattr(billing_routes, "_init_razorpay", lambda: rp)
    monkeypatch.setattr(billing_routes, "SessionLocal", session_factory)

    ctx: dict = {"org_id": None, "role": "owner"}

    def _db():
        yield db

    def _current_org():
        return CurrentOrg(organization=db.get(Organization, ctx["org_id"]), role=ctx["role"])

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_org] = _current_org
    try:
        yield Env(TestClient(app), db, rp, ctx)
    finally:
        app.dependency_overrides.clear()


def make_bill(db, org: Organization, *, tier: str = "starter", period: str = "monthly",
              amount: int = 199_900, start: date | None = None, status: str = "open",
              currency: str = "INR") -> Bill:
    """An open bill whose period covers today (IST) unless `start` says otherwise."""
    start = start or (today_ist() - timedelta(days=2))
    bill = Bill(
        org_id=org.id,
        org_name_snapshot=org.company_name,
        tier=tier,
        period=period,
        period_start=start,
        period_end=start + timedelta(days=30),
        amount_paise=amount,
        currency=currency,
        due_date=start + timedelta(days=19),
        cancel_on=start + timedelta(days=30),
        status=status,
    )
    db.add(bill)
    db.commit()
    return bill


__all__ = ["make_org", "make_bill", "checkout_signature", "KEY_SECRET", "WEBHOOK_SECRET"]
