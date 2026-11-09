"""Phase 3: the daily billing engine (workers/tasks/billing_cycle.py).

Runs run_billing_cycle against an in-memory SQLite database built from the
real models, with the notifier replaced by a recorder. Timelines walk the
engine day by day exactly like the daily Beat task would.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from api.billing_rules import ist_date, ist_midnight
from db.models import Bill, BillingEvent, Organization
from api.tests.billing_testkit import make_org
from workers.tasks import billing_cycle as cycle


@pytest.fixture
def notices(monkeypatch):
    """Records every notify() call as (kind, today, org_id, bill_id)."""
    calls: list[tuple] = []
    state = {"today": None}

    def fake_notify(kind, org, bill=None):
        calls.append((kind, state["today"], org.id, getattr(bill, "id", None)))

    monkeypatch.setattr(cycle, "notify", fake_notify)
    return SimpleNamespace(calls=calls, state=state)


def run_day(db, notices, day: date) -> dict:
    notices.state["today"] = day
    now = ist_midnight(day) + timedelta(minutes=30)
    return cycle.run_billing_cycle(db, day, now)


def run_days(db, notices, start: date, end: date) -> None:
    day = start
    while day <= end:
        run_day(db, notices, day)
        day += timedelta(days=1)


def days_of(notices, kind: str, org_id: str | None = None) -> list[date]:
    return [d for k, d, o, _ in notices.calls if k == kind and (org_id is None or o == org_id)]


def bills_of(db, org_id: str) -> list[Bill]:
    return db.query(Bill).filter(Bill.org_id == org_id).order_by(Bill.period_start).all()


def events_of(db, org_id: str) -> list[str]:
    rows = db.query(BillingEvent).filter(BillingEvent.org_id == org_id).order_by(BillingEvent.created_at).all()
    return [r.event for r in rows]


# --- timelines -------------------------------------------------------------

def test_nov_4_payer_timeline(db, notices):
    # Paid Nov 4: next bill 1 Dec (anchor rule).
    org = make_org(db, tier="starter", next_bill=date(2026, 12, 1))
    oid = org.id

    run_days(db, notices, date(2026, 11, 25), date(2026, 11, 30))
    assert bills_of(db, oid) == []

    run_day(db, notices, date(2026, 12, 1))
    [bill] = bills_of(db, oid)
    assert bill.period_start == date(2026, 12, 1)
    assert bill.period_end == date(2027, 1, 1)
    assert bill.due_date == date(2026, 12, 20)
    assert bill.cancel_on == date(2027, 1, 1)
    assert bill.amount_paise == 199900
    assert bill.currency == "INR"
    assert bill.status == "open"
    assert bill.org_name_snapshot == "Acme"
    assert ist_date(db.get(Organization, oid).next_billing_date) == date(2027, 1, 1)
    assert days_of(notices, "ready") == [date(2026, 12, 1)]

    run_days(db, notices, date(2026, 12, 2), date(2026, 12, 31))
    assert days_of(notices, "due_in_3") == [date(2026, 12, 17)]
    # Cancel date 1 Jan, so the warning is 29 Dec (cancel_on minus 3 days).
    assert days_of(notices, "cancel_in_3") == [date(2026, 12, 29)]
    assert db.get(Organization, oid).tier == "starter"
    assert days_of(notices, "cancelled") == []

    run_day(db, notices, date(2027, 1, 1))
    org = db.get(Organization, oid)
    assert org.tier == "free"
    assert org.nonpayment_downgraded_at is not None
    [bill] = bills_of(db, oid)          # no second bill, the first is still open
    assert bill.status == "open"
    assert org.next_billing_date is None and org.billing_period is None
    assert events_of(db, oid) == ["nonpayment_downgrade"]
    assert days_of(notices, "cancelled") == [date(2027, 1, 1)]

    run_days(db, notices, date(2027, 1, 2), date(2027, 2, 5))
    assert len(bills_of(db, oid)) == 1  # a downgraded org is never billed again


def test_nov_20_payer_timeline(db, notices):
    # Paid Nov 20: day 16 or later, so the first bill is 1 Jan, not 1 Dec.
    org = make_org(db, tier="starter", next_bill=date(2027, 1, 1))
    oid = org.id
    run_days(db, notices, date(2026, 11, 20), date(2026, 12, 31))
    assert bills_of(db, oid) == []
    assert days_of(notices, "ready") == []

    run_day(db, notices, date(2027, 1, 1))
    [bill] = bills_of(db, oid)
    assert bill.period_start == date(2027, 1, 1)
    assert bill.due_date == date(2027, 1, 20)
    assert bill.cancel_on == date(2027, 2, 1)
    assert ist_date(db.get(Organization, oid).next_billing_date) == date(2027, 2, 1)


def test_annual_timeline(db, notices):
    # Paid Nov 4 2026 on an annual plan: first annual bill 1 Dec 2027.
    org = make_org(db, tier="growth", period="annual", next_bill=date(2027, 12, 1))
    oid = org.id
    run_days(db, notices, date(2027, 11, 28), date(2027, 11, 30))
    assert bills_of(db, oid) == []

    run_day(db, notices, date(2027, 12, 1))
    [bill] = bills_of(db, oid)
    assert bill.period == "annual"
    assert bill.amount_paise == 2999400
    assert bill.period_start == date(2027, 12, 1)
    assert bill.period_end == date(2028, 12, 1)
    assert bill.due_date == date(2027, 12, 20)        # assumption 9
    assert bill.cancel_on == date(2028, 1, 1)         # assumption 9
    assert ist_date(db.get(Organization, oid).next_billing_date) == date(2028, 12, 1)

    # Nothing more is billed during the annual term.
    run_days(db, notices, date(2027, 12, 2), date(2028, 1, 31))
    assert len(bills_of(db, oid)) == 1


def test_a_paid_bill_is_never_enforced_and_the_next_month_is_billed(db, notices):
    org = make_org(db, tier="starter", next_bill=date(2026, 12, 1))
    oid = org.id
    run_day(db, notices, date(2026, 12, 1))
    [bill] = bills_of(db, oid)
    bill.status = "paid"
    bill.paid_at = datetime(2026, 12, 5, tzinfo=timezone.utc)
    db.commit()

    run_days(db, notices, date(2026, 12, 2), date(2027, 1, 1))
    org = db.get(Organization, oid)
    assert org.tier == "starter"
    assert [b.period_start for b in bills_of(db, oid)] == [date(2026, 12, 1), date(2027, 1, 1)]
    # Reminders were only for the open bills.
    assert days_of(notices, "due_in_3") == []
    assert days_of(notices, "cancel_in_3") == []


def test_february_reminder_dates_in_a_real_run(db, notices):
    org = make_org(db, tier="starter", next_bill=date(2027, 2, 1))
    run_days(db, notices, date(2027, 2, 1), date(2027, 2, 28))
    assert days_of(notices, "due_in_3") == [date(2027, 2, 17)]
    assert days_of(notices, "cancel_in_3") == [date(2027, 2, 26)]


# --- pending change, idempotency, missed day -------------------------------

def test_pending_downgrade_is_applied_at_issue(db, notices):
    org = make_org(
        db, tier="growth", period="monthly", next_bill=date(2026, 12, 1),
        pending_tier="starter",
    )
    oid = org.id
    run_day(db, notices, date(2026, 12, 1))
    org = db.get(Organization, oid)
    [bill] = bills_of(db, oid)
    assert bill.tier == "starter"
    assert bill.amount_paise == 199900
    assert org.tier == "starter"
    assert org.pending_tier is None and org.pending_period is None
    assert events_of(db, oid) == ["downgraded"]
    event = db.query(BillingEvent).filter(BillingEvent.org_id == oid).one()
    assert (event.from_tier, event.to_tier, event.period) == ("growth", "starter", "monthly")


def test_pending_annual_to_monthly_is_applied_at_issue(db, notices):
    org = make_org(
        db, tier="growth", period="annual", next_bill=date(2027, 12, 1),
        pending_period="monthly",
    )
    oid = org.id
    run_day(db, notices, date(2027, 12, 1))
    org = db.get(Organization, oid)
    [bill] = bills_of(db, oid)
    assert (bill.tier, bill.period, bill.amount_paise) == ("growth", "monthly", 499900)
    assert org.billing_period == "monthly"
    assert ist_date(org.next_billing_date) == date(2028, 1, 1)


def test_double_run_on_the_same_day_creates_one_bill_and_one_notice(db, notices):
    org = make_org(db, tier="growth", next_bill=date(2026, 12, 1))
    oid = org.id
    first = run_day(db, notices, date(2026, 12, 1))
    second = run_day(db, notices, date(2026, 12, 1))
    assert first["bills_issued"] == 1
    assert second["bills_issued"] == 0
    assert len(bills_of(db, oid)) == 1
    assert days_of(notices, "ready") == [date(2026, 12, 1)]

    run_day(db, notices, date(2026, 12, 17))
    run_day(db, notices, date(2026, 12, 17))
    assert days_of(notices, "due_in_3") == [date(2026, 12, 17)]


def test_double_run_on_the_downgrade_day_changes_nothing_the_second_time(db, notices):
    org = make_org(db, tier="starter", next_bill=date(2026, 12, 1))
    oid = org.id
    run_days(db, notices, date(2026, 12, 1), date(2027, 1, 1))
    grace_until = db.get(Organization, oid).retention_grace_until
    second = run_day(db, notices, date(2027, 1, 1))
    assert second["nonpayment_downgrades"] == 0
    assert db.get(Organization, oid).retention_grace_until == grace_until
    assert events_of(db, oid) == ["nonpayment_downgrade"]
    assert days_of(notices, "cancelled") == [date(2027, 1, 1)]


def test_a_missed_day_catches_up_with_the_same_bill_dates(db, notices):
    org = make_org(db, tier="starter", next_bill=date(2026, 12, 1))
    oid = org.id
    # The 1 Dec run never happened. The 2 Dec run issues the 1 Dec bill.
    run_day(db, notices, date(2026, 11, 30))
    run_day(db, notices, date(2026, 12, 2))
    [bill] = bills_of(db, oid)
    assert bill.period_start == date(2026, 12, 1)
    assert bill.due_date == date(2026, 12, 20)
    assert bill.cancel_on == date(2027, 1, 1)
    assert ist_date(db.get(Organization, oid).next_billing_date) == date(2027, 1, 1)


def test_a_missed_day_still_sends_the_reminder_window(db, notices):
    org = make_org(db, tier="starter", next_bill=date(2026, 12, 1))
    run_day(db, notices, date(2026, 12, 1))
    # 17 Dec was missed, the 18 Dec run is still inside the window.
    run_day(db, notices, date(2026, 12, 18))
    assert days_of(notices, "due_in_3") == [date(2026, 12, 18)]
    # Once the due date itself has arrived, "due in 3 days" is not sent.
    org2 = make_org(db, tier="growth", name="Late", next_bill=date(2026, 12, 1))
    run_day(db, notices, date(2026, 12, 20))
    assert days_of(notices, "due_in_3", org2.id) == []


def test_at_most_one_bill_per_org_per_run_after_a_long_outage(db, notices):
    org = make_org(db, tier="starter", next_bill=date(2026, 12, 1))
    oid = org.id
    stats = run_day(db, notices, date(2027, 1, 5))
    assert stats["bills_issued"] == 1
    [bill] = bills_of(db, oid)
    assert bill.period_start == date(2026, 12, 1)
    # The next run enforces that bill (its cancel_on has passed).
    run_day(db, notices, date(2027, 1, 6))
    assert db.get(Organization, oid).tier == "free"
    assert len(bills_of(db, oid)) == 1


# --- voluntary cancel ------------------------------------------------------

def test_voluntary_cancel_at_period_end_issues_no_bill(db, notices):
    org = make_org(db, tier="growth", next_bill=date(2026, 12, 1), cancel_at_period_end=True)
    oid = org.id
    run_days(db, notices, date(2026, 11, 28), date(2026, 11, 30))
    assert db.get(Organization, oid).tier == "growth"

    run_day(db, notices, date(2026, 12, 1))
    org = db.get(Organization, oid)
    assert org.tier == "free"
    assert org.retention_grace_tier == "growth"
    assert org.nonpayment_downgraded_at is None     # only nonpayment sets it
    assert org.cancel_at_period_end is False
    assert bills_of(db, oid) == []
    assert events_of(db, oid) == ["cancelled"]
    assert days_of(notices, "cancelled") == [date(2026, 12, 1)]


def test_open_bill_beats_a_cancel_request_and_counts_as_nonpayment(db, notices):
    org = make_org(db, tier="starter", next_bill=date(2026, 12, 1))
    oid = org.id
    run_day(db, notices, date(2026, 12, 1))
    db.get(Organization, oid).cancel_at_period_end = True
    db.commit()
    run_day(db, notices, date(2027, 1, 1))
    assert events_of(db, oid) == ["nonpayment_downgrade"]
    assert db.get(Organization, oid).nonpayment_downgraded_at is not None


# --- reminders switch ------------------------------------------------------

def test_routine_reminders_can_be_turned_off_but_the_cancel_warning_cannot(db, notices):
    org = make_org(db, tier="starter", next_bill=date(2026, 12, 1), billing_reminders_enabled=False)
    oid = org.id
    run_days(db, notices, date(2026, 12, 1), date(2026, 12, 31))
    assert days_of(notices, "ready", oid) == []
    assert days_of(notices, "due_in_3", oid) == []
    assert days_of(notices, "cancel_in_3", oid) == [date(2026, 12, 29)]
    assert len(bills_of(db, oid)) == 1


# --- not billable ----------------------------------------------------------

def test_orgs_the_engine_must_not_bill(db, notices):
    free = make_org(db, tier="free", period=None, name="Free")
    pilot = make_org(
        db, tier="growth", period=None, name="Pilot",
        billing_provider="pilot", trial_ends_at=datetime(2026, 12, 15, tzinfo=timezone.utc),
    )
    legacy = make_org(db, tier="growth", period=None, name="Legacy", next_bill=date(2026, 12, 1))
    deleted = make_org(
        db, tier="starter", name="Gone", next_bill=date(2026, 12, 1),
        deleted_at=datetime(2026, 11, 30, tzinfo=timezone.utc),
    )
    db.commit()
    stats = run_day(db, notices, date(2026, 12, 1))
    assert stats["bills_issued"] == 0
    assert stats["skipped_unbillable"] == 1      # the legacy org, logged and skipped
    assert db.query(Bill).count() == 0
    assert db.get(Organization, pilot.id).tier == "growth"
    assert db.get(Organization, free.id).tier == "free"
    assert db.get(Organization, legacy.id).tier == "growth"
    assert db.get(Organization, deleted.id).tier == "starter"


# --- currency --------------------------------------------------------------

def test_a_usd_org_is_billed_in_cents_with_a_usd_bill(db, notices):
    org = make_org(
        db, tier="growth", next_bill=date(2026, 12, 1), billing_country="US", billing_currency="USD",
    )
    run_day(db, notices, date(2026, 12, 1))
    [bill] = bills_of(db, org.id)
    assert (bill.amount_paise, bill.currency) == (12900, "USD")
    assert days_of(notices, "ready") == [date(2026, 12, 1)]


def test_a_usd_annual_org_is_billed_the_usd_annual_price(db, notices):
    org = make_org(
        db, tier="pro", period="annual", next_bill=date(2026, 12, 1),
        billing_country="GB", billing_currency="USD",
    )
    run_day(db, notices, date(2026, 12, 1))
    [bill] = bills_of(db, org.id)
    assert (bill.amount_paise, bill.currency) == (149400, "USD")


def test_a_paid_org_with_no_billing_country_is_skipped_not_billed_in_a_guess(db, notices):
    org = make_org(
        db, tier="starter", next_bill=date(2026, 12, 1), billing_country=None, billing_currency="USD",
    )
    stats = run_day(db, notices, date(2026, 12, 1))
    assert stats["bills_issued"] == 0
    assert stats["skipped_unbillable"] == 1
    assert bills_of(db, org.id) == []
    assert notices.calls == []


def test_the_pending_downgrade_bills_the_new_plan_in_the_same_currency(db, notices):
    org = make_org(
        db, tier="pro", next_bill=date(2026, 12, 1), billing_country="US", billing_currency="USD",
        pending_tier="starter", pending_period="monthly",
    )
    run_day(db, notices, date(2026, 12, 1))
    [bill] = bills_of(db, org.id)
    assert (bill.tier, bill.amount_paise, bill.currency) == ("starter", 4900, "USD")


def test_reminders_are_queued_after_the_commit(db, notices, monkeypatch):
    """A reminder must never go out for a state that was rolled back, so the
    notifier is only called once the day's changes are committed."""
    org = make_org(db, tier="starter", next_bill=date(2026, 12, 1))
    run_day(db, notices, date(2026, 12, 1))
    seen: list[bool] = []

    def watcher(kind, org_, bill=None):
        seen.append(db.in_transaction() and bool(db.new or db.dirty))

    monkeypatch.setattr(cycle, "notify", watcher)
    run_day(db, notices, date(2026, 12, 17))
    assert seen == [False]
    assert org.id


