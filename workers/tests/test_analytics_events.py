"""Phase 11: billing and scan events sent from the workers, and heartbeats.

plan_cancelled and bill_overdue come from workers/tasks/billing_cycle.py. The
heartbeat helper is workers/heartbeat.py. All network is replaced with fakes.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api.billing_rules import ist_midnight
from api.tests.analytics_testkit import add_owner, install
from api.tests.billing_testkit import make_org
from api.tests.conftest import make_bill
from workers import heartbeat
from workers.tasks import billing_cycle as cycle


@pytest.fixture
def posthog(monkeypatch):
    fake, fake_redis = install(monkeypatch)
    fake.redis = fake_redis
    return fake


# --- plan_cancelled -----------------------------------------------------------------

@pytest.mark.parametrize("reason", ["cancel", "nonpayment", "refund"])
def test_downgrade_sends_plan_cancelled(db, posthog, reason):
    org = make_org(db, tier="growth", period="annual")
    owner = add_owner(db, org)
    assert cycle.downgrade_org(org, db, reason) is True
    assert posthog.events == []  # nothing until the caller commits
    db.commit()
    [(_, distinct_id, props)] = posthog.named("plan_cancelled")
    assert distinct_id == owner
    assert props == {"org_id": org.id, "reason": reason, "from_tier": "growth", "period": "annual"}


def test_trial_end_is_not_a_cancellation(db, posthog):
    org = make_org(db, tier="basic", period="monthly")
    add_owner(db, org)
    cycle.downgrade_org(org, db, "trial_end")
    db.commit()
    assert posthog.events == []


def test_second_downgrade_sends_nothing(db, posthog):
    org = make_org(db, tier="basic", period="monthly")
    add_owner(db, org)
    cycle.downgrade_org(org, db, "cancel")
    db.commit()
    assert cycle.downgrade_org(org, db, "cancel") is False
    db.commit()
    assert len(posthog.named("plan_cancelled")) == 1


def test_rolled_back_downgrade_sends_nothing(db, posthog):
    org = make_org(db, tier="basic", period="monthly")
    add_owner(db, org)
    cycle.downgrade_org(org, db, "nonpayment")
    db.rollback()
    assert posthog.events == []


# --- bill_overdue ----------------------------------------------------------------------

def test_overdue_bill_is_announced_once_across_daily_runs(db, posthog):
    org = make_org(db, tier="basic", period="monthly", next_bill=date(2027, 1, 1))
    owner = add_owner(db, org)
    bill = make_bill(db, org, start=date(2026, 12, 1))  # due 20 Dec, cancels 31 Dec

    for day in (date(2026, 12, 19), date(2026, 12, 20)):
        cycle.run_billing_cycle(db, day, ist_midnight(day) + timedelta(minutes=30))
    assert posthog.named("bill_overdue") == []

    for day in (date(2026, 12, 21), date(2026, 12, 22), date(2026, 12, 23)):
        cycle.run_billing_cycle(db, day, ist_midnight(day) + timedelta(minutes=30))
    [(_, distinct_id, props)] = posthog.named("bill_overdue")
    assert distinct_id == owner
    assert props["org_id"] == org.id
    assert props["tier"] == "basic"
    assert props["due_date"] == "2026-12-20"
    assert props["cancel_on"] == bill.cancel_on.isoformat()


def test_cycle_stats_are_unchanged_by_overdue_reporting(db, posthog):
    make_org(db, tier="basic", period="monthly", next_bill=date(2027, 1, 1))
    day = date(2026, 12, 22)
    stats = cycle.run_billing_cycle(db, day, ist_midnight(day) + timedelta(minutes=30))
    assert "errors" in stats and stats["errors"] == 0


def test_free_orgs_are_not_announced(db, posthog):
    free = make_org(db, tier="starter", period=None, name="Free")
    add_owner(db, free, email="free@example.test")
    make_bill(db, free, start=date(2026, 12, 1))
    day = date(2026, 12, 22)
    cycle._announce_overdue(db, day)
    assert posthog.events == []


def test_overdue_step_is_a_no_op_when_analytics_is_off(db, monkeypatch):
    fake, _ = install(monkeypatch, enabled=False)
    org = make_org(db, tier="basic", period="monthly")
    add_owner(db, org)
    make_bill(db, org, start=date(2026, 12, 1))
    cycle._announce_overdue(db, date(2026, 12, 22))
    assert fake.events == []


# --- heartbeats ------------------------------------------------------------------------------

@pytest.fixture
def pings(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(heartbeat.httpx, "get", lambda url, timeout=None: calls.append(url))
    return calls


def test_ping_hits_the_url(monkeypatch, pings):
    monkeypatch.setenv("HEARTBEAT_URL", "https://uptime.example.test/api/v1/heartbeat/abc/")
    assert heartbeat.ping("HEARTBEAT_URL") is True
    assert pings == ["https://uptime.example.test/api/v1/heartbeat/abc"]


def test_failed_ping_goes_to_the_fail_path(monkeypatch, pings):
    monkeypatch.setenv("BILLING_HEARTBEAT_URL", "https://uptime.example.test/api/v1/heartbeat/xyz")
    heartbeat.ping("BILLING_HEARTBEAT_URL", failed=True)
    assert pings == ["https://uptime.example.test/api/v1/heartbeat/xyz/fail"]


def test_blank_or_missing_url_sends_nothing(monkeypatch, pings):
    monkeypatch.setenv("HEARTBEAT_URL", "")
    monkeypatch.delenv("BILLING_HEARTBEAT_URL", raising=False)
    assert heartbeat.ping("HEARTBEAT_URL") is False
    assert heartbeat.ping("BILLING_HEARTBEAT_URL") is False
    assert pings == []


def test_ping_never_raises(monkeypatch):
    def boom(url, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(heartbeat.httpx, "get", boom)
    monkeypatch.setenv("HEARTBEAT_URL", "https://uptime.example.test/x")
    assert heartbeat.ping("HEARTBEAT_URL") is False


def _stub_cycle(monkeypatch, result=None, error=None):
    class _Session:
        def close(self):
            pass

    monkeypatch.setattr(cycle, "SessionLocal", lambda: _Session())

    def run(db, today, now=None):
        if error:
            raise error
        return result

    monkeypatch.setattr(cycle, "run_billing_cycle", run)


def test_billing_task_pings_green_on_a_clean_run(monkeypatch, pings):
    monkeypatch.setenv("BILLING_HEARTBEAT_URL", "https://uptime.example.test/b")
    _stub_cycle(monkeypatch, result={"errors": 0})
    assert cycle.billing_cycle() == {"errors": 0}
    assert pings == ["https://uptime.example.test/b"]


def test_billing_task_pings_fail_when_an_org_errored(monkeypatch, pings):
    monkeypatch.setenv("BILLING_HEARTBEAT_URL", "https://uptime.example.test/b")
    _stub_cycle(monkeypatch, result={"errors": 2})
    cycle.billing_cycle()
    assert pings == ["https://uptime.example.test/b/fail"]


def test_billing_task_pings_fail_and_reraises_on_a_crash(monkeypatch, pings):
    monkeypatch.setenv("BILLING_HEARTBEAT_URL", "https://uptime.example.test/b")
    _stub_cycle(monkeypatch, error=RuntimeError("db gone"))
    with pytest.raises(RuntimeError):
        cycle.billing_cycle()
    assert pings == ["https://uptime.example.test/b/fail"]


# --- logs heartbeat (poll_all_clients) -----------------------------------------------

@pytest.fixture
def poller(monkeypatch, session_factory):
    import workers.tasks.process_logs as pl

    dispatched: list[str] = []
    monkeypatch.setattr(pl, "SessionLocal", session_factory)
    monkeypatch.setattr(pl.process_logs, "delay", lambda org_id: dispatched.append(org_id))
    return pl, dispatched


def test_poller_pings_even_with_no_orgs(monkeypatch, pings, poller):
    pl, dispatched = poller
    monkeypatch.setenv("HEARTBEAT_URL", "https://uptime.example.test/logs")
    assert pl.poll_all_clients() == {"dispatched": 0}
    assert pings == ["https://uptime.example.test/logs"]


def test_poller_pings_after_dispatching(db, monkeypatch, pings, poller):
    pl, dispatched = poller
    monkeypatch.setenv("HEARTBEAT_URL", "https://uptime.example.test/logs")
    org = make_org(db, tier="basic", period="monthly", s3_bucket="b", log_format="alb")
    assert pl.poll_all_clients() == {"dispatched": 1}
    assert dispatched == [org.id]
    assert pings == ["https://uptime.example.test/logs"]


def test_poller_does_not_ping_when_the_database_fails(monkeypatch, pings, poller):
    pl, _ = poller

    def broken():
        raise RuntimeError("db gone")

    monkeypatch.setattr(pl, "SessionLocal", broken)
    monkeypatch.setenv("HEARTBEAT_URL", "https://uptime.example.test/logs")
    with pytest.raises(RuntimeError):
        pl.poll_all_clients()
    assert pings == []
