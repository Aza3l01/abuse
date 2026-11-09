"""Hard monthly call-volume cap in process_logs: at the cap nothing is scanned,
and a poll that would cross it is cut off exactly at the cap. Uses the same
fakes as test_phase8_gate (engine, S3 and Redis replaced).
"""
from __future__ import annotations

import pytest

import workers.tasks.process_logs as pl
from api.tests.billing_testkit import make_org
from api.tiers import CALL_VOLUME_CAPS
from workers.tests.test_phase8_gate import RECORDS, FakeReader, FakeRedis

CAP = CALL_VOLUME_CAPS["free"]


class CountingRunner:
    batches: list[int] = []
    constructed = 0

    def __init__(self, *args, **kwargs):
        CountingRunner.constructed += 1
        self.llm_calls_used = 0

    def run(self, batch, mode="window"):
        CountingRunner.batches.append(len(batch))
        return {"is_attack": False}

    def flush(self):
        pass


@pytest.fixture
def run_task(db, session_factory, monkeypatch):
    CountingRunner.batches = []
    CountingRunner.constructed = 0
    monkeypatch.setattr(pl, "SessionLocal", session_factory)
    monkeypatch.setattr(pl, "_get_redis", lambda: FakeRedis())
    monkeypatch.setattr(pl, "S3Reader", FakeReader)
    monkeypatch.setattr(pl, "aws_session_for_org", lambda org: None)
    monkeypatch.setattr(pl, "parse_lines", lambda *a, **k: [dict(r) for r in RECORDS])
    monkeypatch.setattr(pl, "ExplanationCache", lambda *a, **k: None)
    monkeypatch.setattr(pl, "_build_intel_client", lambda redis_conn: None)
    monkeypatch.setattr(pl, "PipelineRunner", CountingRunner)
    monkeypatch.setattr(pl, "_persist_scan_run", lambda *a, **k: None)
    monkeypatch.setattr(pl, "_upsert_ip_memory", lambda *a, **k: None)

    def go(org):
        result = pl.process_logs(org.id)
        db.expire_all()
        return result

    return go


def _org(db, **extra):
    fields = {"tier": "free", "s3_bucket": "b", "log_format": "apigw", "last_processed_key": "logs/old"}
    fields.update(extra)
    return make_org(db, **fields)


def test_at_the_cap_nothing_is_scanned_and_the_cursor_moves_on(db, run_task):
    org = _org(db, monthly_requests_processed=CAP)
    result = run_task(org)
    assert result["note"] == "volume_cap_reached"
    assert CountingRunner.constructed == 0
    assert org.monthly_requests_processed == CAP
    assert org.last_processed_key == "logs/a"
    assert org.last_scan_status == "paused"


def test_a_poll_crossing_the_cap_is_cut_off_exactly_at_the_cap(db, run_task):
    org = _org(db, monthly_requests_processed=CAP - 3)
    result = run_task(org)
    assert result["status"] == "ok"
    assert sum(CountingRunner.batches) == 3
    assert org.monthly_requests_processed == CAP
    assert org.quota_exceeded_sent_at is not None
    assert org.last_scan_status == "success"


def test_under_the_cap_the_whole_poll_is_scanned(db, run_task):
    org = _org(db, monthly_requests_processed=0)
    run_task(org)
    assert sum(CountingRunner.batches) == len(RECORDS)
    assert org.monthly_requests_processed == len(RECORDS)


def test_enterprise_has_no_cap(db, run_task):
    org = _org(db, tier="enterprise", monthly_requests_processed=10**10)
    run_task(org)
    assert sum(CountingRunner.batches) == len(RECORDS)


def test_upgrading_lifts_the_cap(db, run_task):
    org = _org(db, tier="starter", monthly_requests_processed=CAP)
    run_task(org)
    assert sum(CountingRunner.batches) == len(RECORDS)
    assert org.last_scan_status == "success"
