"""Phase 14 regression tests: QA clean-up of the Phase 13 ledger.

Routes run through the real app with the in-memory database from conftest. The
Redis counters behind the auth routes are replaced by a small in-memory fake,
the Turnstile verifier and outgoing email are stubbed, and the slowapi limiter
is switched off (it counts in Redis). Nothing here needs a network or a broker.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import api.routes.auth as auth_routes
import api.routes.org as org_routes
from api.auth_utils import encrypt_secret, hash_password, hash_token
from api.deps import get_current_client
from api.limiter import limiter
from api.tests.billing_testkit import make_org
from db.models import (
    BillingEvent,
    Client,
    MfaBackupCode,
    Organization,
    OrganizationMember,
    OrgInvite,
    Payment,
)

PASSWORD = "pw-12345678"


class FakeRedis:
    """The slice of redis-py the auth routes use."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def incr(self, key):
        self.data[key] = int(self.data.get(key, 0)) + 1
        return self.data[key]

    def expire(self, key, ttl):
        return True

    def get(self, key):
        value = self.data.get(key)
        return None if value is None else str(value)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def setex(self, key, ttl, value):
        self.data[key] = value

    def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    fake = FakeRedis()
    monkeypatch.setattr(auth_routes, "_redis", fake)
    monkeypatch.setattr(org_routes, "_redis", fake)
    monkeypatch.setattr(auth_routes, "verify_turnstile_token", lambda token, ip=None: True)
    for name in (
        "send_verification_email",
        "send_password_reset_email",
        "send_password_changed_email",
        "send_login_lockout_email",
        "send_mfa_enabled_email",
    ):
        monkeypatch.setattr(auth_routes, name, lambda *a, **k: None)
    monkeypatch.setattr(org_routes, "send_org_invite_email", lambda *a, **k: None)
    return fake


def _client(db, email="owner@acme.test", **extra) -> Client:
    client = Client(
        email=email, password_hash=hash_password(PASSWORD), full_name="Owner", email_verified=True, **extra
    )
    db.add(client)
    db.commit()
    return client


def _register_body(**over) -> dict:
    body = {
        "email": "new@acme.test",
        "password": "Str0ng-pass-123",
        "full_name": "New Person",
        "company_name": "NewCo",
        "captcha_token": "ok",
        "tos_accepted": True,
    }
    body.update(over)
    return body


# ---------------------------------------------------------------------------
# F-002, F-003, F-004: register validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "over",
    [
        {"password": ""},
        {"password": "a"},
        {"password": "x" * 7},
        {"password": "x" * 129},
        {"email": "qa13-not-an-email"},
        {"email": "a b@acme.test"},
        {"email": "x" * 250 + "@acme.test"},
        {"company_name": "c" * 300},
        {"company_name": "   "},
        {"full_name": "n" * 300},
    ],
)
def test_register_refuses_bad_input_with_422_and_creates_nothing(env, db, over):
    r = env.client.post("/auth/register", json=_register_body(**over))
    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], str)
    assert db.query(Client).count() == 0
    assert db.query(Organization).count() == 0


def test_register_trims_and_lowercases_the_email_and_blocks_a_second_account_for_it(env, db):
    r = env.client.post("/auth/register", json=_register_body(email="  Trim@Acme.TEST  "))
    assert r.status_code == 201
    assert db.query(Client).one().email == "trim@acme.test"
    again = env.client.post("/auth/register", json=_register_body(email="trim@acme.test", company_name="Other"))
    assert again.status_code == 400
    assert db.query(Client).count() == 1


def test_register_accepts_the_longest_allowed_values(env, db):
    r = env.client.post(
        "/auth/register",
        json=_register_body(company_name="c" * 255, full_name="n" * 255, password="p" * 128),
    )
    assert r.status_code == 201


def test_register_validation_runs_before_the_captcha(env, db, monkeypatch):
    seen = []
    monkeypatch.setattr(auth_routes, "verify_turnstile_token", lambda token, ip=None: seen.append(token) or True)
    assert env.client.post("/auth/register", json=_register_body(email="nope")).status_code == 422
    assert seen == []


