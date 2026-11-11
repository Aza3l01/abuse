"""Phase 12b: customer pause of scanning, CAPTCHA on login, resend-verification
and the newsletter form, and the optional signup source.

Routes run through the real app with the in-memory database from conftest. The
Turnstile verifier and the Redis counters are replaced, so nothing here needs a
network or a broker. The production limiter counts in Redis, so it is switched
off for these tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import api.routes.auth as auth_routes
import api.routes.newsletter as newsletter_routes
from api.auth_utils import hash_password
from api.deps import get_current_client
from api.limiter import limiter
from api.routes.clients import _to_org_config
from api.routes.org import SIGNUP_SOURCE_DETAIL_MAX, SIGNUP_SOURCES, create_organization
from api.staff_views import account_view, signup_sources_view
from api.tests.billing_testkit import make_org
from db.models import Client, Organization


@pytest.fixture(autouse=True)
def no_limiter(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)


def _client(db, email="owner@acme.test") -> Client:
    client = Client(email=email, password_hash=hash_password("pw-12345678"), full_name="Owner", email_verified=True)
    db.add(client)
    db.commit()
    return client


@pytest.fixture
def team(env, db):
    """An org plus the calling client, acting as owner."""
    org = make_org(db, tier="starter", s3_bucket="b", log_format="apigw")
    client = _client(db)
    from api.main import app

    app.dependency_overrides[get_current_client] = lambda: db.get(Client, client.id)
    env.act_as(org, "owner")
    return org, client


# ---------------------------------------------------------------------------
# Pause and resume routes

def _sqlite_date_trunc(db) -> None:
    """The summary's trend query uses Postgres date_trunc. With no verdict rows
    it only has to exist, so a stand-in is registered on the test connection."""
    db.connection().connection.create_function("date_trunc", 2, lambda unit, ts: ts)
# ---------------------------------------------------------------------------

def test_owner_can_pause_and_the_pause_records_who_and_when(env, db, team):
    org, client = team
    r = env.client.post("/org/scanning/pause")
    assert r.status_code == 200
    assert r.json()["scanning_paused_at"] is not None
    db.expire_all()
    assert org.scanning_paused_at is not None
    assert org.scanning_paused_by == client.id


def test_admin_can_pause_and_resume(env, db, team):
    org, _ = team
    env.act_as(org, "admin")
    assert env.client.post("/org/scanning/pause").status_code == 200
    assert env.client.post("/org/scanning/resume").status_code == 200


def test_viewer_cannot_pause_or_resume(env, db, team):
    org, _ = team
    env.act_as(org, "viewer")
    assert env.client.post("/org/scanning/pause").status_code == 403
    assert env.client.post("/org/scanning/resume").status_code == 403
    db.expire_all()
    assert org.scanning_paused_at is None


def test_pausing_twice_keeps_the_first_pause(env, db, team):
    org, _ = team
    first = env.client.post("/org/scanning/pause").json()["scanning_paused_at"]
    second = env.client.post("/org/scanning/pause").json()["scanning_paused_at"]
    assert first == second


def test_resume_clears_the_pause_and_records_the_resume_time(env, db, team):
    org, _ = team
    env.client.post("/org/scanning/pause")
    r = env.client.post("/org/scanning/resume")
    assert r.json()["scanning_paused_at"] is None
    db.expire_all()
    assert org.scanning_paused_at is None
    assert org.scanning_paused_by is None
    assert org.scanning_resumed_at is not None


def test_resuming_a_running_org_changes_nothing(env, db, team):
    org, _ = team
    assert env.client.post("/org/scanning/resume").status_code == 200
    db.expire_all()
    assert org.scanning_resumed_at is None


def test_pause_does_not_touch_billing_or_scan_state(env, db, team):
    org, _ = team
    org.monthly_requests_processed = 123
    org.last_scan_status = "success"
    org.last_processed_key = "logs/x"
    db.commit()
    env.client.post("/org/scanning/pause")
    db.expire_all()
    assert org.tier == "starter"
    assert org.monthly_requests_processed == 123
    assert org.last_scan_status == "success"
    assert org.last_processed_key == "logs/x"


def test_summary_and_org_config_expose_the_pause(env, db, team):
    org, _ = team
    _sqlite_date_trunc(db)
    assert env.client.get("/dashboard/summary").json()["scanning_paused_at"] is None
    env.client.post("/org/scanning/pause")
    assert env.client.get("/dashboard/summary").json()["scanning_paused_at"] is not None
    assert _to_org_config(org, "owner").scanning_paused_at is not None


def test_a_viewer_still_sees_the_pause_in_the_summary(env, db, team):
    org, _ = team
    _sqlite_date_trunc(db)
    env.client.post("/org/scanning/pause")
    env.act_as(org, "viewer")
    assert env.client.get("/dashboard/summary").json()["scanning_paused_at"] is not None


def test_staff_account_view_shows_who_paused(db, team):
    org, client = team
    org.scanning_paused_at = datetime.now(timezone.utc)
    org.scanning_paused_by = client.id
    db.commit()
    scan = account_view(db, org)["scan"]
    assert scan["scanning_paused_at"] is not None
    assert scan["scanning_paused_by_email"] == client.email


def test_staff_account_view_survives_a_purged_pauser(db, team):
    org, _ = team
    org.scanning_paused_at = datetime.now(timezone.utc)
    org.scanning_paused_by = None  # what ON DELETE SET NULL leaves behind
    db.commit()
    scan = account_view(db, org)["scan"]
    assert scan["scanning_paused_at"] is not None
    assert scan["scanning_paused_by_email"] is None


# ---------------------------------------------------------------------------
# CAPTCHA on login, resend-verification and the newsletter form
# ---------------------------------------------------------------------------

class Spy:
    def __init__(self, result=True):
        self.calls = []
        self.result = result

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


@pytest.fixture
def auth_spies(monkeypatch):
    spies = {
        "rate": Spy(True),
        "locked": Spy(False),
        "failure": Spy(None),
        "reset": Spy(None),
    }
    monkeypatch.setattr(auth_routes, "_check_email_rate", spies["rate"])
    monkeypatch.setattr(auth_routes, "_is_login_locked_out", spies["locked"])
    monkeypatch.setattr(auth_routes, "_record_login_failure", spies["failure"])
    monkeypatch.setattr(auth_routes, "_reset_login_failures", spies["reset"])
    return spies


def test_login_without_a_captcha_is_rejected_before_any_counter(env, db, auth_spies, monkeypatch):
    _client(db)
    monkeypatch.setattr(auth_routes, "verify_turnstile_token", lambda token, ip=None: False)
    r = env.client.post("/auth/login", json={"email": "owner@acme.test", "password": "pw-12345678"})
    assert r.status_code == 400
    assert "CAPTCHA" in r.json()["detail"]
    assert "script blocker" in r.json()["detail"]
    assert auth_spies["rate"].calls == []
    assert auth_spies["failure"].calls == []
    assert auth_spies["locked"].calls == []


def test_a_rejected_captcha_never_counts_as_a_failed_login(env, db, auth_spies, monkeypatch):
    _client(db)
    monkeypatch.setattr(auth_routes, "verify_turnstile_token", lambda token, ip=None: False)
    for _ in range(10):
        r = env.client.post(
            "/auth/login", json={"email": "owner@acme.test", "password": "wrong", "captcha_token": "bad"}
        )
        assert r.status_code == 400
    assert auth_spies["failure"].calls == []


def test_login_with_a_good_captcha_reaches_the_password_check(env, db, auth_spies, monkeypatch):
    _client(db)
    seen = []
    monkeypatch.setattr(auth_routes, "verify_turnstile_token", lambda token, ip=None: seen.append(token) or True)
    r = env.client.post(
        "/auth/login", json={"email": "owner@acme.test", "password": "wrong", "captcha_token": "good"}
    )
    assert r.status_code == 401
    assert seen == ["good"]
    assert len(auth_spies["failure"].calls) == 1


def test_resend_verification_needs_a_captcha_before_the_email_counter(env, db, auth_spies, monkeypatch):
    monkeypatch.setattr(auth_routes, "verify_turnstile_token", lambda token, ip=None: False)
    r = env.client.post("/auth/resend-verification", json={"email": "owner@acme.test"})
    assert r.status_code == 400
    assert auth_spies["rate"].calls == []


def test_resend_verification_with_a_captcha_still_answers_generically(env, db, auth_spies, monkeypatch):
    monkeypatch.setattr(auth_routes, "verify_turnstile_token", lambda token, ip=None: True)
    r = env.client.post("/auth/resend-verification", json={"email": "nobody@acme.test", "captcha_token": "ok"})
    assert r.status_code == 200
    assert len(auth_spies["rate"].calls) == 1


def test_mfa_login_has_no_captcha(env, db, monkeypatch):
    called = Spy(False)
    monkeypatch.setattr(auth_routes, "verify_turnstile_token", called)
    env.client.post("/auth/login/mfa", json={"mfa_token": "x", "code": "000000"})
    assert called.calls == []


@pytest.fixture
def newsletter(monkeypatch):
    sent = []
    monkeypatch.setenv("RESEND_SEGMENT_ID", "seg_test")
    monkeypatch.setattr(newsletter_routes.resend.Contacts, "get", lambda email: None)
    monkeypatch.setattr(newsletter_routes, "send_email", lambda **kw: sent.append(kw))
    return sent


def test_newsletter_without_a_captcha_is_rejected(env, newsletter, monkeypatch):
    monkeypatch.setattr(newsletter_routes, "verify_turnstile_token", lambda token, ip=None: False)
    r = env.client.post("/newsletter/subscribe", json={"email": "a@b.co"})
    assert r.status_code == 400
    assert newsletter == []


def test_newsletter_with_a_captcha_sends_the_confirmation(env, newsletter, monkeypatch):
    monkeypatch.setattr(newsletter_routes, "verify_turnstile_token", lambda token, ip=None: token == "ok")
    r = env.client.post("/newsletter/subscribe", json={"email": "a@b.co", "captcha_token": "ok"})
    assert r.status_code == 200
    assert len(newsletter) == 1


def test_newsletter_honeypot_is_answered_before_the_captcha(env, newsletter, monkeypatch):
    called = Spy(False)
    monkeypatch.setattr(newsletter_routes, "verify_turnstile_token", called)
    r = env.client.post("/newsletter/subscribe", json={"email": "a@b.co", "website": "http://spam"})
    assert r.status_code == 200
    assert called.calls == []
    assert newsletter == []


# ---------------------------------------------------------------------------
# Signup source
# ---------------------------------------------------------------------------

def test_every_fixed_source_is_stored(db):
    owner = _client(db)
    for i, source in enumerate(SIGNUP_SOURCES):
        org = create_organization(db, f"Co {i}", owner, signup_source=source)
        db.commit()
        assert org.signup_source == source


def test_no_source_is_stored_as_null(db):
    org = create_organization(db, "Co", _client(db))
    db.commit()
    assert org.signup_source is None
    assert org.signup_source_detail is None


def test_an_unknown_source_is_a_422(db):
    with pytest.raises(HTTPException) as exc:
        create_organization(db, "Co", _client(db), signup_source="a podcast")
    assert exc.value.status_code == 422


def test_other_keeps_a_trimmed_detail_capped_at_200(db):
    owner = _client(db)
    org = create_organization(db, "Co", owner, signup_source="other", signup_source_detail="  " + "x" * 500 + "  ")
    db.commit()
    assert org.signup_source_detail == "x" * SIGNUP_SOURCE_DETAIL_MAX


def test_a_blank_other_detail_is_not_stored(db):
    org = create_organization(db, "Co", _client(db), signup_source="other", signup_source_detail="   ")
    db.commit()
    assert org.signup_source == "other"
    assert org.signup_source_detail is None


def test_detail_is_dropped_for_every_source_but_other(db):
    org = create_organization(db, "Co", _client(db), signup_source="llm", signup_source_detail="ChatGPT")
    db.commit()
    assert org.signup_source == "llm"
    assert org.signup_source_detail is None


def test_register_route_stores_the_source(env, db, monkeypatch):
    monkeypatch.setattr(auth_routes, "verify_turnstile_token", lambda token, ip=None: True)
    monkeypatch.setattr(auth_routes, "send_verification_email", lambda *a, **k: None)
    r = env.client.post("/auth/register", json={
        "email": "new@acme.test", "password": "Str0ng-pass-123", "full_name": "N", "company_name": "NewCo",
        "captcha_token": "ok", "tos_accepted": True, "signup_source": "other", "signup_source_detail": "a friend's blog",
    })
    assert r.status_code == 201
    org = db.query(Organization).filter(Organization.company_name == "NewCo").one()
    assert org.signup_source == "other"
    assert org.signup_source_detail == "a friend's blog"


def test_register_route_rejects_an_unknown_source(env, db, monkeypatch):
    monkeypatch.setattr(auth_routes, "verify_turnstile_token", lambda token, ip=None: True)
    monkeypatch.setattr(auth_routes, "send_verification_email", lambda *a, **k: None)
    r = env.client.post("/auth/register", json={
        "email": "new2@acme.test", "password": "Str0ng-pass-123", "full_name": "N", "company_name": "NewCo2",
        "captcha_token": "ok", "tos_accepted": True, "signup_source": "bogus",
    })
    assert r.status_code == 422


def test_register_without_a_source_still_works(env, db, monkeypatch):
    monkeypatch.setattr(auth_routes, "verify_turnstile_token", lambda token, ip=None: True)
    monkeypatch.setattr(auth_routes, "send_verification_email", lambda *a, **k: None)
    r = env.client.post("/auth/register", json={
        "email": "new3@acme.test", "password": "Str0ng-pass-123", "full_name": "N", "company_name": "NewCo3",
        "captcha_token": "ok", "tos_accepted": True,
    })
    assert r.status_code == 201


# ---------------------------------------------------------------------------
# Ops: account view and the Metrics table
# ---------------------------------------------------------------------------

def test_account_view_shows_the_signup_answer(db):
    org = make_org(db, tier="starter", signup_source="other", signup_source_detail="a newsletter")
    org_view = account_view(db, org)["org"]
    assert org_view["signup_source"] == "other"
    assert org_view["signup_source_detail"] == "a newsletter"


def test_signup_table_counts_signups_and_payers_by_fixed_source(db):
    now = datetime.now(timezone.utc)
    make_org(db, name="A", tier="starter", signup_source="llm", created_at=now - timedelta(days=2))
    make_org(db, name="B", tier="basic", signup_source="llm", created_at=now - timedelta(days=3), first_charged_at=now)
    make_org(db, name="C", tier="starter", signup_source="search_engine", created_at=now - timedelta(days=1))
    make_org(db, name="D", tier="starter", created_at=now - timedelta(days=1))
    make_org(db, name="E", tier="starter", signup_source="llm", created_at=now - timedelta(days=45))
    view = signup_sources_view(db, now)
    rows = {r["source"]: r for r in view["rows"]}
    assert rows["llm"] == {"source": "llm", "signups": 2, "paid": 1}
    assert rows["search_engine"]["signups"] == 1
    assert rows["none"]["signups"] == 1
    assert rows["word_of_mouth"] == {"source": "word_of_mouth", "signups": 0, "paid": 0}
    assert [r["source"] for r in view["rows"][: len(SIGNUP_SOURCES)]] == list(SIGNUP_SOURCES)


def test_signup_table_keeps_free_text_out_of_the_counts(db):
    now = datetime.now(timezone.utc)
    make_org(db, name="A", signup_source="other", signup_source_detail="a podcast", created_at=now - timedelta(days=1))
    make_org(db, name="B", signup_source="other", signup_source_detail="a talk", created_at=now - timedelta(days=2))
    view = signup_sources_view(db, now)
    assert {r["source"] for r in view["rows"]} == {*SIGNUP_SOURCES, "none"}
    assert next(r for r in view["rows"] if r["source"] == "other")["signups"] == 2
    assert [a["detail"] for a in view["other_answers"]] == ["a podcast", "a talk"]
