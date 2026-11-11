"""Phase 3: retention grace in the purge task, and pilot trial expiry.

  - purge_expired_data must use effective_retention_tier, so a downgraded org
    keeps its old tier's retention window until the 30 day grace ends.
  - trial_reminders' expiry branch must go through downgrade_org("trial_end"),
    so a pilot keeps Growth retention for 30 days and auto-block is switched off.
Both tasks are called directly with SessionLocal pointed at an in-memory
SQLite database.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from db.models import BillingEvent, Organization, Verdict
from api.tests.billing_testkit import capture_notifications, make_org
from workers.tasks import purge_expired_data as purge_module
from workers.tasks import trial_reminders as trial_module


@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    """No broker in tests: the pilot-ended notice is recorded instead."""
    return capture_notifications(monkeypatch)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _verdict(db, org, age_days: int, ip: str = "203.0.113.5") -> None:
    db.add(
        Verdict(
            org_id=org.id,
            timestamp=_now() - timedelta(days=age_days),
            ip=ip,
            severity="high",
            confidence=0.9,
        )
    )
    db.commit()


def _verdict_count(db, org) -> int:
    return db.query(Verdict).filter(Verdict.org_id == org.id).count()


# --- retention grace and the purge ----------------------------------------

def test_purge_keeps_the_old_tiers_window_while_the_grace_lasts(db, session_factory, monkeypatch):
    monkeypatch.setattr(purge_module, "SessionLocal", session_factory)
    in_grace = make_org(
        db, tier="starter", period=None, name="InGrace",
        retention_grace_tier="basic", retention_grace_until=_now() + timedelta(days=10),
    )
    grace_over = make_org(
        db, tier="starter", period=None, name="GraceOver",
        retention_grace_tier="basic", retention_grace_until=_now() - timedelta(days=1),
    )
    never_paid = make_org(db, tier="starter", period=None, name="NeverPaid")
    still_paying = make_org(db, tier="basic", name="StillPaying")
    for org in (in_grace, grace_over, never_paid, still_paying):
        _verdict(db, org, age_days=20)   # between free (7) and starter (30)

    purge_module.purge_expired_data()
    db.expire_all()

    assert _verdict_count(db, in_grace) == 1       # Starter's 30 days still applies
    assert _verdict_count(db, grace_over) == 0     # back to Free's 7 days
    assert _verdict_count(db, never_paid) == 0
    assert _verdict_count(db, still_paying) == 1


def test_purge_still_applies_the_grace_tiers_own_limit(db, session_factory, monkeypatch):
    monkeypatch.setattr(purge_module, "SessionLocal", session_factory)
    org = make_org(
        db, tier="starter", period=None,
        retention_grace_tier="basic", retention_grace_until=_now() + timedelta(days=10),
    )
    _verdict(db, org, age_days=40, ip="203.0.113.6")   # older than Starter's 30 days
    _verdict(db, org, age_days=20, ip="203.0.113.7")
    purge_module.purge_expired_data()
    db.expire_all()
    assert _verdict_count(db, org) == 1


def test_enterprise_grace_means_nothing_is_purged(db, session_factory, monkeypatch):
    monkeypatch.setattr(purge_module, "SessionLocal", session_factory)
    org = make_org(
        db, tier="starter", period=None,
        retention_grace_tier="enterprise", retention_grace_until=_now() + timedelta(days=5),
    )
    _verdict(db, org, age_days=400)
    purge_module.purge_expired_data()
    db.expire_all()
    assert _verdict_count(db, org) == 1


def test_purge_fails_closed_for_an_unrecognised_tier(db, session_factory, monkeypatch, caplog):
    monkeypatch.setattr(purge_module, "SessionLocal", session_factory)
    odd = make_org(db, tier="platinum", period=None, name="Odd")
    normal = make_org(db, tier="starter", period=None, name="Normal")
    _verdict(db, odd, age_days=400)
    _verdict(db, normal, age_days=400, ip="203.0.113.8")
    with caplog.at_level("ERROR", logger=purge_module.logger.name):
        purge_module.purge_expired_data()
    db.expire_all()
    assert _verdict_count(db, odd) == 1       # kept, not purged
    assert _verdict_count(db, normal) == 0    # the rest of the run still works
    assert any("unrecognised tier" in r.getMessage() and odd.id in r.getMessage() for r in caplog.records)


# --- pilot trial expiry ----------------------------------------------------

def test_expired_pilot_trial_goes_through_downgrade_org(db, session_factory, monkeypatch, notifications):
    monkeypatch.setattr(trial_module, "SessionLocal", session_factory)
    pilot = make_org(
        db, tier="growth", period=None, name="Pilot",
        billing_provider="pilot", trial_source="manual_outreach",
        trial_ends_at=_now() - timedelta(hours=1), auto_block_enabled=True,
    )
    pid = pilot.id

    result = trial_module.send_trial_reminders()
    db.expire_all()

    assert result["expired"] == 1
    org = db.get(Organization, pid)
    assert org.tier == "starter"
    assert org.retention_grace_tier == "growth"
    grace_left = org.retention_grace_until - _now()
    assert timedelta(days=29, hours=23) < grace_left <= timedelta(days=30)
    assert org.auto_block_enabled is False
    assert org.nonpayment_downgraded_at is None
    event = db.query(BillingEvent).filter(BillingEvent.org_id == pid).one()
    assert (event.event, event.from_tier, event.to_tier) == ("trial_end", "growth", "starter")
    assert notifications == [("pilot_ended", pid, None, None)]

    # A second run changes nothing and sends nothing more.
    trial_module.send_trial_reminders()
    assert len(notifications) == 1


def test_pilot_keeps_growth_retention_after_the_trial(db, session_factory, monkeypatch):
    monkeypatch.setattr(trial_module, "SessionLocal", session_factory)
    monkeypatch.setattr(purge_module, "SessionLocal", session_factory)
    pilot = make_org(
        db, tier="growth", period=None, name="Pilot",
        billing_provider="pilot", trial_source="manual_outreach",
        trial_ends_at=_now() - timedelta(hours=1),
    )
    _verdict(db, pilot, age_days=60)     # inside Growth's 90 days, outside Free's 7

    trial_module.send_trial_reminders()
    purge_module.purge_expired_data()
    db.expire_all()
    assert _verdict_count(db, pilot) == 1


def test_running_the_trial_task_twice_downgrades_once(db, session_factory, monkeypatch):
    monkeypatch.setattr(trial_module, "SessionLocal", session_factory)
    pilot = make_org(
        db, tier="growth", period=None, name="Pilot",
        billing_provider="pilot", trial_source="manual_outreach",
        trial_ends_at=_now() - timedelta(hours=1),
    )
    pid = pilot.id
    assert trial_module.send_trial_reminders()["expired"] == 1
    assert trial_module.send_trial_reminders()["expired"] == 0
    assert db.query(BillingEvent).filter(BillingEvent.org_id == pid).count() == 1


def _captured_reminder_email(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        trial_module, "_owner_emails", lambda db, org_id: ["owner@example.com"]
    )
    monkeypatch.setattr(
        "api.auth_utils.send_email",
        lambda **kwargs: sent.append(kwargs) or True,
    )
    return sent


def test_trial_reminder_links_to_checkout_for_a_supported_currency(db, session_factory, monkeypatch):
    monkeypatch.setattr(trial_module, "SessionLocal", session_factory)
    sent = _captured_reminder_email(monkeypatch)
    make_org(
        db, tier="growth", period=None, billing_provider="pilot", trial_source="manual_outreach",
        billing_currency="USD", trial_ends_at=_now() + timedelta(days=1, hours=1),
    )
    trial_module.send_trial_reminders()
    assert sent and all("/settings#billing" in m["body_text"] for m in sent)


def test_trial_reminder_routes_to_support_when_currency_has_no_checkout(db, session_factory, monkeypatch):
    monkeypatch.setattr(trial_module, "SessionLocal", session_factory)
    sent = _captured_reminder_email(monkeypatch)
    make_org(
        db, tier="growth", period=None, billing_provider="pilot", trial_source="manual_outreach",
        billing_currency="EUR", trial_ends_at=_now() + timedelta(days=1, hours=1),
    )
    trial_module.send_trial_reminders()
    assert sent
    for message in sent:
        assert "/settings#billing" not in message["body_text"]
        assert "support@clewsec.com" in message["body_text"]


def test_a_pilot_still_in_trial_is_untouched(db, session_factory, monkeypatch):
    monkeypatch.setattr(trial_module, "SessionLocal", session_factory)
    monkeypatch.setattr(trial_module, "send_trial_reminder_email", lambda *a, **k: None)
    pilot = make_org(
        db, tier="growth", period=None, name="Pilot",
        billing_provider="pilot", trial_source="manual_outreach",
        trial_ends_at=_now() + timedelta(days=20), auto_block_enabled=True,
    )
    pid = pilot.id
    assert trial_module.send_trial_reminders()["expired"] == 0
    db.expire_all()
    org = db.get(Organization, pid)
    assert org.tier == "growth"
    assert org.auto_block_enabled is True
    assert org.retention_grace_tier is None
