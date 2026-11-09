"""Phase 10 acceptance: payment reconciliation reports a deliberately dropped
webhook. Razorpay is a fake client, the database is in-memory SQLite."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import workers.tasks.reconcile_payments as rec
from api.tests.billing_testkit import make_org
from db.models import Payment

NOW = datetime.now(timezone.utc)


class FakeRazorpayPayments:
    def __init__(self, items: list[dict]) -> None:
        self.items = items
        self.calls: list[dict] = []
        self.payment = SimpleNamespace(all=self._all)

    def _all(self, params: dict) -> dict:
        self.calls.append(params)
        skip, count = params["skip"], params["count"]
        return {"entity": "collection", "items": self.items[skip : skip + count]}


def _remote(order_id: str, payment_id: str, *, amount=199_900, currency="INR", status="captured", age_hours=3.0):
    return {
        "id": payment_id, "order_id": order_id, "amount": amount, "currency": currency, "status": status,
        "created_at": int((NOW - timedelta(hours=age_hours)).timestamp()),
    }


def _local(db, org, order_id, *, status, payment_id=None, amount=199_900, currency="INR", age_hours=3.0):
    row = Payment(
        org_id=org.id, org_name_snapshot=org.company_name, razorpay_order_id=order_id,
        razorpay_payment_id=payment_id, amount_paise=amount, currency=currency, purpose="initial",
        status=status, line_items={}, tos_accepted=True,
        created_at=NOW - timedelta(hours=age_hours),
        captured_at=NOW - timedelta(hours=age_hours) if status == "captured" else None,
    )
    db.add(row)
    db.commit()
    return row


def _run(monkeypatch, session_factory, remote):
    saved: list[dict] = []
    monkeypatch.setattr(rec, "SessionLocal", session_factory)
    monkeypatch.setattr(rec, "_razorpay_client", lambda: FakeRazorpayPayments(remote))
    monkeypatch.setattr(rec, "save_reconciliation", saved.append)
    summary = rec.reconcile_payments()
    return summary, saved[-1] if saved else None


def test_a_dropped_webhook_is_reported(db, session_factory, monkeypatch):
    org = make_org(db, tier="free", period=None)
    # Razorpay captured the payment, the webhook never arrived and the browser
    # never called verify-payment: the local row is still "created".
    _local(db, org, "order_dropped", status="created")
    _local(db, org, "order_fine", status="captured", payment_id="pay_fine")

    summary, saved = _run(
        monkeypatch, session_factory,
        [_remote("order_dropped", "pay_dropped"), _remote("order_fine", "pay_fine")],
    )

    assert summary == {"status": "ok", "checked": 2, "discrepancies": 1}
    [d] = saved["discrepancies"]
    assert (d["kind"], d["razorpay_payment_id"], d["razorpay_order_id"]) == ("missed_webhook", "pay_dropped", "order_dropped")
    assert d["org_name"] == org.company_name and d["amount_paise"] == 199_900


def test_clean_books_report_nothing(db, session_factory, monkeypatch):
    org = make_org(db, tier="free", period=None)
    _local(db, org, "order_a", status="captured", payment_id="pay_a")
    _local(db, org, "order_b", status="refunded", payment_id="pay_b")

    summary, saved = _run(
        monkeypatch, session_factory,
        [_remote("order_a", "pay_a"), _remote("order_b", "pay_b", status="refunded")],
    )

    assert summary["discrepancies"] == 0 and saved["discrepancies"] == []


def test_unknown_order_amount_mismatch_and_missing_remote(db, session_factory, monkeypatch):
    org = make_org(db, tier="free", period=None)
    _local(db, org, "order_amount", status="captured", payment_id="pay_amount", amount=199_900)
    _local(db, org, "order_ghost", status="captured", payment_id="pay_ghost")

    _, saved = _run(
        monkeypatch, session_factory,
        [_remote("order_unknown", "pay_unknown"), _remote("order_amount", "pay_amount", amount=499_900)],
    )

    kinds = sorted((d["kind"], d["razorpay_payment_id"]) for d in saved["discrepancies"])
    assert kinds == [
        ("amount_mismatch", "pay_amount"),
        ("not_on_razorpay", "pay_ghost"),
        ("unknown_order", "pay_unknown"),
    ]


def test_recent_payments_and_uncaptured_ones_are_skipped(db, session_factory, monkeypatch):
    org = make_org(db, tier="free", period=None)
    _local(db, org, "order_new", status="created", age_hours=0.05)
    _local(db, org, "order_auth", status="created")

    summary, saved = _run(
        monkeypatch, session_factory,
        [
            _remote("order_new", "pay_new", age_hours=0.05),      # inside the 15 minute grace
            _remote("order_auth", "pay_auth", status="authorized"),
            _remote("order_failed", "pay_failed", status="failed"),
        ],
    )

    assert summary["checked"] == 0 and saved["discrepancies"] == []


def test_the_task_skips_when_razorpay_is_not_configured(monkeypatch):
    monkeypatch.setattr(rec, "_razorpay_client", lambda: None)
    assert rec.reconcile_payments() == {"status": "skipped", "reason": "razorpay_not_configured"}


def test_remote_listing_pages_through_every_payment():
    items = [_remote(f"order_{i}", f"pay_{i}") for i in range(250)]
    client = FakeRazorpayPayments(items)
    assert len(rec.fetch_remote_payments(client, NOW - timedelta(hours=48), NOW)) == 250
    assert [c["skip"] for c in client.calls] == [0, 100, 200]
