"""Phase 12b: a customer pause of scanning in the worker. A paused org is not
dispatched, and a task that was already queued skips it before touching any
scan state. After a resume the next scan reads only what arrived since the
resume (the backlog from the pause is skipped), then the normal cursor takes
over again. Uses the same fakes as test_volume_cap.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import workers.tasks.process_logs as pl
from api.tests.billing_testkit import make_org
from api.tiers import CALL_VOLUME_CAPS
from workers.tests.test_phase8_gate import RECORDS, FakeRedis

CAP = CALL_VOLUME_CAPS["starter"]


class RecordingReader:
    listed: list[tuple] = []

    def __init__(self, *args, **kwargs):
        pass

    def list_objects_since(self, cutoff):
        RecordingReader.listed.append(("since", cutoff))
        return [{"Key": "logs/live"}]

    def list_new_objects(self):
        RecordingReader.listed.append(("new", None))
        return [{"Key": "logs/live"}]

    def iter_lines(self, objects):
        for i in range(len(RECORDS)):
            yield "logs/live", f"line{i}"


class CountingRunner:
    constructed = 0

    def __init__(self, *args, **kwargs):
        CountingRunner.constructed += 1
        self.llm_calls_used = 0

    def run(self, batch, mode="window"):
        return {"is_attack": False}

    def flush(self):
        pass


@pytest.fixture
def run_task(db, session_factory, monkeypatch):
    RecordingReader.listed = []
    CountingRunner.constructed = 0
    monkeypatch.setattr(pl, "SessionLocal", session_factory)
    monkeypatch.setattr(pl, "_get_redis", lambda: FakeRedis())
    monkeypatch.setattr(pl, "S3Reader", RecordingReader)
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
    fields = {"tier": "starter", "s3_bucket": "b", "log_format": "apigw", "last_processed_key": "logs/old"}
    fields.update(extra)
    return make_org(db, **fields)


def _paused(db, **extra):
    return _org(db, scanning_paused_at=datetime.now(timezone.utc), **extra)


def test_the_dispatcher_skips_a_paused_org(db, session_factory, monkeypatch):
    dispatched = []
    monkeypatch.setattr(pl, "SessionLocal", session_factory)
    monkeypatch.setattr(pl.process_logs, "delay", lambda org_id: dispatched.append(org_id))
    monkeypatch.setattr(pl, "ping_heartbeat", lambda name: None)
    running = _org(db, name="Running")
    _paused(db, name="Paused")
    result = pl.poll_all_clients()
    assert dispatched == [running.id]
    assert result == {"dispatched": 1}


def test_a_queued_task_for_a_paused_org_is_skipped_untouched(db, run_task):
    org = _paused(db, last_scan_status="success", monthly_requests_processed=77)
    result = run_task(org)
    assert result == {"status": "skipped", "reason": "paused"}
    assert CountingRunner.constructed == 0
    assert RecordingReader.listed == []
    assert org.last_scan_status == "success"
    assert org.last_scan_started_at is None
    assert org.last_processed_key == "logs/old"
    assert org.monthly_requests_processed == 77


def test_the_user_pause_beats_the_volume_cap(db, run_task):
    org = _paused(db, monthly_requests_processed=CAP, last_scan_status="success")
    result = run_task(org)
    assert result["reason"] == "paused"
    assert org.last_scan_status == "success"
    assert org.last_processed_key == "logs/old"
    assert org.monthly_requests_processed == CAP


def test_the_counter_is_unchanged_across_a_pause_and_counts_again_after_resume(db, run_task):
    org = _paused(db, monthly_requests_processed=10)
    run_task(org)
    assert org.monthly_requests_processed == 10
    org.scanning_paused_at = None
    org.scanning_resumed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()
    run_task(org)
    assert org.monthly_requests_processed == 10 + len(RECORDS)


def test_after_a_resume_only_objects_since_the_resume_are_read(db, run_task):
    resumed = datetime.now(timezone.utc) - timedelta(minutes=5)
    org = _org(db, scanning_resumed_at=resumed)
    run_task(org)
    assert RecordingReader.listed == [("since", resumed)]
    assert org.last_processed_key == "logs/live"
    assert org.scanning_resumed_at is None
    assert org.last_scan_status == "success"


def test_the_next_scan_after_a_resume_uses_the_normal_cursor_again(db, run_task):
    org = _org(db, scanning_resumed_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    run_task(org)
    run_task(org)
    assert [kind for kind, _ in RecordingReader.listed] == ["since", "new"]


def test_an_org_never_paused_uses_the_normal_cursor(db, run_task):
    org = _org(db)
    run_task(org)
    assert [kind for kind, _ in RecordingReader.listed] == ["new"]


def test_resume_before_the_first_scan_never_reads_older_than_the_resume(db, run_task):
    resumed = datetime.now(timezone.utc) - timedelta(hours=1)
    org = _org(db, last_processed_key=None, scanning_resumed_at=resumed)
    run_task(org)
    assert RecordingReader.listed[0] == ("since", resumed)
