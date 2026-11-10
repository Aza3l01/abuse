"""Phase 6 internal ops panel: staff auth, isolation from customer auth, audit,
raw-data gating, account actions and system health.

Every request carries the staff session as an explicit Cookie header, and the
Redis behind the login rate limits is an in-memory fake, so nothing here needs
a network.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
import redis as redis_lib
from fastapi.testclient import TestClient

import api.staff_auth as staff_auth
import api.staff_views as staff_views
from api.auth_utils import create_access_token, encrypt_secret, hash_password
from api.billing_rules import add_months, ist_date, restore_amount_paise, today_ist
from api.deps import get_db
from api.metrics import CSV_HEADER
from api.staff_auth import create_staff_token, require_staff
from api.tests.billing_testkit import make_org
from api.tests.conftest import make_bill
from db.models import (
    Bill,
    Client,
    IpMemory,
    Organization,
    OrganizationMember,
    Payment,
    PromoCode,
    StaffAuditLog,
    StaffUser,
    Verdict,
)

PASSWORD = "correct horse battery staple"
TOTP_SECRET = pyotp.random_base32()
SECRETS = ("CF-SECRET-123", "EXT-SECRET-456", "ClewSecretRole", "MFA-SECRET-000", "HASH-SECRET-789")
LONG_REASON = "Customer paid by bank transfer, ticket 42"


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, int] = {}

    def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    def expire(self, key, seconds):
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(staff_auth, "_redis", fake)
    return fake


def make_staff(db, email="ops@clew.test", **extra) -> StaffUser:
    staff = StaffUser(**{
        "email": email,
        "password_hash": hash_password(PASSWORD),
        "totp_secret": encrypt_secret(TOTP_SECRET),
        "totp_active": True,
        "is_active": True,
        **extra,
    })
    db.add(staff)
    db.commit()
    return staff


class Panel:
    """The test client acting as one staff user (session cookie sent per call)."""

    def __init__(self, env, staff: StaffUser) -> None:
        self.env = env
        self.staff = staff

    def _headers(self) -> dict:
        return {"Cookie": f"clew_staff={create_staff_token(self.staff.id)}"}

    def get(self, path: str, **kw):
        return self.env.client.get(path, headers=self._headers(), **kw)

    def post(self, path: str, body: dict):
        return self.env.client.post(path, json=body, headers=self._headers())

    def audit(self, action: str) -> list[StaffAuditLog]:
        self.env.db.expire_all()
        return self.env.db.query(StaffAuditLog).filter(StaffAuditLog.action == action).all()


@pytest.fixture
def panel(env, fake_redis, db):
    return Panel(env, make_staff(db))


@pytest.fixture
def bare(db):
    """The real app with only the DB overridden: no customer auth override."""
    from api.main import app

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def login(client, *, email="ops@clew.test", password=PASSWORD, code=None):
    return client.post("/internal/auth/login", json={
        "email": email, "password": password, "code": pyotp.TOTP(TOTP_SECRET).now() if code is None else code,
    })


def seed_account(db) -> Organization:
    org = make_org(
        db, tier="basic", period="monthly", name="Acme Corp",
        next_bill=today_ist() + timedelta(days=10),
        first_charged_at=datetime.now(timezone.utc),
        cloudflare_token="CF-SECRET-123", aws_external_id="EXT-SECRET-456",
        aws_role_arn="arn:aws:iam::123456789012:role/ClewSecretRole",
    )
    owner = Client(
        email="owner@acme.test", full_name="Owner", email_verified=True,
        password_hash="HASH-SECRET-789", mfa_secret="MFA-SECRET-000",
    )
    db.add(owner)
    db.flush()
    db.add(OrganizationMember(client_id=owner.id, org_id=org.id, role="owner"))
    db.commit()
    return org


# --- login ------------------------------------------------------------------

def test_login_sets_a_strict_httponly_cookie_and_audits(env, fake_redis, db):
    make_staff(db)
    r = login(env.client)
    assert r.status_code == 200 and r.json() == {"email": "ops@clew.test"}
    cookie = r.headers["set-cookie"].lower()
    assert "clew_staff=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "domain=" not in cookie
    db.expire_all()
    assert len(db.query(StaffAuditLog).filter_by(action="staff_login").all()) == 1
    assert db.query(StaffUser).one().last_totp_step is not None


def test_login_failures_look_identical_and_unknown_emails_leave_no_audit_row(env, fake_redis, db):
    make_staff(db)
    wrong_code = login(env.client, code="000000")
    wrong_password = login(env.client, password="nope")
    unknown = login(env.client, email="nobody@clew.test")
    assert {wrong_code.status_code, wrong_password.status_code, unknown.status_code} == {401}
    assert wrong_code.json() == wrong_password.json() == unknown.json()
    db.expire_all()
    failed = db.query(StaffAuditLog).filter_by(action="staff_login_failed").all()
    assert len(failed) == 2 and all(row.staff_email == "ops@clew.test" for row in failed)


def test_a_totp_code_cannot_be_used_twice(env, fake_redis, db):
    make_staff(db)
    code = pyotp.TOTP(TOTP_SECRET).now()
    assert login(env.client, code=code).status_code == 200
    assert login(env.client, code=code).status_code == 401


def test_totp_is_required(env, fake_redis, db):
    make_staff(db)
    assert login(env.client, code="").status_code == 401
    assert login(env.client, code="12345").status_code == 401


def test_enrolment_not_finished_cannot_log_in(env, fake_redis, db):
    staff = make_staff(db, totp_active=False)
    assert login(env.client).status_code == 401
    assert Panel(env, staff).get("/internal/auth/me").status_code == 401


def test_inactive_staff_cannot_log_in_or_use_a_live_session(env, fake_redis, db):
    staff = make_staff(db)
    assert Panel(env, staff).get("/internal/auth/me").status_code == 200
    staff.is_active = False
    db.commit()
    assert Panel(env, staff).get("/internal/auth/me").status_code == 401
    assert login(env.client).status_code == 401


def test_five_failures_lock_the_email_even_for_the_right_code(env, fake_redis, db):
    make_staff(db)
    for _ in range(5):
        assert login(env.client, code="000000").status_code == 401
    assert login(env.client).status_code == 429


def test_ip_rate_limit(env, fake_redis, db):
    for i in range(10):
        assert login(env.client, email=f"nobody{i}@clew.test").status_code == 401
    assert login(env.client, email="nobody99@clew.test").status_code == 429


def test_login_fails_closed_when_redis_is_down(env, monkeypatch, db):
    make_staff(db)

    class Down:
        def incr(self, key):
            raise redis_lib.exceptions.ConnectionError("down")

    monkeypatch.setattr(staff_auth, "_redis", Down())
    assert login(env.client).status_code == 503


def test_logout_is_audited(panel):
    assert panel.post("/internal/auth/logout", {}).status_code == 200
    assert len(panel.audit("staff_logout")) == 1


# --- isolation from customer auth --------------------------------------------

def test_no_session_is_refused(env, fake_redis):
    for path in ("/internal/auth/me", "/internal/health", "/internal/metrics", "/internal/audit"):
        assert env.client.get(path).status_code == 401, path


def test_a_customer_token_does_not_open_the_panel(env, fake_redis, db):
    make_staff(db)
    customer = create_access_token("00000000-0000-0000-0000-000000000001")
    for cookie in (f"clew_staff={customer}", f"access_token={customer}"):
        r = env.client.get("/internal/auth/me", headers={"Cookie": cookie})
        assert r.status_code == 401, cookie


def test_a_staff_token_does_not_open_customer_routes(bare, db):
    staff = make_staff(db)
    token = create_staff_token(staff.id)
    for path in ("/billing/status", "/billing/banner"):
        assert bare.get(path, headers={"Cookie": f"access_token={token}"}).status_code == 401, path
        assert bare.get(path, headers={"Cookie": f"clew_staff={token}"}).status_code == 401, path


def test_staff_rows_are_created_only_by_the_cli():
    from api.main import app

    posts = sorted(
        route.path for route in app.routes
        if route.path.startswith("/internal") and "POST" in getattr(route, "methods", ())
    )
    assert posts == sorted([
        "/internal/auth/login", "/internal/auth/logout", "/internal/orgs/{org_id}/raw",
        "/internal/orgs/{org_id}/bills/mark-paid", "/internal/orgs/{org_id}/bills/void",
        "/internal/orgs/{org_id}/extend-period", "/internal/orgs/{org_id}/pause-downgrade",
        "/internal/orgs/{org_id}/reinstate", "/internal/orgs/{org_id}/extend-pilot",
        "/internal/pilot-codes",
        "/internal/referrals/credits/{credit_id}/revoke", "/internal/referrals/credits/{credit_id}/approve",
    ])


def test_every_internal_route_but_login_and_logout_requires_staff():
    from api.main import app

    open_routes = {"/internal/auth/login", "/internal/auth/logout"}
    for route in app.routes:
        if not route.path.startswith("/internal") or route.path in open_routes:
            continue
        assert any(dep.call is require_staff for dep in route.dependant.dependencies), route.path


# --- lookup and raw data ------------------------------------------------------

def test_search_finds_by_email_name_and_id_and_escapes_wildcards(panel, db):
    org = seed_account(db)
    for q in ("owner@acme", "acme corp", org.id):
        found = panel.get("/internal/orgs/search", params={"q": q}).json()["results"]
        assert [r["id"] for r in found] == [org.id], q
    assert panel.get("/internal/orgs/search", params={"q": "%%"}).json()["results"] == []
    assert panel.get("/internal/orgs/search", params={"q": "a"}).status_code == 422


def test_lookup_shows_the_orgs_bills_and_never_a_secret_or_raw_customer_data(panel, db):
    org = seed_account(db)
    open_bill = make_bill(db, org)
    old_bill = make_bill(db, org, status="paid", start=today_ist() - timedelta(days=60))
    db.add(Verdict(org_id=org.id, timestamp=datetime.now(timezone.utc), ip="203.0.113.9",
                   endpoint="/secret-admin-path", severity="high", confidence=0.9))
    db.commit()

    r = panel.get(f"/internal/orgs/{org.id}")
    assert r.status_code == 200
    body = r.json()
    assert {b["id"]: b["status"] for b in body["bills"]} == {open_bill.id: "open", old_bill.id: "paid"}
    assert body["org"]["has_aws_role"] is True and body["org"]["has_cloudflare_token"] is True
    assert body["usage"]["verdict_count"] == 1
    for secret in SECRETS + ("203.0.113.9", "/secret-admin-path"):
        assert secret not in r.text, secret
    search = panel.get("/internal/orgs/search", params={"q": "acme"})
    for secret in SECRETS:
        assert secret not in search.text


def test_unknown_or_malformed_org_ids_are_404(panel):
    assert panel.get("/internal/orgs/not-a-uuid").status_code == 404
    assert panel.get("/internal/orgs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_raw_data_needs_a_real_reason_and_is_logged(panel, db):
    org = seed_account(db)
    db.add(Verdict(org_id=org.id, timestamp=datetime.now(timezone.utc), ip="203.0.113.9",
                   endpoint="/x", severity="high", confidence=0.9))
    db.add(IpMemory(org_id=org.id, ip="198.51.100.7", first_seen=datetime.now(timezone.utc),
                    last_seen=datetime.now(timezone.utc)))
    db.commit()
    url = f"/internal/orgs/{org.id}/raw"

    for reason in ("", "short"):
        r = panel.post(url, {"kind": "verdicts", "reason": reason})
        assert r.status_code == 400 and "203.0.113.9" not in r.text
    assert panel.audit("raw_view") == []

    ok = panel.post(url, {"kind": "verdicts", "reason": "Customer asked why 203.0.113.9 was blocked"})
    assert ok.status_code == 200 and ok.json()["rows"][0]["ip"] == "203.0.113.9"
    ips = panel.post(url, {"kind": "ips", "reason": "Checking the memory of one address"})
    assert ips.json()["rows"][0]["ip"] == "198.51.100.7"
    rows = panel.audit("raw_view")
    assert len(rows) == 2
    assert rows[0].org_id == org.id and rows[0].reason and rows[0].staff_email == "ops@clew.test"
    for secret in SECRETS:
        assert secret not in ok.text + ips.text
    assert panel.post(url, {"kind": "nope", "reason": LONG_REASON}).status_code == 400


# --- account actions ----------------------------------------------------------

def test_mark_paid_closes_the_bill_for_the_customer_and_is_audited(panel, env, db):
    org = env.act_as(seed_account(db))
    bill = make_bill(db, org)
    r = panel.post(f"/internal/orgs/{org.id}/bills/mark-paid",
                   {"bill_id": bill.id, "reference": "NEFT-7788", "reason": LONG_REASON})
    assert r.status_code == 200, r.text
    payment_id = r.json()["payment_id"]

    status = env.client.get("/billing/status").json()
    assert status["open_bills"] == []
    assert [p["id"] for p in status["payments"] if p["id"] == payment_id] == [payment_id]
    assert env.client.get("/billing/banner").json()["open_bills"] == []
    assert env.client.get(f"/billing/payments/{payment_id}").status_code == 200

    detail = panel.get(f"/internal/orgs/{org.id}").json()
    assert detail["bills"][0]["status"] == "paid"
    manual = [p for p in detail["payments"] if p["id"] == payment_id][0]
    assert manual["manual"] is True and manual["reference"] == "NEFT-7788"

    [row] = panel.audit("bill_mark_paid")
    assert row.org_id == org.id and row.reason == LONG_REASON
    assert row.details["reference"] == "NEFT-7788" and row.details["bill_id"] == bill.id


def test_mark_paid_refusals_change_nothing(panel, db):
    org = seed_account(db)
    bill = make_bill(db, org)
    url = f"/internal/orgs/{org.id}/bills/mark-paid"
    assert panel.post(url, {"bill_id": bill.id, "reference": "R", "reason": "short"}).status_code == 400
    assert panel.post(url, {"bill_id": bill.id, "reference": "", "reason": LONG_REASON}).status_code == 422
    assert panel.post(url, {"bill_id": "nope", "reference": "R", "reason": LONG_REASON}).status_code == 404
    other = seed_other_org(db)
    foreign = make_bill(db, other)
    assert panel.post(url, {"bill_id": foreign.id, "reference": "R", "reason": LONG_REASON}).status_code == 404
    usd = make_bill(db, org, currency="USD", start=today_ist() - timedelta(days=40))
    assert panel.post(url, {"bill_id": usd.id, "reference": "R", "reason": LONG_REASON}).status_code == 409
    db.expire_all()
    assert db.get(Bill, bill.id).status == "open"
    assert db.query(Payment).count() == 0
    assert panel.audit("bill_mark_paid") == []


def seed_other_org(db) -> Organization:
    return make_org(db, tier="basic", period="monthly", name="Other Co")


def test_marking_a_bill_paid_twice_is_refused(panel, db):
    org = seed_account(db)
    bill = make_bill(db, org)
    url = f"/internal/orgs/{org.id}/bills/mark-paid"
    body = {"bill_id": bill.id, "reference": "R1", "reason": LONG_REASON}
    assert panel.post(url, body).status_code == 200
    assert panel.post(url, body).status_code == 409
    assert db.query(Payment).count() == 1


def test_void_bill(panel, env, db):
    org = env.act_as(seed_account(db))
    bill = make_bill(db, org)
    r = panel.post(f"/internal/orgs/{org.id}/bills/void", {"bill_id": bill.id, "reason": LONG_REASON})
    assert r.status_code == 200
    assert env.client.get("/billing/banner").json()["open_bills"] == []
    assert len(panel.audit("bill_void")) == 1
    assert panel.post(f"/internal/orgs/{org.id}/bills/void",
                      {"bill_id": bill.id, "reason": LONG_REASON}).status_code == 409


def test_extend_period_moves_the_next_bill_date_for_the_customer(panel, env, db):
    org = env.act_as(seed_account(db))
    before = ist_date(org.next_billing_date)
    r = panel.post(f"/internal/orgs/{org.id}/extend-period", {"months": 2, "reason": LONG_REASON})
    assert r.status_code == 200, r.text
    after = add_months(before, 2)
    assert r.json()["next_billing_date_after"] == after.isoformat()
    shown = env.client.get("/billing/status").json()["next_billing_date"]
    assert ist_date(datetime.fromisoformat(shown)) == after
    [row] = panel.audit("period_extend")
    assert row.details["months"] == 2


def test_extend_period_refusals(panel, db):
    org = seed_account(db)
    url = f"/internal/orgs/{org.id}/extend-period"
    assert panel.post(url, {"months": 0, "reason": LONG_REASON}).status_code == 400
    assert panel.post(url, {"months": 13, "reason": LONG_REASON}).status_code == 400
    make_bill(db, org)
    assert panel.post(url, {"months": 1, "reason": LONG_REASON}).status_code == 409
    free = make_org(db, tier="starter", period=None, name="Free Co")
    assert panel.post(f"/internal/orgs/{free.id}/extend-period",
                      {"months": 1, "reason": LONG_REASON}).status_code == 409
    assert panel.audit("period_extend") == []


def test_pause_downgrade_moves_the_cancel_date(panel, db):
    org = seed_account(db)
    bill = make_bill(db, org)
    before = bill.cancel_on
    r = panel.post(f"/internal/orgs/{org.id}/pause-downgrade", {"days": 14, "reason": LONG_REASON})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Bill, bill.id).cancel_on == before + timedelta(days=14)
    assert len(panel.audit("downgrade_pause")) == 1


def test_pause_downgrade_refusals(panel, db):
    org = seed_account(db)
    url = f"/internal/orgs/{org.id}/pause-downgrade"
    assert panel.post(url, {"days": 14, "reason": LONG_REASON}).status_code == 409  # no open bill
    make_bill(db, org)
    assert panel.post(url, {"days": 31, "reason": LONG_REASON}).status_code == 400
    assert panel.post(url, {"days": 0, "reason": LONG_REASON}).status_code == 400


def test_reinstate_restores_a_nonpayment_downgrade(panel, env, db):
    org = env.act_as(make_org(
        db, tier="starter", period=None, name="Late Co",
        nonpayment_downgraded_at=datetime.now(timezone.utc) - timedelta(days=3),
        blocking_tos_accepted_at=datetime.now(timezone.utc) - timedelta(days=90),
        retention_grace_tier="growth",
        retention_grace_until=datetime.now(timezone.utc) + timedelta(days=27),
    ))
    bill = make_bill(db, org, tier="growth", amount=499_900)
    expected = restore_amount_paise([bill], "basic", "monthly", currency="INR")
    r = panel.post(f"/internal/orgs/{org.id}/reinstate",
                   {"tier": "basic", "period": "monthly", "reference": "NEFT-1", "reason": LONG_REASON})
    assert r.status_code == 200, r.text
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.tier, org.billing_period) == ("basic", "monthly")
    assert org.nonpayment_downgraded_at is None and org.retention_grace_until is None
    assert db.get(Bill, bill.id).status == "paid"
    assert db.get(Payment, r.json()["payment_id"]).amount_paise == expected
    assert env.client.get("/billing/banner").json()["tier"] == "basic"
    [row] = panel.audit("org_reinstate")
    assert row.details["amount_minor"] == expected


def test_reinstate_refused_for_an_org_not_downgraded_for_nonpayment(panel, db):
    org = seed_account(db)
    r = panel.post(f"/internal/orgs/{org.id}/reinstate",
                   {"tier": "basic", "period": "monthly", "reference": "R", "reason": LONG_REASON})
    assert r.status_code in (400, 403, 409)
    assert db.query(Payment).count() == 0
    assert panel.audit("org_reinstate") == []


def test_extend_pilot(panel, db):
    now = datetime.now(timezone.utc)
    org = make_org(db, tier="growth", period=None, name="Pilot Co", billing_provider="pilot",
                   trial_ends_at=now + timedelta(days=2), trial_reminder_5d_sent=True,
                   trial_reminder_2d_sent=True)
    r = panel.post(f"/internal/orgs/{org.id}/extend-pilot", {"days": 14, "reason": LONG_REASON})
    assert r.status_code == 200, r.text
    db.expire_all()
    org = db.get(Organization, org.id)
    assert abs((org.trial_ends_at - (now + timedelta(days=16))).total_seconds()) < 60
    assert org.trial_reminder_5d_sent is False and org.trial_reminder_2d_sent is False
    assert len(panel.audit("pilot_extend")) == 1


def test_extend_pilot_reactivates_an_expired_pilot(panel, db):
    now = datetime.now(timezone.utc)
    org = make_org(db, tier="starter", period=None, name="Gone Pilot", billing_provider="pilot",
                   trial_ends_at=now - timedelta(days=5))
    r = panel.post(f"/internal/orgs/{org.id}/extend-pilot", {"days": 14, "reason": LONG_REASON})
    assert r.status_code == 200 and r.json()["reactivated"] is True
    db.expire_all()
    org = db.get(Organization, org.id)
    assert org.tier == "growth"
    assert abs((org.trial_ends_at - (now + timedelta(days=14))).total_seconds()) < 60


def test_extend_pilot_refusals(panel, db):
    paid = seed_account(db)
    assert panel.post(f"/internal/orgs/{paid.id}/extend-pilot",
                      {"days": 7, "reason": LONG_REASON}).status_code == 409
    pilot = make_org(db, tier="growth", period=None, name="P2", billing_provider="pilot",
                     trial_ends_at=datetime.now(timezone.utc) + timedelta(days=1))
    for days in (0, 91):
        assert panel.post(f"/internal/orgs/{pilot.id}/extend-pilot",
                          {"days": days, "reason": LONG_REASON}).status_code == 400


def test_pilot_codes(panel, db):
    r = panel.post("/internal/pilot-codes", {"count": 3, "reason": LONG_REASON})
    assert r.status_code == 200
    codes = r.json()["codes"]
    assert len(set(codes)) == 3 and all(re.fullmatch(r"CLEW-[2-9A-HJ-NP-Z]{5}", c) for c in codes)
    rows = db.query(PromoCode).filter(PromoCode.code.in_(codes)).all()
    assert len(rows) == 3 and all(p.kind == "admin" and p.max_redemptions == 1 for p in rows)
    assert panel.post("/internal/pilot-codes", {"count": 51, "reason": LONG_REASON}).status_code == 400
    assert panel.post("/internal/pilot-codes", {"count": 0, "reason": LONG_REASON}).status_code == 400
    assert panel.post("/internal/pilot-codes", {"count": 2, "reason": "short"}).status_code == 400
    [row] = panel.audit("pilot_codes_generate")
    assert row.details["count"] == 3 and row.org_id is None


# --- referrals (Phase 12) -------------------------------------------------------

def _referral_credit(db, org, status="available", amount=199_900, source=None):
    from db.models import Credit

    credit = Credit(
        org_id=org.id, kind="referrer_reward", status=status, amount_paise=amount, currency="INR",
        basis_tier="basic", basis_period="monthly", source_org_id=source.id if source else None,
        earned_at=datetime.now(timezone.utc),
    )
    db.add(credit)
    db.commit()
    return credit


def test_staff_can_revoke_an_unused_credit_with_a_reason_and_an_audit_row(panel, db):
    org = seed_account(db)
    credit = _referral_credit(db, org, "pending")
    url = f"/internal/referrals/credits/{credit.id}/revoke"
    assert panel.post(url, {"reason": "short"}).status_code == 400
    assert panel.post(url, {"reason": LONG_REASON}).status_code == 200
    db.expire_all()
    db.refresh(credit)
    assert credit.status == "revoked" and credit.revoked_reason == LONG_REASON
    [row] = panel.audit("referral_credit_revoke")
    assert row.org_id == org.id and row.details["credit_id"] == credit.id
    assert panel.post(url, {"reason": LONG_REASON}).status_code == 409  # already revoked


def test_staff_cannot_revoke_an_applied_credit_or_find_a_missing_one(panel, db):
    org = seed_account(db)
    credit = _referral_credit(db, org, "applied")
    assert panel.post(f"/internal/referrals/credits/{credit.id}/revoke", {"reason": LONG_REASON}).status_code == 409
    for bad in ("00000000-0000-0000-0000-000000000000", "not-a-uuid"):
        assert panel.post(f"/internal/referrals/credits/{bad}/revoke", {"reason": LONG_REASON}).status_code == 404
    assert panel.audit("referral_credit_revoke") == []


def test_approve_releases_only_a_held_credit(panel, db):
    org = seed_account(db)
    held = _referral_credit(db, org, "held")
    pending = _referral_credit(db, org, "pending")
    assert panel.post(f"/internal/referrals/credits/{pending.id}/approve", {"reason": LONG_REASON}).status_code == 409
    assert panel.post(f"/internal/referrals/credits/{held.id}/approve", {"reason": LONG_REASON}).status_code == 200
    db.expire_all()
    db.refresh(held)
    assert held.status == "available" and held.vests_at is not None
    assert len(panel.audit("referral_credit_approve")) == 1


def test_referral_overview_lists_referrers_edges_and_held_credits(panel, db):
    from db.models import PromoCodeRedemption

    referrer = seed_account(db)
    code = PromoCode(code="REF-STAFF", kind="referral", owner_org_id=referrer.id, max_redemptions=0)
    db.add(code)
    db.commit()
    referee = make_org(db, tier="starter", period=None, name="Referee Co", referred_by_promo_code_id=code.id)
    db.add(PromoCodeRedemption(promo_code_id=code.id, redeemed_by_org_id=referee.id,
                               redeemed_at=datetime.now(timezone.utc)))
    db.commit()
    _referral_credit(db, referrer, "held", source=referee)

    body = panel.get("/internal/referrals").json()
    [row] = body["referrers"]
    assert (row["org_id"], row["code"], row["signups"], row["paying"], row["held"]) == (referrer.id, "REF-STAFF", 1, 0, 1)
    [edge] = body["edges"]
    assert edge["referee_org_id"] == referee.id and edge["referrer_org_id"] == referrer.id
    assert edge["free_bill_applied"] is False
    assert [c["status"] for c in body["held"]] == ["held"]
    assert body["held"][0]["source_org_name"] == "Referee Co"


def test_account_view_carries_credits_and_the_credit_applied_on_bills(panel, db):
    org = seed_account(db)
    _referral_credit(db, org, "available")
    bill = make_bill(db, org)
    bill.credit_applied_paise = 5_000
    db.commit()
    body = panel.get(f"/internal/orgs/{org.id}").json()
    assert [c["status"] for c in body["credits"]] == ["available"]
    assert body["bills"][0]["credit_applied_paise"] == 5_000
    assert body["referral"]["credit_available_inr_minor"] == 199_900


def test_writes_to_a_deleted_account_are_refused(panel, db):
    org = make_org(db, tier="basic", period="monthly", name="Gone Co",
                   deleted_at=datetime.now(timezone.utc))
    bill = make_bill(db, org)
    r = panel.post(f"/internal/orgs/{org.id}/bills/mark-paid",
                   {"bill_id": bill.id, "reference": "R", "reason": LONG_REASON})
    assert r.status_code == 409
    assert panel.audit("bill_mark_paid") == []


def test_audit_endpoint_lists_actions_newest_first(panel, db):
    org = seed_account(db)
    panel.post(f"/internal/orgs/{org.id}/raw", {"kind": "ips", "reason": LONG_REASON})
    panel.post("/internal/pilot-codes", {"count": 1, "reason": LONG_REASON})
    rows = panel.get("/internal/audit").json()["rows"]
    assert {"raw_view", "pilot_codes_generate"} <= {r["action"] for r in rows}
    assert all(r["staff_email"] == "ops@clew.test" and r["ip"] for r in rows)


# --- system health -------------------------------------------------------------

def test_health_lists_every_expected_task_and_flags_stuck_and_failed_payments(panel, db, monkeypatch):
    monkeypatch.setattr(staff_views, "read_runs", lambda: {})
    monkeypatch.setattr(staff_views, "read_reconciliation", lambda: None)
    org = seed_account(db)
    now = datetime.now(timezone.utc)

    def payment(order_id, status, created):
        db.add(Payment(
            org_id=org.id, org_name_snapshot=org.company_name, razorpay_order_id=order_id,
            amount_paise=199_900, currency="INR", purpose="plan", status=status,
            line_items={}, tos_accepted=False, created_at=created,
        ))

    payment("order_stuck", "created", now - timedelta(hours=5))
    payment("order_fresh", "created", now - timedelta(minutes=5))
    payment("order_failed", "failed", now - timedelta(hours=1))
    db.commit()

    body = panel.get("/internal/health").json()
    assert [t["name"] for t in body["tasks"]] == list(staff_views.EXPECTED_TASKS)
    assert body["task_runs_recorded"] is False
    assert [p["razorpay_order_id"] for p in body["stuck_payments"]] == ["order_stuck"]
    assert [p["razorpay_order_id"] for p in body["failed_payments"]] == ["order_failed"]


# --- metrics routes ---------------------------------------------------------------

def test_metrics_json_has_a_row_per_currency(panel, db):
    make_org(db, tier="basic", period="monthly", name="Payer", first_charged_at=datetime.now(timezone.utc))
    body = panel.get("/internal/metrics").json()
    assert [r["currency"] for r in body["current"]] == ["USD", "INR"]
    inr = body["current"][1]
    assert inr["mrr_minor"] == 199_900 and inr["paying_orgs"] == 1
    assert body["current"][0]["mrr_minor"] == 0


def test_csv_export_parses_and_is_audited(panel, db):
    make_org(db, tier="basic", period="monthly", name="Payer", first_charged_at=datetime.now(timezone.utc))
    r = panel.get("/internal/metrics/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == list(CSV_HEADER)
    assert all(len(row) == len(CSV_HEADER) for row in rows)
    inr = [row for row in rows[1:] if row[1] == "INR"][-1]
    assert inr[CSV_HEADER.index("mrr_minor")] == "1999.00"
    assert len(panel.audit("metrics_export")) == 1


def test_metrics_json_has_a_combined_block(panel, db, monkeypatch):
    monkeypatch.setenv("METRICS_INR_PER_USD", "88")
    now = datetime.now(timezone.utc)
    make_org(db, tier="basic", period="monthly", name="Payer", first_charged_at=now)
    make_org(
        db, tier="basic", period="monthly", name="UsdPayer", first_charged_at=now,
        billing_currency="USD", billing_country="US",
    )
    make_org(
        db, tier="growth", period=None, name="Pilot", billing_provider="pilot",
        pilot_code_used="CLEW-PPPPP", trial_ends_at=now + timedelta(days=10),
    )
    body = panel.get("/internal/metrics").json()
    assert body["headline_currency"] == "INR" and body["rate"] == "88"
    usd, inr = body["current"]
    assert usd["mrr_minor"] == 4_900 and inr["mrr_minor"] == 199_900  # per-currency untouched
    combined = body["combined_current"]
    assert combined["currency"] == "INR" and combined["inr_per_usd"] == "88"
    assert combined["mrr_minor"] == 199_900 + 4_900 * 88
    assert combined["paying_orgs"] == 2  # the pilot is not counted
    assert combined["arpa_minor"] == round(combined["mrr_minor"] / 2)


def test_metrics_json_says_rate_not_set_for_combined_only(panel, db, monkeypatch):
    monkeypatch.delenv("METRICS_INR_PER_USD", raising=False)
    make_org(db, tier="basic", period="monthly", name="Payer", first_charged_at=datetime.now(timezone.utc))
    body = panel.get("/internal/metrics").json()
    assert body["rate"] is None
    assert body["combined_current"]["inr_per_usd"] is None and "mrr_minor" not in body["combined_current"]
    assert body["current"][1]["mrr_minor"] == 199_900
    csv_text = panel.get("/internal/metrics/export.csv").text
    rows = list(csv.reader(io.StringIO(csv_text)))
    inr = [row for row in rows[1:] if row[1] == "INR"][-1]
    assert inr[CSV_HEADER.index("mrr_minor")] == "1999.00"
    assert inr[CSV_HEADER.index("inr_per_usd")] == ""
    assert inr[CSV_HEADER.index("combined_mrr_minor")] == ""


def test_csv_export_has_combined_columns(panel, db, monkeypatch):
    monkeypatch.setenv("METRICS_INR_PER_USD", "88")
    make_org(db, tier="basic", period="monthly", name="Payer", first_charged_at=datetime.now(timezone.utc))
    rows = list(csv.reader(io.StringIO(panel.get("/internal/metrics/export.csv").text)))
    assert all(len(row) == len(CSV_HEADER) for row in rows)
    for row in rows[-2:]:  # both currency rows of the live date carry the same combined block
        assert row[CSV_HEADER.index("inr_per_usd")] == "88"
        assert row[CSV_HEADER.index("combined_mrr_minor")] == "1999.00"


def test_entered_rate_overrides_the_server_rate_and_is_not_stored(panel, db, monkeypatch):
    monkeypatch.setenv("METRICS_INR_PER_USD", "88")
    now = datetime.now(timezone.utc)
    make_org(db, tier="basic", period="monthly", name="Payer", first_charged_at=now)
    make_org(
        db, tier="basic", period="monthly", name="UsdPayer", first_charged_at=now,
        billing_currency="USD", billing_country="US",
    )
    body = panel.get("/internal/metrics", params={"rate": "83.5"}).json()
    assert body["rate"] == "83.5" and body["rate_source"] == "entered"
    assert body["combined_current"]["mrr_minor"] == round(199_900 + 4_900 * 83.5)
    assert body["current"][0]["mrr_minor"] == 4_900  # per-currency untouched
    assert panel.get("/internal/metrics").json()["rate_source"] == "server"
    rows = list(csv.reader(io.StringIO(panel.get("/internal/metrics/export.csv", params={"rate": "83.5"}).text)))
    assert rows[-1][CSV_HEADER.index("inr_per_usd")] == "83.5"


def test_entered_rate_works_when_the_server_rate_is_not_set(panel, db, monkeypatch):
    monkeypatch.delenv("METRICS_INR_PER_USD", raising=False)
    make_org(db, tier="basic", period="monthly", name="Payer", first_charged_at=datetime.now(timezone.utc))
    assert panel.get("/internal/metrics").json()["rate_source"] is None
    body = panel.get("/internal/metrics", params={"rate": "90"}).json()
    assert body["rate_source"] == "entered" and body["combined_current"]["mrr_minor"] == 199_900


def test_entered_rate_must_be_a_positive_number(panel):
    for bad in ("abc", "0", "-5", "nan"):
        assert panel.get("/internal/metrics", params={"rate": bad}).status_code == 422
        assert panel.get("/internal/metrics/export.csv", params={"rate": bad}).status_code == 422
