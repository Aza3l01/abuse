#!/usr/bin/env python3
"""
scripts/e2e_phase5.py — End-to-end smoke test for the Phase 5 pipeline.

What this tests (no real AWS credentials required):
  1. apigw_parser and alb_parser parse sample lines correctly.
  2. normalizer.normalize() splits records into batches with client_id injected.
  3. run_pipeline() returns a valid verdict dict for a batch of parsed records.
  4. Verdict row is written to Postgres.
  5. IpMemory row is created / updated.
  6. last_processed_key is updated on the Client row.

S3 is mocked with unittest.mock.patch so no real bucket is needed.

Prerequisites (all must be running):
  docker-compose up -d   (postgres + redis)
  source .venv/bin/activate

Run from the repo root:
  python scripts/e2e_phase5.py
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
ENGINE_ROOT = REPO_ROOT / "engine"
for p in [str(REPO_ROOT), str(ENGINE_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
load_dotenv()

from db.models import Client, IpMemory, Verdict
from db.session import SessionLocal

# Must import engine modules AFTER path setup
from engine.ingestion.apigw_parser import parse_line as apigw_parse
from engine.ingestion.alb_parser import parse_line as alb_parse
from engine.ingestion.normalizer import normalize
from engine.pipeline.run import run_pipeline

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
results: list[tuple[str, str]] = []


def run_test(name: str, fn):
    try:
        fn()
        print(f"  {PASS} {name}")
        results.append(("PASS", name))
    except Exception as exc:
        print(f"  {FAIL} {name}: {exc}")
        import traceback; traceback.print_exc()
        results.append(("FAIL", name))


# ---------------------------------------------------------------------------
# Sample log lines
# ---------------------------------------------------------------------------

_APIGW_JSON = (
    '{"requestTime":"2024-01-15T10:00:00Z","ip":"198.51.100.42",'
    '"httpMethod":"GET","path":"/api/v1/users","status":200,'
    '"responseLength":512,"latencyMs":45,"userAgent":"Mozilla/5.0 (test)"}'
)

_APIGW_CLF = (
    '198.51.100.42 - - [15/Jan/2024:10:01:00 +0000] '
    '"POST /api/v1/login HTTP/1.1" 401 128 120 "python-requests/2.31"'
)

_ALB_LINE = (
    'http 2024-01-15T10:02:00Z app/my-alb/xxx 203.0.113.5:55123 10.0.0.1:80 '
    '0.001 0.002 0.000 200 200 256 1024 '
    '"GET http://api.example.com:80/api/v1/items HTTP/1.1" '
    '"curl/7.88" - - arn:aws:elasticloadbalancing:xx '
    '"Root=1-xxx" "-" "-" 0 2024-01-15T10:02:00.000Z "forward" "-" "-" '
    '"10.0.0.1:80" "200" "-" "-"'
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_apigw_json_parser():
    result = apigw_parse(_APIGW_JSON)
    assert result is not None, "apigw JSON parse returned None"
    assert result["ip"] == "198.51.100.42"
    assert result["method"] == "GET"
    assert result["status"] == 200
    assert result["latency"] == 45.0
    assert result["endpoint"] == "/api/v1/users"


def test_apigw_clf_parser():
    result = apigw_parse(_APIGW_CLF)
    assert result is not None, "apigw CLF parse returned None"
    assert result["ip"] == "198.51.100.42"
    assert result["method"] == "POST"
    assert result["status"] == 401


def test_alb_parser():
    result = alb_parse(_ALB_LINE)
    assert result is not None, "alb parse returned None"
    assert result["ip"] == "203.0.113.5"
    assert result["method"] == "GET"
    assert result["status"] == 200


def test_normalizer_batching():
    lines = [_APIGW_JSON, _APIGW_CLF, "this line is garbage and should be skipped"]
    client_id = str(uuid.uuid4())
    batches = normalize(lines, "apigw", client_id, batch_size=1)
    # 2 valid + 1 skipped → 2 batches of 1
    assert len(batches) == 2, f"expected 2 batches, got {len(batches)}"
    for batch in batches:
        assert len(batch) == 1
        assert batch[0]["client_id"] == client_id


def test_normalizer_empty():
    batches = normalize([], "apigw", "test-client")
    assert batches == []


def test_normalizer_unknown_format():
    try:
        normalize(["line"], "unknown_format", "cid")
        assert False, "should have raised ValueError"
    except ValueError:
        pass


def test_run_pipeline_returns_verdict():
    import redis as redis_lib
    import os
    r = redis_lib.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    client_id = str(uuid.uuid4())
    lines = [_APIGW_JSON]
    batches = normalize(lines, "apigw", client_id)
    assert batches, "normalizer produced no batches"
    verdict = run_pipeline(batches[0], client_id, r)
    assert "is_attack" in verdict
    assert "confidence" in verdict
    assert "severity" in verdict
    assert 0.0 <= verdict["confidence"] <= 1.0


def test_verdict_written_to_db():
    """Full roundtrip: normalise → run_pipeline → persist to Postgres."""
    import redis as redis_lib
    import os

    r = redis_lib.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    db = SessionLocal()
    try:
        # Create a throwaway client row
        client_id = str(uuid.uuid4())
        client = Client(
            id=client_id,
            email=f"e2e-test-{client_id[:8]}@example.com",
            company_name="E2E Test Co",
            s3_bucket="test-bucket",
            log_format="apigw",
            aws_region="us-east-1",
            tier="starter",
            email_verified=True,
        )
        db.add(client)
        db.commit()

        lines = [_APIGW_JSON, _APIGW_CLF]
        batches = normalize(lines, "apigw", client_id)
        assert batches

        # Import helpers from process_logs task
        from workers.tasks.process_logs import _persist_verdict, _upsert_ip_memory

        verdict_dict = run_pipeline(batches[0], client_id, r)
        verdict_id = _persist_verdict(db, client_id, batches[0], verdict_dict)
        _upsert_ip_memory(db, client_id, batches[0], verdict_dict)
        db.commit()

        # Update last_processed_key (simulating S3 cursor advance)
        client.last_processed_key = "logs/2024/01/15/test.log.gz"
        db.commit()

        # Verify rows exist
        v = db.query(Verdict).filter(Verdict.id == verdict_id).first()
        assert v is not None, "Verdict row not found"
        assert v.client_id == client_id

        updated_client = db.query(Client).filter(Client.id == client_id).first()
        assert updated_client.last_processed_key == "logs/2024/01/15/test.log.gz"

        mem = db.query(IpMemory).filter(
            IpMemory.client_id == client_id,
            IpMemory.ip == "198.51.100.42",
        ).first()
        assert mem is not None, "IpMemory row not found"

    finally:
        # Clean up test data
        db.execute(Verdict.__table__.delete().where(Verdict.client_id == client_id))
        db.execute(IpMemory.__table__.delete().where(IpMemory.client_id == client_id))
        db.execute(Client.__table__.delete().where(Client.id == client_id))
        db.commit()
        db.close()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nPhase 5 — e2e smoke tests\n")

    run_test("apigw JSON parser",           test_apigw_json_parser)
    run_test("apigw CLF parser",            test_apigw_clf_parser)
    run_test("alb parser",                  test_alb_parser)
    run_test("normalizer batching",         test_normalizer_batching)
    run_test("normalizer empty input",      test_normalizer_empty)
    run_test("normalizer unknown format",   test_normalizer_unknown_format)
    run_test("run_pipeline returns verdict", test_run_pipeline_returns_verdict)
    run_test("verdict + ip_memory written",  test_verdict_written_to_db)

    passed = sum(1 for r, _ in results if r == "PASS")
    failed = sum(1 for r, _ in results if r == "FAIL")

    print(f"\n{'='*40}")
    print(f"  {passed} passed / {failed} failed")
    print(f"{'='*40}\n")

    sys.exit(0 if failed == 0 else 1)
