"""Phase 8: the automatic-blocking gate in process_logs (block threshold, dry-run,
endpoint minimums), run through the real task with the engine, S3 and Redis
replaced by fakes. The detection engine itself is tested in detection/engine/tests.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import workers.tasks.process_logs as pl
import workers.tasks.push_blocks as push_blocks
from api.tests.billing_testkit import make_org
from db.models import Verdict

NOW = datetime.now(timezone.utc)
RECORDS = [
    {
        "timestamp": f"2024-01-15T14:00:{i:02d}Z", "ip": "198.51.100.7", "method": "POST",
        "endpoint": "/api/login", "source_key": f"k:{i}",
    }
    for i in range(5)
]


class FakeRedis:
    def set(self, *args, **kwargs):
        return True

    def delete(self, *args, **kwargs):
        return 1


class FakeReader:
    def __init__(self, *args, **kwargs):
        pass

    def list_objects_since(self, cutoff):
        return [{"Key": "logs/a"}]

    def list_new_objects(self):
        return [{"Key": "logs/a"}]

    def iter_lines(self, objects):
        for i in range(len(RECORDS)):
            yield "logs/a", f"line{i}"


def _runner_class(confidence: float, endpoint: str = "/api/login", agents: tuple = ("AuthAgent",)):
    class FakeRunner:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            self.llm_calls_used = 0

        def run(self, batch, mode="window"):
            return {
                "is_attack": True, "ip": "198.51.100.7", "method": "POST", "endpoint": endpoint,
                "threat_type": "BRUTE_FORCE", "severity": "high", "confidence": confidence,
                "agents_triggered": list(agents), "explanation": "x", "cost_prevented": 0.0,
            }

        def flush(self):
            pass

    return FakeRunner


@pytest.fixture
def run_task(db, session_factory, monkeypatch):
    pushed: list[tuple] = []
    monkeypatch.setattr(pl, "SessionLocal", session_factory)
    monkeypatch.setattr(pl, "_get_redis", lambda: FakeRedis())
    monkeypatch.setattr(pl, "S3Reader", FakeReader)
    monkeypatch.setattr(pl, "aws_session_for_org", lambda org: None)
    monkeypatch.setattr(pl, "parse_lines", lambda *a, **k: [dict(r) for r in RECORDS])
    monkeypatch.setattr(pl, "ExplanationCache", lambda *a, **k: None)
    monkeypatch.setattr(pl, "_build_intel_client", lambda redis_conn: None)
    monkeypatch.setattr(push_blocks.push_block, "delay", lambda *args: pushed.append(args))

    def go(org, confidence=0.9, endpoint="/api/login", agents=("AuthAgent",)):
        monkeypatch.setattr(pl, "PipelineRunner", _runner_class(confidence, endpoint, agents))
        result = pl.process_logs(org.id)
        assert result["status"] == "ok", result
        db.expire_all()
        return pushed, db.query(Verdict).filter(Verdict.org_id == org.id).all()

    return go


def _org(db, **extra):
    fields = {
        "tier": "growth", "s3_bucket": "b", "log_format": "apigw", "auto_block_enabled": True,
        "blocking_tos_accepted_at": NOW,
    }
    fields.update(extra)
    return make_org(db, **fields)


def test_confident_verdict_is_pushed_at_the_default_threshold(db, run_task):
    org = _org(db)
    pushed, verdicts = run_task(org, confidence=0.80)
    assert len(verdicts) == 1
    assert pushed == [(verdicts[0].id, org.id, 0.75)]
    assert verdicts[0].would_have_blocked_at is None


def test_verdict_below_the_default_threshold_is_not_pushed(db, run_task):
    pushed, verdicts = run_task(_org(db), confidence=0.70)
    assert len(verdicts) == 1
    assert pushed == []
    assert verdicts[0].would_have_blocked_at is None


def test_dry_run_stamps_the_verdict_and_pushes_nothing(db, run_task):
    pushed, verdicts = run_task(_org(db, auto_block_dry_run=True), confidence=0.80)
    assert pushed == []
    assert verdicts[0].would_have_blocked_at is not None
    assert verdicts[0].blocked is False


def test_dry_run_does_not_stamp_a_verdict_below_the_threshold(db, run_task):
    pushed, verdicts = run_task(_org(db, auto_block_dry_run=True), confidence=0.70)
    assert pushed == []
    assert verdicts[0].would_have_blocked_at is None


def test_dry_run_is_inert_when_auto_block_is_off(db, run_task):
    pushed, verdicts = run_task(_org(db, auto_block_dry_run=True, auto_block_enabled=False), confidence=0.90)
    assert pushed == []
    assert verdicts[0].would_have_blocked_at is None


def test_dry_run_is_inert_without_the_agreement(db, run_task):
    pushed, verdicts = run_task(_org(db, auto_block_dry_run=True, blocking_tos_accepted_at=None), confidence=0.90)
    assert pushed == []
    assert verdicts[0].would_have_blocked_at is None


def test_non_blocking_tier_never_stamps_or_pushes(db, run_task):
    pushed, verdicts = run_task(_org(db, tier="basic", auto_block_dry_run=True), confidence=0.90)
    assert pushed == []
    assert verdicts[0].would_have_blocked_at is None


def test_pro_block_threshold_is_used_for_the_gate_and_passed_to_push(db, run_task):
    org = _org(db, tier="pro", detection_config={"block_confidence_threshold": 0.65})
    pushed, verdicts = run_task(org, confidence=0.70)
    assert pushed == [(verdicts[0].id, org.id, 0.65)]


def test_pro_stricter_block_threshold_withholds_the_block(db, run_task):
    org = _org(db, tier="pro", detection_config={"block_confidence_threshold": 0.90})
    pushed, verdicts = run_task(org, confidence=0.85)
    assert len(verdicts) == 1
    assert pushed == []


def test_growth_config_is_ignored(db, run_task):
    org = _org(db, tier="growth", detection_config={"block_confidence_threshold": 0.50})
    pushed, verdicts = run_task(org, confidence=0.70)
    assert pushed == []


def test_endpoint_minimum_drops_a_weaker_detection(db, run_task):
    org = _org(db, tier="pro", detection_config={"endpoint_thresholds": [{"pattern": "/api/login", "min_confidence": 0.95}]})
    pushed, verdicts = run_task(org, confidence=0.90)
    assert verdicts == []
    assert pushed == []


def test_endpoint_minimum_keeps_a_stronger_detection(db, run_task):
    org = _org(db, tier="pro", detection_config={"endpoint_thresholds": [{"pattern": "/api/login", "min_confidence": 0.85}]})
    pushed, verdicts = run_task(org, confidence=0.90)
    assert len(verdicts) == 1
    assert len(pushed) == 1


# Phase 14 (F-014): a verdict whose only evidence is GeoIPAgent is alert-only.

def test_a_geoip_only_verdict_is_never_auto_blocked_but_is_still_recorded(db, run_task):
    pushed, verdicts = run_task(_org(db), confidence=0.80, agents=("GeoIPAgent",))
    assert len(verdicts) == 1
    assert pushed == []
    assert verdicts[0].would_have_blocked_at is None


def test_a_geoip_only_verdict_is_not_stamped_by_dry_run(db, run_task):
    pushed, verdicts = run_task(_org(db, auto_block_dry_run=True), confidence=0.80, agents=("GeoIPAgent",))
    assert pushed == []
    assert verdicts[0].would_have_blocked_at is None


def test_a_verdict_with_geoip_plus_another_agent_still_auto_blocks(db, run_task):
    pushed, verdicts = run_task(_org(db), confidence=0.80, agents=("GeoIPAgent", "AuthAgent"))
    assert len(pushed) == 1
