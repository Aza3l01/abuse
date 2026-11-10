"""Phase 4: payment rules that do not need the HTTP layer (api/billing_payments.py,
downgrade_org's refund reason) and the row-lock guarantee that needs Postgres."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from api.billing_payments import apply_captured_payment, refund_window
from api.tests.billing_testkit import make_org
from api.tiers import plan_price
from db.models import BillingEvent, Organization, Payment
from workers.tasks.billing_cycle import downgrade_org

BASIC_M = plan_price("INR", "basic", "monthly")
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def _payment(db, org, *, captured_at=None, status="captured", rz_id=None, purpose="initial") -> Payment:
    p = Payment(
        org_id=org.id,
        org_name_snapshot=org.company_name,
        razorpay_order_id=f"order_{uuid.uuid4().hex[:12]}",
        razorpay_payment_id=rz_id or f"pay_{uuid.uuid4().hex[:12]}",
        amount_paise=BASIC_M,
        currency="INR",
        purpose=purpose,
        status=status,
        line_items={"tier": "basic", "period": "monthly", "description": "Basic monthly"},
        tos_accepted=True,
        captured_at=captured_at,
    )
    db.add(p)
    db.commit()
    return p


# --- refund window edges ---------------------------------------------------

def test_refund_window_is_strict_at_72_hours(db):
    org = make_org(db, tier="basic")
    first = NOW - timedelta(hours=10)
    _payment(db, org, captured_at=first)
    expires = first + timedelta(hours=72)

    just_before = refund_window(org.id, db, now=expires - timedelta(seconds=1))
    assert just_before.eligible and just_before.reason == "remorse_window"
    assert just_before.expires_at == expires

    at_boundary = refund_window(org.id, db, now=expires)
    assert not at_boundary.eligible and at_boundary.reason == "not_eligible"

    after = refund_window(org.id, db, now=expires + timedelta(hours=1))
    assert not after.eligible and after.reason == "not_eligible"


def test_refund_window_runs_from_the_first_payment_not_the_latest(db):
    org = make_org(db, tier="basic")
    first = NOW - timedelta(hours=80)
    _payment(db, org, captured_at=first)
    _payment(db, org, captured_at=NOW - timedelta(hours=1), purpose="bill")
    assert refund_window(org.id, db, now=NOW).reason == "not_eligible"


def test_refund_window_covers_every_payment_captured_inside_it(db):
    org = make_org(db, tier="basic")
    first = NOW - timedelta(hours=20)
    a = _payment(db, org, captured_at=first)
    b = _payment(db, org, captured_at=first + timedelta(hours=5), purpose="upgrade")
    late = _payment(db, org, captured_at=first + timedelta(hours=80), purpose="bill")
    window = refund_window(org.id, db, now=NOW)
    assert window.eligible
    assert {p.id for p in window.payments} == {a.id, b.id}
    assert late.id not in {p.id for p in window.payments}


def test_refund_window_states_without_a_refundable_payment(db):
    org = make_org(db, tier="starter", period=None)
    assert refund_window(org.id, db, now=NOW).reason == "no_payment"
    p = _payment(db, org, captured_at=NOW - timedelta(hours=1), status="refunded")
    assert refund_window(org.id, db, now=NOW).reason == "already_refunded"
    p.status = "created"
    p.captured_at = None
    db.commit()
    assert refund_window(org.id, db, now=NOW).reason == "no_payment"


# --- apply_captured_payment ------------------------------------------------

def test_apply_captured_payment_is_idempotent(db):
    org = make_org(db, tier="starter", period=None)
    p = _payment(db, org, status="created")
    assert apply_captured_payment(p, db, razorpay_payment_id=p.razorpay_payment_id, now=NOW) is True
    db.commit()
    assert apply_captured_payment(p, db, now=NOW) is False
    db.commit()
    assert db.query(BillingEvent).filter(BillingEvent.org_id == org.id).count() == 1


def test_apply_captured_payment_ignores_a_refunded_payment(db):
    org = make_org(db, tier="starter", period=None)
    p = _payment(db, org, status="refunded", captured_at=NOW)
    assert apply_captured_payment(p, db, now=NOW) is False
    db.refresh(org)
    assert org.tier == "starter"


def test_apply_captured_payment_for_a_deleted_org_changes_nothing(db):
    org = make_org(db, tier="starter", period=None, deleted_at=NOW)
    p = _payment(db, org, status="created")
    assert apply_captured_payment(p, db, now=NOW) is True
    db.commit()
    db.refresh(org)
    assert org.tier == "starter"
    assert db.get(Payment, p.id).status == "captured"


def test_initial_payment_on_an_org_that_already_has_a_plan_leaves_it_unchanged(db):
    org = make_org(db, tier="growth", period="monthly")
    p = _payment(db, org, status="created")
    assert apply_captured_payment(p, db, now=NOW) is True
    db.commit()
    db.refresh(org)
    assert (org.tier, org.billing_period) == ("growth", "monthly")


# --- downgrade_org with the refund reason ----------------------------------

def test_downgrade_org_refund_reason_records_the_refunded_amount(db):
    org = make_org(db, tier="basic", period="monthly", cancel_at_period_end=True)
    assert downgrade_org(org, db, "refund", NOW, amount_paise=BASIC_M) is True
    db.commit()
    assert (org.tier, org.billing_period, org.next_billing_date) == ("starter", None, None)
    assert org.nonpayment_downgraded_at is None
    assert org.retention_grace_tier == "basic"
    assert org.cancel_at_period_end is False
    [event] = db.query(BillingEvent).filter(BillingEvent.org_id == org.id).all()
    assert (event.event, event.from_tier, event.to_tier, event.amount_paise) == ("refunded", "basic", "starter", BASIC_M)
    assert event.currency == "INR"
    assert downgrade_org(org, db, "refund", NOW) is False


def test_billing_event_currency_follows_the_org_and_is_null_without_an_amount(db):
    usd = make_org(db, tier="basic", period="monthly", billing_country=None, billing_currency="USD")
    assert downgrade_org(usd, db, "refund", NOW, amount_paise=1900) is True
    cancelled = make_org(db, tier="basic", period="monthly", billing_country=None, billing_currency="USD")
    assert downgrade_org(cancelled, db, "cancel", NOW) is True
    db.commit()
    refunded = db.query(BillingEvent).filter(BillingEvent.org_id == usd.id).one()
    assert (refunded.amount_paise, refunded.currency) == (1900, "USD")
    plain = db.query(BillingEvent).filter(BillingEvent.org_id == cancelled.id).one()
    assert (plain.amount_paise, plain.currency) == (None, None)


# --- concurrent verify (needs a real Postgres, SQLite ignores FOR UPDATE) ---

@pytest.fixture
def postgres_factory():
    """A throwaway database on the local Postgres server, dropped afterwards.
    Skipped when no local server is reachable. Never touches a non-local host."""
    import os

    import api.main  # noqa: F401  (applies the gitignored .env.local override)
    from db.models import Base

    base = make_url(os.environ["DATABASE_URL"])
    if not base.drivername.startswith("postgresql") or base.host not in ("localhost", "127.0.0.1", None):
        pytest.skip("local Postgres not configured")
    name = f"clew_phase4_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:
        admin.dispose()
        pytest.skip(f"cannot create a throwaway database: {exc}")
    engine = create_engine(base.set(database=name))
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.mark.parametrize("callers", [2, 12])
def test_concurrent_applies_credit_once(postgres_factory, callers):
    setup = postgres_factory()
    org = make_org(setup, tier="starter", period=None)
    payment = _payment(setup, org, status="created")
    org_id, payment_id = org.id, payment.id
    setup.close()

    barrier = threading.Barrier(callers)
    results: list[bool] = []
    errors: list[BaseException] = []

    def worker():
        session = postgres_factory()
        try:
            row = session.get(Payment, payment_id)
            barrier.wait(timeout=10)
            applied = apply_captured_payment(row, session, razorpay_payment_id="pay_once", now=NOW)
            session.commit()
            results.append(applied)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            session.rollback()
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(callers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    assert sorted(results) == [False] * (callers - 1) + [True]
    check = postgres_factory()
    try:
        assert check.get(Organization, org_id).tier == "basic"
        assert check.query(BillingEvent).filter(BillingEvent.org_id == org_id).count() == 1
        assert check.get(Payment, payment_id).status == "captured"
    finally:
        check.close()


def test_a_bill_payment_and_an_upgrade_payment_applied_together_both_land(postgres_factory):
    from api.tests.conftest import make_bill

    setup = postgres_factory()
    org = make_org(setup, tier="basic", period="monthly")
    bill = make_bill(setup, org)
    upgrade = _payment(setup, org, status="created", purpose="upgrade")
    upgrade.line_items = {"tier": "growth", "period": "monthly", "from_tier": "basic", "from_period": "monthly"}
    pay_bill = _payment(setup, org, status="created", purpose="bill")
    pay_bill.line_items = {"bill_ids": [bill.id]}
    setup.commit()
    org_id, bill_id, ids = org.id, bill.id, [upgrade.id, pay_bill.id]
    setup.close()

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker(payment_id):
        session = postgres_factory()
        try:
            row = session.get(Payment, payment_id)
            barrier.wait(timeout=10)
            apply_captured_payment(row, session, now=NOW)
            session.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            session.rollback()
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(pid,)) for pid in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    from db.models import Bill

    assert errors == []
    check = postgres_factory()
    try:
        assert check.get(Organization, org_id).tier == "growth"
        assert check.get(Bill, bill_id).status == "paid"
        assert {check.get(Payment, pid).status for pid in ids} == {"captured"}
    finally:
        check.close()
