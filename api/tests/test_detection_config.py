"""Phase 8: detection_config validation, tier gating and the dry-run list."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from api.detection_config import (
    effective_detection_config,
    endpoint_matches,
    endpoint_minimum,
    validate_detection_config,
)
from api.tests.billing_testkit import make_org
from db.models import Verdict

GOOD = {
    "attack_threshold": 0.5,
    "block_confidence_threshold": 0.8,
    "agent_min_confidence": {"AuthAgent": 0.7},
    "endpoint_thresholds": [{"pattern": "/api/login", "min_confidence": 0.9}, {"pattern": "/admin/*", "min_confidence": 0.8}],
}


# ---------------------------------------------------------------------------
# Pure validation
# ---------------------------------------------------------------------------

def test_valid_config_round_trips():
    assert validate_detection_config(GOOD) == GOOD


@pytest.mark.parametrize("raw", [None, {}, {"attack_threshold": None}, {"agent_min_confidence": {}}, {"endpoint_thresholds": []}])
def test_empty_config_normalises_to_none(raw):
    assert validate_detection_config(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        {"attack_threshold": 0.39},
        {"attack_threshold": 0.91},
        {"attack_threshold": "0.6"},
        {"attack_threshold": True},
        {"block_confidence_threshold": 0.49},
        {"block_confidence_threshold": 0.96},
        {"agent_min_confidence": {"NopeAgent": 0.7}},
        {"agent_min_confidence": {"AuthAgent": 0.49}},
        {"agent_min_confidence": ["AuthAgent"]},
        {"endpoint_thresholds": [{"pattern": "login", "min_confidence": 0.8}]},
        {"endpoint_thresholds": [{"pattern": "/a*b", "min_confidence": 0.8}]},
        {"endpoint_thresholds": [{"pattern": "/a", "min_confidence": 0.49}]},
        {"endpoint_thresholds": [{"pattern": "/a", "min_confidence": 1.0}]},
        {"endpoint_thresholds": [{"pattern": "/a", "min_confidence": 0.8}, {"pattern": "/a", "min_confidence": 0.9}]},
        {"endpoint_thresholds": [{"pattern": "/" + "a" * 200, "min_confidence": 0.8}]},
        {"endpoint_thresholds": [{"pattern": f"/p{i}", "min_confidence": 0.8} for i in range(21)]},
        {"surprise": 1},
        "not an object",
    ],
)
def test_invalid_config_is_rejected(raw):
    with pytest.raises(ValueError):
        validate_detection_config(raw)


def test_effective_config_only_for_eligible_tiers():
    assert effective_detection_config("pro", GOOD) == GOOD
    assert effective_detection_config("enterprise", GOOD) == GOOD
    for tier in ("starter", "basic", "growth"):
        assert effective_detection_config(tier, GOOD) == {}


def test_effective_config_never_raises_on_bad_stored_data():
    assert effective_detection_config("pro", {"attack_threshold": 5}) == {}
    assert effective_detection_config("pro", "junk") == {}
    assert effective_detection_config("pro", None) == {}


def test_endpoint_matching_and_highest_minimum_wins():
    assert endpoint_matches("/admin/*", "/admin/users")
    assert not endpoint_matches("/admin/*", "/administrator")
    assert endpoint_matches("/api/login", "/api/login")
    assert not endpoint_matches("/api/login", "/api/login/x")
    cfg = {"endpoint_thresholds": [{"pattern": "/api/*", "min_confidence": 0.7}, {"pattern": "/api/login", "min_confidence": 0.9}]}
    assert endpoint_minimum(cfg, "/api/login") == 0.9
    assert endpoint_minimum(cfg, "/api/other") == 0.7
    assert endpoint_minimum(cfg, "/home") is None
    assert endpoint_minimum(cfg, None) is None


# ---------------------------------------------------------------------------
# PATCH /clients/me
# ---------------------------------------------------------------------------

def _patch(env, org, body, role="owner"):
    env.act_as(org, role)
    return env.client.patch("/clients/me", json=body)


def test_pro_org_can_save_and_read_back_a_config(env, db):
    org = make_org(db, tier="pro")
    r = _patch(env, org, {"detection_config": GOOD})
    assert r.status_code == 200, r.text
    assert r.json()["detection_config"] == GOOD
    env.refresh()
    assert db.get(type(org), org.id).detection_config == GOOD
    env.act_as(org)
    assert env.client.get("/clients/me").json()["detection_config"] == GOOD


def test_empty_object_resets_the_config(env, db):
    org = make_org(db, tier="pro", detection_config=GOOD)
    r = _patch(env, org, {"detection_config": {}})
    assert r.status_code == 200, r.text
    assert r.json()["detection_config"] is None
    env.refresh()
    assert db.get(type(org), org.id).detection_config is None


def test_out_of_range_config_is_a_422_and_nothing_is_stored(env, db):
    org = make_org(db, tier="pro")
    r = _patch(env, org, {"detection_config": {"attack_threshold": 0.2}})
    assert r.status_code == 422
    assert "attack_threshold" in r.text
    env.refresh()
    assert db.get(type(org), org.id).detection_config is None


@pytest.mark.parametrize("tier", ["starter", "basic", "growth"])
def test_lower_tiers_cannot_set_a_config(env, db, tier):
    org = make_org(db, tier=tier)
    r = _patch(env, org, {"detection_config": GOOD})
    assert r.status_code == 403
    env.refresh()
    assert db.get(type(org), org.id).detection_config is None


def test_viewer_cannot_change_settings(env, db):
    org = make_org(db, tier="pro")
    assert _patch(env, org, {"detection_config": GOOD}, role="viewer").status_code == 403


@pytest.mark.parametrize("tier", ["growth", "pro", "enterprise"])
def test_auto_block_tiers_can_turn_dry_run_on(env, db, tier):
    org = make_org(db, tier=tier)
    r = _patch(env, org, {"auto_block_dry_run": True})
    assert r.status_code == 200, r.text
    assert r.json()["auto_block_dry_run"] is True


@pytest.mark.parametrize("tier", ["starter", "basic"])
def test_lower_tiers_cannot_turn_dry_run_on_but_can_turn_it_off(env, db, tier):
    org = make_org(db, tier=tier)
    assert _patch(env, org, {"auto_block_dry_run": True}).status_code == 403
    org.auto_block_dry_run = True
    db.commit()
    r = _patch(env, org, {"auto_block_dry_run": False})
    assert r.status_code == 200
    assert r.json()["auto_block_dry_run"] is False


# ---------------------------------------------------------------------------
# GET /verdicts/would-have-blocked
# ---------------------------------------------------------------------------

def _verdict(db, org, ip, would_have_blocked_at=None):
    v = Verdict(
        id=str(uuid.uuid4()), org_id=org.id, timestamp=datetime.now(timezone.utc), ip=ip,
        severity="high", confidence=0.9, would_have_blocked_at=would_have_blocked_at,
    )
    db.add(v)
    db.commit()
    return v


def test_would_have_blocked_lists_only_marked_verdicts_for_this_org(env, db):
    org = make_org(db, tier="growth")
    other = make_org(db, tier="growth", name="Other")
    now = datetime.now(timezone.utc)
    _verdict(db, org, "198.51.100.1", would_have_blocked_at=now)
    _verdict(db, org, "198.51.100.2")
    _verdict(db, other, "198.51.100.3", would_have_blocked_at=now)
    env.act_as(org)
    r = env.client.get("/verdicts/would-have-blocked")
    assert r.status_code == 200, r.text
    assert [row["ip"] for row in r.json()] == ["198.51.100.1"]
    assert r.json()[0]["would_have_blocked_at"] is not None
