"""Phase 11: server side PostHog events and error reports (api/analytics.py).

Covers the queue-until-commit behaviour, the disabled no-op, failure
isolation, the once-only Redis guard, and the two events fired from the
payment path (subscription_started, payment_captured).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import analytics
from api.correlation import CorrelationIdMiddleware
from api.tests.analytics_testkit import add_owner, install
from api.tests.billing_testkit import make_org
from api.tiers import plan_price


@pytest.fixture
def posthog(monkeypatch):
    fake, fake_redis = install(monkeypatch)
    fake.redis = fake_redis
    return fake


# --- queue, commit, rollback ---------------------------------------------------

def test_event_is_sent_only_after_commit(db, posthog):
    org = make_org(db)
    owner = add_owner(db, org)
    analytics.queue_org_event(db, org.id, "plan_cancelled", {"reason": "cancel"})
    assert posthog.events == []
    db.commit()
    [(name, distinct_id, props)] = posthog.events
    assert name == "plan_cancelled"
    assert distinct_id == owner
    assert props == {"org_id": org.id, "reason": "cancel"}


def test_event_is_dropped_on_rollback(db, posthog):
    org = make_org(db)
    add_owner(db, org)
    analytics.queue_org_event(db, org.id, "plan_cancelled", {"reason": "cancel"})
    db.rollback()
    db.commit()
    assert posthog.events == []


def test_each_queued_event_is_sent_once(db, posthog):
    org = make_org(db)
    add_owner(db, org)
    analytics.queue_org_event(db, org.id, "payment_captured")
    db.commit()
    db.commit()
    assert len(posthog.events) == 1


def test_only_the_owners_client_id_is_attached(db, posthog):
    org = make_org(db)
    owner = add_owner(db, org, email="private@example.test")
    analytics.queue_org_event(db, org.id, "payment_captured", {"amount": 10.0})
    db.commit()
    [(_, distinct_id, props)] = posthog.events
    assert distinct_id == owner
    assert "private@example.test" not in repr(posthog.events)
    assert "Owner Person" not in repr(posthog.events)
    assert "Acme" not in repr(posthog.events)
    assert set(props) == {"org_id", "amount"}


def test_org_without_an_owner_sends_nothing(db, posthog):
    org = make_org(db)
    analytics.queue_org_event(db, org.id, "payment_captured")
    db.commit()
    assert posthog.events == []


# --- disabled and failure isolation --------------------------------------------

def test_blank_key_is_a_complete_no_op(monkeypatch):
    fake, _ = install(monkeypatch, enabled=False)
    assert analytics.enabled() is False
    # db=None would raise if any query were attempted.
    analytics.queue_org_event(None, "org-1", "payment_captured")
    assert analytics.capture_org_event_once(None, "org-1", "org_activated", "k") is False
    analytics.capture("someone", "x")
    analytics.capture_exception(RuntimeError("x"))
    assert fake.events == [] and fake.errors == []


def test_posthog_outage_never_raises(db, posthog):
    org = make_org(db)
    add_owner(db, org)
    posthog.fail = True
    analytics.queue_org_event(db, org.id, "payment_captured")
    db.commit()
    analytics.capture_exception(RuntimeError("x"))
    assert analytics.capture_org_event_once(db, org.id, "org_activated", "k1") is True


def test_flush_calls_the_client(posthog):
    analytics.flush()
    assert posthog.flushes == 1


# --- once-only events -------------------------------------------------------------

def test_once_event_is_sent_one_time(db, posthog):
    org = make_org(db)
    owner = add_owner(db, org)
    assert analytics.capture_org_event_once(db, org.id, "org_activated", f"org_activated:{org.id}", {"records": 5})
    assert not analytics.capture_org_event_once(db, org.id, "org_activated", f"org_activated:{org.id}", {"records": 9})
    [(name, distinct_id, props)] = posthog.events
    assert (name, distinct_id, props) == ("org_activated", owner, {"org_id": org.id, "records": 5})


def test_once_event_fails_closed_when_redis_is_down(db, posthog):
    org = make_org(db)
    add_owner(db, org)
    posthog.redis.down = True
    assert analytics.capture_org_event_once(db, org.id, "org_activated", "k") is False
    assert posthog.events == []


# --- API error reports ---------------------------------------------------------------

def test_unhandled_api_error_is_reported_with_the_route_template(posthog):
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/verdicts/{verdict_id}")
    def boom(verdict_id: str):
        raise RuntimeError("kaboom")

    res = TestClient(app, raise_server_exceptions=False).get("/verdicts/secret-id-123")
    assert res.status_code == 500
    [(exc, props)] = posthog.errors
    assert str(exc) == "kaboom"
    assert props["route"] == "/verdicts/{verdict_id}"
    assert props["correlation_id"] == res.headers["x-correlation-id"]
    assert "secret-id-123" not in repr(props)


# --- payment path -----------------------------------------------------------------------

def _buy(env, tier="basic", period="monthly"):
    order = env.create_order(
        purpose="initial", tier=tier, period=period, accept_blocking_tos=True
    ).json()
    rz_id = env.rp.pay(order["order_id"])
    return order, rz_id, env.verify(order["order_id"], rz_id)


def test_first_payment_sends_subscription_started_and_payment_captured(env, db, posthog):
    org = env.act_as(make_org(db, tier="starter", period=None))
    owner = add_owner(db, org)
    _, _, resp = _buy(env)
    assert resp.status_code == 200

    [(_, distinct_id, props)] = posthog.named("subscription_started")
    assert distinct_id == owner
    assert props["tier"] == "basic"
    assert props["period"] == "monthly"
    assert props["amount"] == plan_price("INR", "basic", "monthly") / 100
    assert props["currency"] == "INR"
    assert props["first_payment"] is True
    assert props["restore"] is False

    [(_, distinct_id, props)] = posthog.named("payment_captured")
    assert distinct_id == owner
    assert props["purpose"] == "initial"


def test_replayed_payment_does_not_send_twice(env, db, posthog):
    org = env.act_as(make_org(db, tier="starter", period=None))
    add_owner(db, org)
    _, rz_id, _ = _buy(env)
    assert env.webhook(env.captured_event(rz_id)).status_code == 200
    assert len(posthog.named("subscription_started")) == 1
    assert len(posthog.named("payment_captured")) == 1


def test_failed_verification_sends_nothing(env, db, posthog):
    org = env.act_as(make_org(db, tier="starter", period=None))
    add_owner(db, org)
    order = env.create_order(purpose="initial", tier="basic", period="monthly", accept_blocking_tos=True).json()
    rz_id = env.rp.pay(order["order_id"])
    assert env.verify(order["order_id"], rz_id, signature="0" * 64).status_code == 400
    assert posthog.events == []