def test_login_finds_an_account_when_the_typed_email_has_spaces_or_capitals(env, db):
    _client(db, "owner@acme.test")
    r = env.client.post(
        "/auth/login", json={"email": "  Owner@Acme.test ", "password": PASSWORD, "captcha_token": "ok"}
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# F-002: reset-password and invite accept
# ---------------------------------------------------------------------------

def _with_reset_code(db, code="123456"):
    client = _client(db)
    client.reset_token_hash = hash_password(code)
    client.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.commit()
    return client


@pytest.mark.parametrize("weak", ["", "a", "x" * 7, "x" * 129])
def test_reset_password_refuses_a_weak_password_and_keeps_the_code(env, db, weak):
    client = _with_reset_code(db)
    r = env.client.post(
        "/auth/reset-password", json={"email": client.email, "code": "123456", "new_password": weak}
    )
    assert r.status_code == 422
    db.expire_all()
    assert client.reset_token_hash is not None


def test_reset_password_with_a_good_password_still_works(env, db):
    client = _with_reset_code(db)
    r = env.client.post(
        "/auth/reset-password", json={"email": client.email, "code": "123456", "new_password": "Brand-new-pass-1"}
    )
    assert r.status_code == 200


def test_change_password_has_the_same_maximum(env, db):
    client = _client(db)
    from api.main import app

    app.dependency_overrides[get_current_client] = lambda: db.get(Client, client.id)
    short = env.client.post(
        "/auth/change-password", json={"current_password": PASSWORD, "new_password": "short"}
    )
    assert short.status_code == 422
    long_ = env.client.post(
        "/auth/change-password", json={"current_password": PASSWORD, "new_password": "x" * 129}
    )
    assert long_.status_code == 422
    ok = env.client.post(
        "/auth/change-password", json={"current_password": PASSWORD, "new_password": "A-fine-new-pass"}
    )
    assert ok.status_code == 200
    assert "lose access within 15 minutes" in ok.json()["message"]


def _invite_for(db, org, email="invitee@acme.test", role="viewer") -> str:
    token = "tok-" + email
    db.add(
        OrgInvite(
            org_id=org.id,
            invited_email=email,
            role=role,
            token_hash=hash_token(token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=3),
        )
    )
    db.commit()
    return token


def test_accepting_an_invite_as_a_new_user_needs_a_real_password(env, db):
    org = make_org(db, tier="starter")
    token = _invite_for(db, org)
    for bad in ("a", "x" * 129):
        r = env.client.post(f"/org/invite/{token}/accept", json={"password": bad, "full_name": "Inv"})
        assert r.status_code == 422
    assert db.query(Client).count() == 0
    ok = env.client.post(f"/org/invite/{token}/accept", json={"password": "Good-pass-123", "full_name": "Inv"})
    assert ok.status_code == 200


def test_accepting_an_invite_refuses_an_oversize_name(env, db):
    org = make_org(db, tier="starter")
    token = _invite_for(db, org)
    r = env.client.post(f"/org/invite/{token}/accept", json={"password": "Good-pass-123", "full_name": "n" * 300})
    assert r.status_code == 422
    assert db.query(Client).count() == 0


# ---------------------------------------------------------------------------
# F-005: verify-email guess limit
# ---------------------------------------------------------------------------

def _unverified(db, code="123456", email="fresh@acme.test"):
    client = Client(
        email=email,
        password_hash=hash_password(PASSWORD),
        full_name="Fresh",
        email_verified=False,
        verify_token=hash_password(code),
        verify_token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(client)
    db.commit()
    return client


def test_four_wrong_codes_leave_the_code_usable(env, db):
    client = _unverified(db)
    for _ in range(4):
        assert env.client.post("/auth/verify-email", json={"email": client.email, "code": "000000"}).status_code == 400
    ok = env.client.post("/auth/verify-email", json={"email": client.email, "code": "123456"})
    assert ok.status_code == 200
    db.expire_all()
    assert client.email_verified is True


def test_the_fifth_wrong_code_burns_it_even_for_the_right_code(env, db):
    client = _unverified(db)
    for _ in range(5):
        r = env.client.post("/auth/verify-email", json={"email": client.email, "code": "000000"})
        assert r.status_code == 400
    late = env.client.post("/auth/verify-email", json={"email": client.email, "code": "123456"})
    assert late.status_code == 400
    db.expire_all()
    assert client.verify_token is None and client.email_verified is False


def test_resend_gives_a_fresh_code_and_a_fresh_count(env, db, isolated):
    client = _unverified(db)
    for _ in range(5):
        env.client.post("/auth/verify-email", json={"email": client.email, "code": "000000"})
    sent = []
    auth_routes.send_verification_email = lambda to, otp: sent.append(otp)
    try:
        r = env.client.post("/auth/resend-verification", json={"email": client.email, "captcha_token": "ok"})
    finally:
        del auth_routes.send_verification_email
    assert r.status_code == 200 and len(sent) == 1
    ok = env.client.post("/auth/verify-email", json={"email": client.email, "code": sent[0]})
    assert ok.status_code == 200


def test_verify_email_has_a_per_ip_limit():
    # The route carries the slowapi decorator, so the limit is registered.
    keys = [k for k in limiter._route_limits if k.endswith("auth.verify_email")]
    assert keys, "verify_email must be rate limited per IP"


# ---------------------------------------------------------------------------
# F-006: bcrypt does not run on the event loop
# ---------------------------------------------------------------------------

def test_password_checks_run_in_a_worker_thread():
    import asyncio
    import threading

    from api import auth_utils

    seen = []
    real = auth_utils.verify_password

    def spy(plain, hashed):
        seen.append(threading.current_thread() is threading.main_thread())
        return real(plain, hashed)

    original = auth_utils.verify_password
    auth_utils.verify_password = spy
    try:
        hashed = hash_password("pw-12345678")
        assert asyncio.run(auth_utils.averify_password("pw-12345678", hashed)) is True
    finally:
        auth_utils.verify_password = original
    assert seen == [False]


def test_the_event_loop_stays_responsive_while_a_password_is_hashed():
    import asyncio

    from api.auth_utils import ahash_password

    async def scenario():
        ticks = []

        async def ticker():
            for _ in range(8):
                await asyncio.sleep(0.02)
                ticks.append(time.monotonic())

        start = time.monotonic()
        await asyncio.gather(ahash_password("pw-12345678"), ticker())
        return ticks, start

    ticks, start = asyncio.run(scenario())
    gaps = [b - a for a, b in zip([start] + ticks, ticks)]
    assert max(gaps) < 0.15  # a blocked loop would show a gap of about the whole hash time


# ---------------------------------------------------------------------------
# F-007: TOTP step and MFA challenge token are single use
# ---------------------------------------------------------------------------

def _mfa_client(db):
    secret = pyotp.random_base32()
    client = _client(db, mfa_enabled=True, mfa_secret=encrypt_secret(secret))
    return client, secret


def _challenge(env, client) -> str:
    r = env.client.post("/auth/login", json={"email": client.email, "password": PASSWORD, "captcha_token": "ok"})
    assert r.json()["code"] == "MFA_REQUIRED"
    return r.json()["mfa_token"]


def test_a_totp_code_works_once(env, db):
    client, secret = _mfa_client(db)
    code = pyotp.TOTP(secret).now()
    first = env.client.post("/auth/login/mfa", json={"mfa_token": _challenge(env, client), "code": code})
    assert first.status_code == 200
    second = env.client.post("/auth/login/mfa", json={"mfa_token": _challenge(env, client), "code": code})
    assert second.status_code == 401


def test_a_challenge_token_works_once_even_with_a_fresh_code(env, db, monkeypatch):
    client, secret = _mfa_client(db)
    token = _challenge(env, client)
    totp = pyotp.TOTP(secret)
    ok = env.client.post("/auth/login/mfa", json={"mfa_token": token, "code": totp.now()})
    assert ok.status_code == 200
    # A later time step gives a different valid code, so only the token is spent.
    real_time = time.time
    monkeypatch.setattr(auth_routes.time, "time", lambda: real_time() + 30)
    later_code = totp.at(real_time() + 30)
    replay = env.client.post("/auth/login/mfa", json={"mfa_token": token, "code": later_code})
    assert replay.status_code == 401
    assert replay.json()["detail"] == "Invalid or expired MFA token."


def test_a_challenge_token_works_once_with_backup_codes_too(env, db):
    client, _ = _mfa_client(db)
    db.add_all(
        [
            MfaBackupCode(client_id=client.id, code_hash=hash_token("AAAA1111")),
            MfaBackupCode(client_id=client.id, code_hash=hash_token("BBBB2222")),
        ]
    )
    db.commit()
    token = _challenge(env, client)
    assert env.client.post("/auth/login/mfa", json={"mfa_token": token, "code": "AAAA-1111"}).status_code == 200
    replay = env.client.post("/auth/login/mfa", json={"mfa_token": token, "code": "BBBB-2222"})
    assert replay.status_code == 401
    unused = db.query(MfaBackupCode).filter(MfaBackupCode.used == False).count()  # noqa: E712
    assert unused == 1


def test_a_challenge_token_without_a_jti_is_refused(env, db):
    from datetime import datetime as dt

    from jose import jwt

    client, secret = _mfa_client(db)
    old = jwt.encode(
        {"sub": client.id, "exp": dt.now(timezone.utc) + timedelta(minutes=5), "type": "mfa_challenge"},
        auth_routes.JWT_SECRET,
        algorithm=auth_routes.JWT_ALGORITHM,
    )
    r = env.client.post("/auth/login/mfa", json={"mfa_token": old, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 401


def test_mfa_enrolment_also_refuses_a_replayed_code(env, db):
    secret = pyotp.random_base32()
    client = _client(db, mfa_secret=encrypt_secret(secret))
    from api.main import app

    app.dependency_overrides[get_current_client] = lambda: db.get(Client, client.id)
    code = pyotp.TOTP(secret).now()
    auth_routes._claim_once(f"clew:totp_used:{client.id}:{int(time.time() // 30)}", 100)
    r = env.client.post("/auth/mfa/verify", json={"code": code})
    assert r.status_code == 400
    assert db.get(Client, client.id).mfa_enabled is False


# ---------------------------------------------------------------------------
# F-008: switch-org with a malformed id
# ---------------------------------------------------------------------------

def test_switch_org_with_a_malformed_id_is_a_422_not_a_500(env, db):
    client = _client(db)
    from api.main import app

    app.dependency_overrides[get_current_client] = lambda: db.get(Client, client.id)
    for bad in ("x' or 1=1", "xyz", "", "123"):
        assert env.client.post("/auth/switch-org", json={"org_id": bad}).status_code == 422
    other = "6f0c9d2e-1111-4222-8333-444455556666"
    assert env.client.post("/auth/switch-org", json={"org_id": other}).status_code == 403


def test_switch_org_to_a_real_membership_still_works(env, db):
    client = _client(db)
    org = make_org(db, tier="starter")
    db.add(OrganizationMember(client_id=client.id, org_id=org.id, role="owner"))
    db.commit()
    from api.main import app

    app.dependency_overrides[get_current_client] = lambda: db.get(Client, client.id)
    r = env.client.post("/auth/switch-org", json={"org_id": org.id})
    assert r.status_code == 200 and r.json()["org_id"] == org.id


# ---------------------------------------------------------------------------
# F-009: login limits
# ---------------------------------------------------------------------------

def _login(env, password=PASSWORD):
    return env.client.post(
        "/auth/login", json={"email": "owner@acme.test", "password": password, "captcha_token": "ok"}
    )


def test_ten_good_logins_in_a_window_are_all_allowed_and_the_eleventh_is_not(env, db):
    _client(db)
    assert [_login(env).status_code for _ in range(10)] == [200] * 10
    assert _login(env).status_code == 429


def test_the_sixth_wrong_password_shows_the_lockout_text(env, db):
    _client(db)
    assert [_login(env, "wrong").status_code for _ in range(5)] == [401] * 5
    sixth = _login(env, "wrong")
    assert sixth.status_code == 429
    assert sixth.json()["detail"] == "Too many failed login attempts. Try again in 15 minutes."


# ---------------------------------------------------------------------------
# F-010: one CAPTCHA failure text everywhere
# ---------------------------------------------------------------------------

def test_register_and_forgot_password_use_the_script_blocker_text(env, db, monkeypatch):
    monkeypatch.setattr(auth_routes, "verify_turnstile_token", lambda token, ip=None: False)
    reg = env.client.post("/auth/register", json=_register_body())
    forgot = env.client.post("/auth/forgot-password", json={"email": "a@b.test", "captcha_token": "bad"})
    for r in (reg, forgot):
        assert r.status_code == 400
        assert r.json()["detail"] == auth_routes._CAPTCHA_FAILED_DETAIL
        assert "script blocker" in r.json()["detail"]


# ---------------------------------------------------------------------------
# F-012: invites
# ---------------------------------------------------------------------------

@pytest.fixture
def owner_in_org(env, db):
    org = make_org(db, tier="starter", domain="acme.test")
    client = _client(db)
    db.add(OrganizationMember(client_id=client.id, org_id=org.id, role="owner"))
    db.commit()
    from api.main import app

    app.dependency_overrides[get_current_client] = lambda: db.get(Client, client.id)
    env.act_as(org, "owner")
    return org, client


def test_invite_trims_the_email_and_refuses_an_existing_member_typed_with_spaces(env, db, owner_in_org):
    org, _ = owner_in_org
    member = _client(db, "viewer@acme.test")
    db.add(OrganizationMember(client_id=member.id, org_id=org.id, role="viewer"))
    db.commit()
    r = env.client.post("/org/invite", json={"email": " VIEWER@acme.test ", "role": "viewer"})
    assert r.status_code == 400
    assert "already a member" in r.json()["detail"]
    assert db.query(OrgInvite).count() == 0


@pytest.mark.parametrize("bad", ["not an email <script>", "", "no-at-sign", "x" * 260 + "@acme.test"])
def test_invite_refuses_a_malformed_or_oversize_email(env, db, owner_in_org, bad):
    r = env.client.post("/org/invite", json={"email": bad, "role": "viewer"})
    assert r.status_code == 422
    assert db.query(OrgInvite).count() == 0


def test_invite_is_stored_trimmed_and_a_second_open_invite_is_refused(env, db, owner_in_org):
    first = env.client.post("/org/invite", json={"email": "  New1@Acme.test ", "role": "viewer"})
    assert first.status_code == 201
    assert db.query(OrgInvite).one().invited_email == "new1@acme.test"
    second = env.client.post("/org/invite", json={"email": "new1@acme.test", "role": "viewer"})
    assert second.status_code == 400
    assert "open invite" in second.json()["detail"]
    assert db.query(OrgInvite).count() == 1


def test_create_org_refuses_an_oversize_name(env, db):
    client = _client(db)
    from api.main import app

    app.dependency_overrides[get_current_client] = lambda: db.get(Client, client.id)
    assert env.client.post("/org", json={"company_name": "c" * 300}).status_code == 422
    assert db.query(Organization).count() == 0


# ---------------------------------------------------------------------------
# F-013: pause is one conditional UPDATE
# ---------------------------------------------------------------------------

def test_pause_and_resume_write_with_a_conditional_update(env, db, owner_in_org, session_factory):
    org, _ = owner_in_org
    statements: list[str] = []
    engine = db.get_bind()

    def spy(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE ORGANIZATIONS"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", spy)
    try:
        env.client.post("/org/scanning/pause")
        env.client.post("/org/scanning/resume")
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert any("scanning_paused_at IS NULL" in s for s in statements)
    assert any("scanning_paused_at IS NOT NULL" in s for s in statements)


def test_a_second_pause_keeps_the_first_timestamp_even_from_a_stale_object(env, db, owner_in_org):
    org, _ = owner_in_org
    first = env.client.post("/org/scanning/pause").json()["scanning_paused_at"]
    # A stale in-memory copy that still thinks the org is running must not win.
    db.expire_all()
    stale = db.get(Organization, org.id)
    db.expunge(stale)
    second = env.client.post("/org/scanning/pause").json()["scanning_paused_at"]
    assert first == second


# ---------------------------------------------------------------------------
# F-027: a NUL character is a 422
# ---------------------------------------------------------------------------

def _nul_app():
    from api.main import app

    if not any(getattr(r, "path", "") == "/__p14/nul" for r in app.routes):

        @app.get("/__p14/nul")
        def _nul():
            raise ValueError("A string literal cannot contain NUL (0x00) characters.")

        @app.get("/__p14/other")
        def _other():
            raise ValueError("some other bug")

    return TestClient(app, raise_server_exceptions=False)


def test_a_nul_value_error_becomes_a_422():
    r = _nul_app().get("/__p14/nul")
    assert r.status_code == 422
    assert r.json() == {"detail": "Input contains a character that is not allowed."}


def test_any_other_value_error_is_still_a_500_with_a_correlation_id():
    r = _nul_app().get("/__p14/other")
    assert r.status_code == 500
    assert "correlation_id" in r.json()


def test_nul_in_a_field_we_validate_ourselves_is_a_422(env, db):
    r = env.client.post("/auth/register", json=_register_body(company_name="Co\u0000Ltd"))
    assert r.status_code == 422
    r = env.client.post("/auth/register", json=_register_body(email="a\u0000b@acme.test"))
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# F-036 and the account_deleted event
# ---------------------------------------------------------------------------

def test_deleting_an_account_leaves_other_orgs_and_writes_a_billing_event(env, db):
    client = _client(db, "doomed@acme.test")
    mine = make_org(db, tier="basic", period="monthly", company_name="Mine")
    theirs = make_org(db, tier="starter", company_name="Theirs")
    db.add_all(
        [
            OrganizationMember(client_id=client.id, org_id=mine.id, role="owner"),
            OrganizationMember(client_id=client.id, org_id=theirs.id, role="viewer"),
        ]
    )
    db.commit()
    from api.main import app

    app.dependency_overrides[get_current_client] = lambda: db.get(Client, client.id)
    r = env.client.post("/auth/delete-account", json={"confirmation": "DELETE"})
    assert r.status_code == 200
    db.expire_all()
    left = db.query(OrganizationMember).filter(OrganizationMember.org_id == theirs.id).count()
    assert left == 0
    assert db.get(Organization, mine.id).deleted_at is not None
    ev = db.query(BillingEvent).filter(BillingEvent.event == "account_deleted").one()
    assert (ev.org_id, ev.from_tier, ev.to_tier, ev.period) == (mine.id, "basic", None, "monthly")
    assert db.get(Client, client.id).email.endswith("@deleted.clew")


# ---------------------------------------------------------------------------
# Billing: F-008 receipt id, F-029 country lock, F-030 unapplied payments, F-033
# ---------------------------------------------------------------------------

def _fresh_org(db, **extra):
    return make_org(db, tier="starter", period=None, billing_country=None, billing_currency="USD", **extra)


def _order(env, tier="basic", country=None, **extra):
    body = {"purpose": "initial", "tier": tier, "period": "monthly", "accept_blocking_tos": True, **extra}
    if country:
        body["billing_country"] = country
    resp = env.create_order(**body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _events(db, org, event):
    return db.query(BillingEvent).filter(BillingEvent.org_id == org.id, BillingEvent.event == event).all()


def test_receipt_with_a_malformed_id_is_a_422_and_an_unknown_one_a_404(env, db):
    env.act_as(make_org(db, tier="basic", period="monthly"))
    assert env.client.get("/billing/payments/xyz").status_code == 422
    assert env.client.get("/billing/payments/6f0c9d2e-1111-4222-8333-444455556666").status_code == 404


def test_closing_checkout_without_paying_leaves_the_country_open(env, db):
    org = env.act_as(_fresh_org(db))
    _order(env, country="IN")
    db.expire_all()
    assert db.get(Organization, org.id).billing_country is None
    # The customer can still choose another country and pay.
    us = _order(env, country="US")
    rz_id = env.rp.pay(us["order_id"])
    assert env.verify(us["order_id"], rz_id).status_code == 200
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.billing_country, org.billing_currency, org.tier) == ("US", "USD", "basic")


def test_two_open_orders_in_different_countries_only_the_first_paid_counts(env, db, notifications):
    org = env.act_as(_fresh_org(db))
    inr = _order(env, country="IN")
    usd = _order(env, country="US")
    pay_usd = env.rp.pay(usd["order_id"])
    assert env.verify(usd["order_id"], pay_usd).json()["applied"] is True
    pay_inr = env.rp.pay(inr["order_id"])
    late = env.verify(inr["order_id"], pay_inr)
    assert late.status_code == 200 and late.json()["applied"] is False
    db.expire_all()
    assert db.get(Organization, org.id).billing_currency == "USD"
    assert db.get(Payment, inr["payment_id"]).status == "refunded"
    assert [c[0] for c in env.rp.refund_calls] == [pay_inr]
    assert len(notifications) == 1


def test_a_second_paid_initial_order_is_refunded_by_the_verify_route(env, db, notifications):
    org = env.act_as(_fresh_org(db))
    first = _order(env, "basic", country="US")
    second = _order(env, "growth", country="US")
    pay1 = env.rp.pay(first["order_id"])
    pay2 = env.rp.pay(second["order_id"])
    assert env.verify(first["order_id"], pay1).json()["applied"] is True
    assert env.verify(second["order_id"], pay2).json()["applied"] is False
    db.expire_all()
    org = db.get(Organization, org.id)
    assert org.tier == "basic"
    assert len(_events(db, org, "first_paid")) == 1
    assert db.get(Payment, first["payment_id"]).status == "captured"
    paid_back = db.get(Payment, second["payment_id"])
    assert paid_back.status == "refunded" and paid_back.refunded_at is not None
    assert env.rp.refund_calls == [(pay2, env.rp.refund_calls[0][1])]
    assert env.rp.refund_calls[0][1]["amount"] == second["amount"]
    assert len(_events(db, org, "payment_auto_refunded")) == 1
    assert len(notifications) == 1  # only the real purchase is announced


def test_a_second_paid_initial_order_is_refunded_by_the_webhook_too(env, db, notifications):
    org = env.act_as(_fresh_org(db))
    first = _order(env, "basic", country="US")
    second = _order(env, "growth", country="US")
    pay1 = env.rp.pay(first["order_id"])
    pay2 = env.rp.pay(second["order_id"])
    assert env.webhook(env.captured_event(pay1)).status_code == 200
    assert env.webhook(env.captured_event(pay2)).status_code == 200
    db.expire_all()
    assert db.get(Organization, org.id).tier == "basic"
    assert db.get(Payment, second["payment_id"]).status == "refunded"
    assert len(env.rp.refund_calls) == 1
    # Razorpay's own refund.processed for it changes nothing further.
    hook = {"event": "refund.processed", "payload": {"refund": {"entity": {"payment_id": pay2, "amount": second["amount"]}}}}
    assert env.webhook(hook).status_code == 200
    db.expire_all()
    assert db.get(Organization, org.id).tier == "basic"
    assert len(notifications) == 1


def test_when_razorpay_refuses_the_automatic_refund_the_payment_stays_flagged(env, db):
    org = env.act_as(_fresh_org(db))
    first = _order(env, "basic", country="US")
    second = _order(env, "growth", country="US")
    pay1 = env.rp.pay(first["order_id"])
    pay2 = env.rp.pay(second["order_id"])
    env.verify(first["order_id"], pay1)
    env.rp.fail_refunds = True
    assert env.verify(second["order_id"], pay2).status_code == 200
    db.expire_all()
    stuck = db.get(Payment, second["payment_id"])
    assert stuck.status == "captured"
    assert stuck.line_items["unapplied"] == "org_already_on_a_paid_plan"
    assert db.get(Organization, org.id).tier == "basic"


def _bought_basic(env, db, country="US"):
    org = env.act_as(_fresh_org(db))
    order = _order(env, "basic", country=country)
    rz_id = env.rp.pay(order["order_id"])
    assert env.verify(order["order_id"], rz_id).status_code == 200
    return org, order, rz_id


def _full_refund_hook(rz_id, amount):
    return {"event": "refund.processed", "payload": {"refund": {"entity": {"payment_id": rz_id, "amount": amount}}}}


def test_a_dashboard_refund_inside_72_hours_downgrades_like_the_refund_button(env, db):
    org, order, rz_id = _bought_basic(env, db)
    assert env.webhook(_full_refund_hook(rz_id, order["amount"])).status_code == 200
    db.expire_all()
    org = db.get(Organization, org.id)
    assert (org.tier, org.billing_period, org.next_billing_date) == ("starter", None, None)
    assert org.retention_grace_tier == "basic"
    assert len(_events(db, org, "refunded")) == 1
    assert db.get(Payment, order["payment_id"]).status == "refunded"


def test_a_dashboard_refund_after_72_hours_keeps_the_plan(env, db):
    org, order, rz_id = _bought_basic(env, db)
    payment = db.get(Payment, order["payment_id"])
    org.first_charged_at = datetime.now(timezone.utc) - timedelta(days=10)
    payment.captured_at = datetime.now(timezone.utc) - timedelta(days=10)
    db.commit()
    assert env.webhook(_full_refund_hook(rz_id, order["amount"])).status_code == 200
    db.expire_all()
    org = db.get(Organization, org.id)
    assert org.tier == "basic" and org.next_billing_date is not None
    assert db.get(Payment, order["payment_id"]).status == "refunded"
    assert _events(db, org, "refunded") == []


def test_the_refund_button_followed_by_its_webhook_downgrades_once(env, db):
    org, order, rz_id = _bought_basic(env, db)
    assert env.client.post("/billing/refund").status_code == 200
    assert env.webhook(_full_refund_hook(rz_id, order["amount"])).status_code == 200
    db.expire_all()
    assert len(_events(db, db.get(Organization, org.id), "refunded")) == 1


# ---------------------------------------------------------------------------
# F-028 settings field checks, F-019 first scan on the ARN save
# ---------------------------------------------------------------------------

@pytest.fixture
def settings_org(env, db, monkeypatch):
    import api.routes.clients as clients_routes
    import workers.tasks.process_logs as pl

    queued: list[tuple] = []
    monkeypatch.setattr(clients_routes, "_test_s3_connection", lambda *a, **k: ("connected", None))
    monkeypatch.setattr(pl.process_logs, "delay", lambda org_id: queued.append(("scan", org_id)))
    monkeypatch.setattr(pl.calibrate_client, "delay", lambda org_id: queued.append(("calibrate", org_id)))
    org = env.act_as(make_org(db, tier="growth", period="monthly", s3_bucket="my-bucket", log_format="apigw"))
    return org, queued


@pytest.mark.parametrize(
    "body",
    [
        {"alert_email": "a" * 300},
        {"alert_email": "not-an-email <x>"},
        {"s3_prefix": "p" * 300},
        {"waf_ip_set_id": "w" * 300},
        {"cloudflare_zone_id": "z" * 300},
        {"s3_prefix": "a\u0000b"},
    ],
)
def test_settings_refuses_bad_text_with_a_422(env, db, settings_org, body):
    r = env.client.patch("/clients/me", json=body)
    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], str)


def test_settings_stores_a_clean_alert_email_and_still_lets_it_be_cleared(env, db, settings_org):
    r = env.client.patch("/clients/me", json={"alert_email": "  Alerts@Acme.TEST "})
    assert r.status_code == 200 and r.json()["alert_email"] == "alerts@acme.test"
    cleared = env.client.patch("/clients/me", json={"alert_email": ""})
    assert cleared.status_code == 200 and cleared.json()["alert_email"] in ("", None)


def test_saving_the_role_arn_queues_the_first_scan_when_none_ever_completed(env, db, settings_org):
    org, queued = settings_org
    arn = "arn:aws:iam::123456789012:role/clew-read"
    assert env.client.patch("/clients/me", json={"aws_role_arn": arn}).status_code == 200
    assert ("scan", org.id) in queued


def test_saving_the_role_arn_after_a_completed_scan_does_not_queue_another(env, db, settings_org):
    org, queued = settings_org
    org.last_scan_completed_at = datetime.now(timezone.utc)
    db.commit()
    arn = "arn:aws:iam::123456789012:role/clew-read"
    assert env.client.patch("/clients/me", json={"aws_role_arn": arn}).status_code == 200
    assert ("scan", org.id) not in queued


# ---------------------------------------------------------------------------
# F-026 manual block
# ---------------------------------------------------------------------------

@pytest.fixture
def blocking_org(env, db, monkeypatch):
    import workers.tasks.push_blocks as pb

    pushed: list[str] = []
    monkeypatch.setattr(pb.push_block, "delay", lambda verdict_id, org_id: pushed.append(verdict_id))
    org = env.act_as(make_org(
        db,
        tier="growth",
        period="monthly",
        blocking_tos_accepted_at=datetime.now(timezone.utc),
        cloudflare_zone_id="zone",
        cloudflare_token="token",
    ))
    return org, pushed


@pytest.mark.parametrize("ip", ["224.0.0.1", "239.255.255.250", "100.64.0.1", "0.0.0.0", "10.0.0.1", "127.0.0.1"])
def test_manual_block_refuses_non_public_ips(env, db, blocking_org, ip):
    r = env.client.post("/verdicts/manual-block", json={"ip": ip})
    assert r.status_code == 422, r.text


def test_manual_block_twice_reuses_the_verdict(env, db, blocking_org):
    from db.models import Verdict

    org, pushed = blocking_org
    first = env.client.post("/verdicts/manual-block", json={"ip": "8.8.8.8"})
    second = env.client.post("/verdicts/manual-block", json={"ip": "8.8.8.8"})
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert db.query(Verdict).filter(Verdict.org_id == org.id, Verdict.ip == "8.8.8.8").count() == 1
    assert len(pushed) == 2


def test_blocked_tab_keeps_an_ip_whose_block_failed(env, db, blocking_org):
    from db.models import IpMemory

    org, _ = blocking_org
    now = datetime.now(timezone.utc)
    db.add(IpMemory(
        id=str(uuid.uuid4()), org_id=org.id, ip="8.8.8.8", first_seen=now, last_seen=now,
        total_requests=0, threat_count=1, risk_score=1.0,
        cloudflare_block_error="Authentication failed (status: 400)",
    ))
    db.add(IpMemory(
        id=str(uuid.uuid4()), org_id=org.id, ip="1.1.1.1", first_seen=now, last_seen=now,
        total_requests=0, threat_count=1, risk_score=1.0,
    ))
    db.commit()
    r = env.client.get("/ips?blocked_only=true")
    assert [i["ip"] for i in r.json()["items"]] == ["8.8.8.8"]


def test_cloudflare_errors_are_stored_as_plain_messages(monkeypatch):
    import blocking.cloudflare as cf

    class Resp:
        status_code = 400

        def json(self):
            return {"success": False, "errors": [{"code": 9106, "message": "Authentication failed (status: 400)"}]}

    monkeypatch.setattr(cf.httpx, "post", lambda *a, **k: Resp())
    ok, error = cf.block_ip("8.8.8.8", "zone", "token")
    assert ok is False and error == "Authentication failed (status: 400)"