def test_one_failing_org_does_not_stop_the_others(db, notices, monkeypatch):
    good = make_org(db, tier="starter", name="Good", next_bill=date(2026, 12, 1))
    bad = make_org(db, tier="growth", name="Bad", next_bill=date(2026, 12, 1))
    bad_id, good_id = bad.id, good.id
    real = cycle.next_bill_date_after_issue

    def flaky(issue, period):
        flaky.calls += 1
        if flaky.calls == 1:
            raise RuntimeError("boom")
        return real(issue, period)

    flaky.calls = 0
    monkeypatch.setattr(cycle, "next_bill_date_after_issue", flaky)
    stats = run_day(db, notices, date(2026, 12, 1))
    assert stats["errors"] == 1
    assert stats["bills_issued"] == 1
    assert len(bills_of(db, good_id)) + len(bills_of(db, bad_id)) == 1


# --- downgrade_org ---------------------------------------------------------

def test_downgrade_org_resets_everything_for_each_reason(db):
    now = datetime(2026, 12, 1, tzinfo=timezone.utc)
    for reason, event in [
        ("nonpayment", "nonpayment_downgrade"),
        ("cancel", "cancelled"),
        ("trial_end", "trial_end"),
    ]:
        org = make_org(
            db, tier="pro", period="annual", next_bill=date(2026, 12, 1),
            auto_block_enabled=True, cancel_at_period_end=True,
            pending_tier="growth", pending_period="monthly", name=reason,
        )
        assert cycle.downgrade_org(org, db, reason, now) is True
        db.commit()
        assert org.tier == "free"
        assert org.retention_grace_tier == "pro"
        assert org.retention_grace_until == now + timedelta(days=30) or \
            org.retention_grace_until.replace(tzinfo=timezone.utc) == now + timedelta(days=30)
        assert org.auto_block_enabled is False
        assert org.next_billing_date is None
        assert org.billing_period is None
        assert org.cancel_at_period_end is False
        assert org.pending_tier is None and org.pending_period is None
        assert (org.nonpayment_downgraded_at is not None) == (reason == "nonpayment")
        ev = db.query(BillingEvent).filter(BillingEvent.org_id == org.id).one()
        assert (ev.event, ev.from_tier, ev.to_tier, ev.period) == (event, "pro", "free", "annual")


def test_downgrade_org_leaves_a_free_org_alone_and_rejects_a_bad_reason(db):
    org = make_org(db, tier="free", period=None)
    assert cycle.downgrade_org(org, db, "nonpayment") is False
    assert org.retention_grace_tier is None
    assert db.query(BillingEvent).count() == 0
    paid = make_org(db, tier="starter", name="Paid")
    with pytest.raises(ValueError):
        cycle.downgrade_org(paid, db, "because")
    assert paid.tier == "starter"


def test_downgrade_keeps_open_bills_open(db, notices):
    org = make_org(db, tier="starter", next_bill=date(2026, 12, 1))
    oid = org.id
    run_days(db, notices, date(2026, 12, 1), date(2027, 1, 1))
    assert [b.status for b in bills_of(db, oid)] == ["open"]
