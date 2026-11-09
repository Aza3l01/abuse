"""push_unblock result statuses: a real removal, a failed removal, and an org
with no integration configured must each be distinguishable."""
from __future__ import annotations

from datetime import datetime, timezone

import workers.tasks.push_blocks as push_blocks
from api.tests.billing_testkit import make_org
from db.models import Verdict


def _blocked_verdict(db, org) -> Verdict:
    verdict = Verdict(
        org_id=org.id,
        timestamp=datetime.now(timezone.utc),
        ip="198.51.100.9",
        severity="high",
        confidence=0.9,
        blocked=True,
    )
    db.add(verdict)
    db.commit()
    return verdict


def _setup(monkeypatch, session_factory, remove_result=(True, None)):
    monkeypatch.setattr(push_blocks, "SessionLocal", session_factory)
    monkeypatch.setattr(push_blocks, "aws_session_for_org", lambda org: None)
    monkeypatch.setattr(push_blocks, "remove_ip_from_set", lambda **kwargs: remove_result)


def test_unblock_with_no_integration_is_reported_as_no_integration(db, session_factory, monkeypatch):
    _setup(monkeypatch, session_factory)
    org = make_org(db, tier="starter")
    verdict = _blocked_verdict(db, org)

    result = push_blocks.push_unblock(verdict.id, org.id)

    assert result["status"] == "no_integration"
    assert result["via"] == []
    db.expire_all()
    assert db.get(Verdict, verdict.id).blocked is False


def test_unblock_through_an_integration_is_reported_as_unblocked(db, session_factory, monkeypatch):
    _setup(monkeypatch, session_factory)
    org = make_org(db, tier="growth", waf_ip_set_id="clew-blocked-ips::set-1")
    verdict = _blocked_verdict(db, org)

    result = push_blocks.push_unblock(verdict.id, org.id)

    assert result == {"status": "unblocked", "ip": "198.51.100.9", "via": ["waf"]}
    db.expire_all()
    assert db.get(Verdict, verdict.id).blocked is False


def test_unblock_failure_leaves_the_verdict_blocked(db, session_factory, monkeypatch):
    _setup(monkeypatch, session_factory, remove_result=(False, "access denied"))
    org = make_org(db, tier="growth", waf_ip_set_id="clew-blocked-ips::set-1")
    verdict = _blocked_verdict(db, org)

    result = push_blocks.push_unblock(verdict.id, org.id)

    assert result == {"status": "failed", "reason": "no_integration_succeeded"}
    db.expire_all()
    assert db.get(Verdict, verdict.id).blocked is True
