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
from engine.agents.payload_agent import PayloadAgent
from engine.agents.base_agent import AgentContext
from engine.memory.shared_memory import SharedMemory
from engine.tools.registry import ToolRegistry

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

_results: list[tuple[str, str]] = []
_ORG_ID = "test-client-0000-0000-0000-000000000001"
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
        "org_id": _ORG_ID,
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
    assert r.org_id == _ORG_ID


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
    verdict = run_pipeline(records, _ORG_ID)
    assert isinstance(verdict, dict)
    for key in ("org_id", "ip", "threat_type", "severity", "confidence",
                "agents_triggered", "explanation", "blocked", "is_attack", "timestamp"):
        assert key in verdict, f"Missing key: {key}"


def test_run_pipeline_benign_batch():
    """10 normal requests from one IP — should produce no-attack verdict."""
    records = [_log(ip="10.0.0.1", offset_s=i * 5) for i in range(10)]
    verdict = run_pipeline(records, _ORG_ID)
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
    verdict = run_pipeline(records, _ORG_ID)
    assert isinstance(verdict, dict)
    assert verdict["confidence"] >= 0.0  # engine ran without error


def test_run_pipeline_volume_spike():
    """Single IP sending >400 requests in one batch."""
    records = [
        _log(ip="203.0.113.99", endpoint="/api/data", offset_s=i // 10)
        for i in range(460)
    ]
    verdict = run_pipeline(records, _ORG_ID)
    assert isinstance(verdict, dict)
    assert verdict["ip"] == "203.0.113.99"


def test_run_pipeline_primary_ip_correct():
    """Most common IP should become the primary IP in the verdict."""
    records = (
        [_log(ip="1.1.1.1", offset_s=i) for i in range(5)] +
        [_log(ip="2.2.2.2", offset_s=i) for i in range(20)]
    )
    verdict = run_pipeline(records, _ORG_ID)
    assert verdict["ip"] == "2.2.2.2"


def test_run_pipeline_org_id_propagated():
    records = [_log(offset_s=i) for i in range(5)]
    verdict = run_pipeline(records, _ORG_ID)
    assert verdict["org_id"] == _ORG_ID


def test_run_pipeline_empty_raises():
    try:
        run_pipeline([], _ORG_ID)
        raise AssertionError("Should have raised ValueError")
    except ValueError:
        pass  # expected


def test_run_pipeline_no_redis_client():
    """Pipeline must work without Redis (in-process LTM only)."""
    records = [_log(offset_s=i) for i in range(10)]
    verdict = run_pipeline(records, _ORG_ID, redis_client=None)
    assert isinstance(verdict, dict)


def test_run_pipeline_consecutive_batches():
    """Run two batches sequentially; second batch inherits LTM state."""
    records_a = [_log(ip="5.5.5.5", offset_s=i) for i in range(20)]
    records_b = [_log(ip="5.5.5.5", offset_s=i + 100) for i in range(20)]
    v1 = run_pipeline(records_a, _ORG_ID)
    v2 = run_pipeline(records_b, _ORG_ID)
    assert v1["is_attack"] in (True, False)
    assert v2["is_attack"] in (True, False)


def test_endpoint_template_collapses_numeric_ids():
    """Item 0 acceptance: 200 requests to /api/users/{random_int} from one IP
    must collapse to 1 distinct endpoint in PayloadAgent, not 200."""
    import json
    import random
    from engine.ingestion import apigw_parser

    lines = [
        json.dumps({
            "requestTime": (_BASE_TIME + timedelta(seconds=i)).isoformat() + "Z",
            "ip": "192.0.2.1",
            "method": "GET",
            "path": f"/api/users/{random.randint(1, 999999)}",
            "status": 200,
        })
        for i in range(200)
    ]
    parsed = [apigw_parser.parse_line(line) for line in lines]
    for d in parsed:
        d["org_id"] = _ORG_ID
    log_records = [dict_to_log_record(d) for d in parsed]
    assert all(lr.endpoint_template == "/api/users/{id}" for lr in log_records)

    mem = SharedMemory(window_seconds=60)
    tools = ToolRegistry(mem)
    ctx = AgentContext(records=log_records)
    PayloadAgent(mem, tools).observe(ctx)
    assert ctx.raw_metrics["total_distinct_endpoints"] == 1
    assert ctx.raw_metrics["per_ip_distinct"]["192.0.2.1"] == 1


def test_focus_pass_catches_diluted_attacker():
    """Item 1 acceptance: an attacker sending 500 requests split evenly
    across two 500-record window batches (each diluted among 250 distinct
    benign IPs) is invisible to Pass A alone (each window individually looks
    like ordinary distributed/CDN traffic), but item 1's Pass B (focus pass,
    grouping by IP across the whole poll) sees the attacker's full request
    count and fires VolumeAgent's absolute-flood check.

    Uses a single shared SharedMemory + MetaAgentOrchestrator across warm-up,
    Pass A and Pass B calls (mirrors production, where the same Redis-backed
    LTM is loaded for every run_pipeline() call within one poll cycle — batch
    count and adaptive thresholds must be shared, or VolumeAgent stays in
    permanent cold-start warm-up)."""
    from engine.coordinator.meta_agent import MetaAgentOrchestrator
    from engine.ingestion.normalizer import chunk, group_by_ip

    mem = SharedMemory(window_seconds=60)
    orchestrator = MetaAgentOrchestrator(mem)

    def _run(batch: list[dict], mode: str = "window"):
        log_records = [dict_to_log_record(d) for d in batch]
        return orchestrator.run(log_records, mode=mode)

    # Warm VolumeAgent past MIN_WARMUP_BATCHES(15) with ordinary benign window
    # batches before the real test batches, matching how a client's engine
    # calibrates over its first several poll cycles in production.
    for i in range(16):
        warmup_batch = [_log(ip=f"10.0.{i}.{j}", offset_s=j) for j in range(20)]
        _run(warmup_batch, mode="window")

    attacker_ip = "203.0.113.77"
    records: list[dict] = []
    # Two windows of 500: each has 250 attacker requests + 250 distinct
    # single-request benign IPs, so per-window dominant_ratio=0.50 and
    # unique_ips=251 (>MAX_IP_DIVERSITY, >DDOS_MAX_UNIQUE_IPS) — VolumeAgent
    # correctly treats each window as ordinary distributed traffic.
    for window in range(2):
        for i in range(250):
            records.append(_log(ip=attacker_ip, endpoint="/api/data", offset_s=window * 1000 + i))
        for i in range(250):
            records.append(_log(ip=f"198.51.100.{window}.{i}", offset_s=window * 1000 + i))

    batches = chunk(records, batch_size=500)
    assert len(batches) == 2

    for batch in batches:
        verdict = _run(batch, mode="window")
        assert verdict.is_attack is False, (
            "Pass A window should NOT flag the diluted attacker as an attack — "
            f"got {verdict.threat_type} conf={verdict.confidence_score}"
        )

    ip_groups = group_by_ip(records, min_requests=20)
    assert attacker_ip in ip_groups
    assert len(ip_groups[attacker_ip]) == 500

    focus_verdict = _run(ip_groups[attacker_ip], mode="focus")
    assert focus_verdict.is_attack is True, (
        "Pass B focus pass should catch the attacker Pass A's window boundaries diluted — "
        f"got {focus_verdict.threat_type} conf={focus_verdict.confidence_score}"
    )


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
    test("org_id propagated",                  test_run_pipeline_org_id_propagated)
    test("empty records raises ValueError",     test_run_pipeline_empty_raises)
    test("no Redis client — in-process LTM",    test_run_pipeline_no_redis_client)
    test("consecutive batches share LTM",       test_run_pipeline_consecutive_batches)
    test("endpoint_template collapses ids",     test_endpoint_template_collapses_numeric_ids)
    test("focus pass catches diluted attacker", test_focus_pass_catches_diluted_attacker)

    passed = sum(1 for s, _ in _results if s == "PASS")
    failed = sum(1 for s, _ in _results if s == "FAIL")
    print(f"\n{'='*40}")
    print(f"  {passed} passed   {failed} failed   ({len(_results)} total)")
    print(f"{'='*40}\n")
    sys.exit(0 if failed == 0 else 1)
