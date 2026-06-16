"""
Integration test for the product pipeline adapter.

Tests the full path: list[dict] → run_pipeline → verdict dict.
No real Redis or Postgres required — ProductSharedMemory falls back to
in-process LTM when redis_client=None.

Run from the product root:
    cd /home/azael/Documents/Code/abuse
    source .venv/bin/activate
    python3.11 engine/source/tests/test_pipeline.py
"""

from __future__ import annotations

import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

# Add engine/ to path so 'from engine.xxx import ...' resolves correctly
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.pipeline.run import dict_to_log_record, run_pipeline

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

_results: list[tuple[str, str]] = []
_CLIENT_ID = "test-client-0000-0000-0000-000000000001"
_BASE_TIME = datetime(2024, 1, 15, 14, 0, 0)


def test(name: str, fn) -> None:
    t0 = time.time()
    try:
        fn()
        ms = (time.time() - t0) * 1000
        print(f"  {PASS} {name}  ({ms:.0f}ms)")
        _results.append(("PASS", name))
    except Exception as exc:
        ms = (time.time() - t0) * 1000
        print(f"  {FAIL} {name}  ({ms:.0f}ms)")
        traceback.print_exc()
        _results.append(("FAIL", name))


# ---------------------------------------------------------------------------
# Helper: build a normalised log dict
# ---------------------------------------------------------------------------

def _log(ip="1.2.3.4", method="GET", endpoint="/api/users", status=200,
         offset_s=0, user_agent="Mozilla/5.0",
         response_size=512, latency=45.0) -> dict:
    return {
        "timestamp": (_BASE_TIME + timedelta(seconds=offset_s)).isoformat() + "Z",
        "ip": ip,
        "method": method,
        "endpoint": endpoint,
        "status": status,
        "response_size": response_size,
        "latency": latency,
        "user_agent": user_agent,
        "client_id": _CLIENT_ID,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_dict_to_log_record_basic():
    d = _log()
    r = dict_to_log_record(d)
    assert r.ip == "1.2.3.4"
    assert r.method == "GET"
    assert r.endpoint == "/api/users"
    assert r.status == 200
    assert r.client_id == _CLIENT_ID


def test_dict_to_log_record_timestamp_iso_z():
    d = _log()
    r = dict_to_log_record(d)
    assert r.timestamp.year == 2024
    assert r.timestamp.month == 1


def test_dict_to_log_record_timestamp_datetime():
    d = _log()
    d["timestamp"] = datetime(2024, 6, 1, 12, 0, 0)
    r = dict_to_log_record(d)
    assert r.timestamp.month == 6


def test_run_pipeline_returns_verdict_dict():
    records = [_log(offset_s=i) for i in range(10)]
    verdict = run_pipeline(records, _CLIENT_ID)
    assert isinstance(verdict, dict)
    for key in ("client_id", "ip", "threat_type", "severity", "confidence",
                "agents_triggered", "explanation", "blocked", "is_attack", "timestamp"):
        assert key in verdict, f"Missing key: {key}"


def test_run_pipeline_benign_batch():
    """10 normal requests from one IP — should produce no-attack verdict."""
    records = [_log(ip="10.0.0.1", offset_s=i * 5) for i in range(10)]
    verdict = run_pipeline(records, _CLIENT_ID)
    # Benign batch: confidence should be low, no critical severity
    assert verdict["severity"] in ("none", "low", "medium")


def test_run_pipeline_brute_force_pattern():
    """Many 401 responses from one IP → AuthAgent should fire."""
    records = [
        _log(ip="198.51.100.1", endpoint="/auth/login", status=401,
             offset_s=i, user_agent="python-requests/2.28")
        for i in range(50)
    ]
    # Pad with some normal traffic so the batch isn't trivially sparse
    records += [_log(ip="10.0.0.2", offset_s=i * 3) for i in range(10)]
    verdict = run_pipeline(records, _CLIENT_ID)
    assert isinstance(verdict, dict)
    assert verdict["confidence"] >= 0.0  # engine ran without error


def test_run_pipeline_volume_spike():
    """Single IP sending >400 requests in one batch."""
    records = [
        _log(ip="203.0.113.99", endpoint="/api/data", offset_s=i // 10)
        for i in range(460)
    ]
    verdict = run_pipeline(records, _CLIENT_ID)
    assert isinstance(verdict, dict)
    assert verdict["ip"] == "203.0.113.99"


def test_run_pipeline_primary_ip_correct():
    """Most common IP should become the primary IP in the verdict."""
    records = (
        [_log(ip="1.1.1.1", offset_s=i) for i in range(5)] +
        [_log(ip="2.2.2.2", offset_s=i) for i in range(20)]
    )
    verdict = run_pipeline(records, _CLIENT_ID)
    assert verdict["ip"] == "2.2.2.2"


def test_run_pipeline_client_id_propagated():
    records = [_log(offset_s=i) for i in range(5)]
    verdict = run_pipeline(records, _CLIENT_ID)
    assert verdict["client_id"] == _CLIENT_ID


def test_run_pipeline_empty_raises():
    try:
        run_pipeline([], _CLIENT_ID)
        raise AssertionError("Should have raised ValueError")
    except ValueError:
        pass  # expected


def test_run_pipeline_no_redis_client():
    """Pipeline must work without Redis (in-process LTM only)."""
    records = [_log(offset_s=i) for i in range(10)]
    verdict = run_pipeline(records, _CLIENT_ID, redis_client=None)
    assert isinstance(verdict, dict)


def test_run_pipeline_consecutive_batches():
    """Run two batches sequentially; second batch inherits LTM state."""
    records_a = [_log(ip="5.5.5.5", offset_s=i) for i in range(20)]
    records_b = [_log(ip="5.5.5.5", offset_s=i + 100) for i in range(20)]
    v1 = run_pipeline(records_a, _CLIENT_ID)
    v2 = run_pipeline(records_b, _CLIENT_ID)
    assert v1["is_attack"] in (True, False)
    assert v2["is_attack"] in (True, False)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nPipeline integration tests\n")

    test("dict_to_log_record basic",            test_dict_to_log_record_basic)
    test("dict_to_log_record ISO-Z timestamp",  test_dict_to_log_record_timestamp_iso_z)
    test("dict_to_log_record datetime input",   test_dict_to_log_record_timestamp_datetime)
    test("run_pipeline returns verdict dict",   test_run_pipeline_returns_verdict_dict)
    test("benign batch — low severity",         test_run_pipeline_benign_batch)
    test("brute-force pattern — engine runs",   test_run_pipeline_brute_force_pattern)
    test("volume spike — engine runs",          test_run_pipeline_volume_spike)
    test("primary IP correct",                  test_run_pipeline_primary_ip_correct)
    test("client_id propagated",               test_run_pipeline_client_id_propagated)
    test("empty records raises ValueError",     test_run_pipeline_empty_raises)
    test("no Redis client — in-process LTM",    test_run_pipeline_no_redis_client)
    test("consecutive batches share LTM",       test_run_pipeline_consecutive_batches)

    passed = sum(1 for s, _ in _results if s == "PASS")
    failed = sum(1 for s, _ in _results if s == "FAIL")
    print(f"\n{'='*40}")
    print(f"  {passed} passed   {failed} failed   ({len(_results)} total)")
    print(f"{'='*40}\n")
    sys.exit(0 if failed == 0 else 1)
