"""
workers/tests/test_process_logs.py — regression test for item 5c
(wrong-IP attribution in process_logs.py).

_persist_verdict() and _upsert_ip_memory() used to read ip/method/endpoint
from batch[0] instead of the pipeline's own verdict_dict attribution. Since
batch[0] is just whichever record was parsed first, an innocent bystander's
IP could end up persisted (and pushed to the customer's own WAF/Cloudflare
block list) instead of the actual attacker's IP.

No real DB is needed here — both functions only ever call db.add()/db.query()
on the constructed Verdict/IpMemory objects, so a minimal fake session is
enough to observe what gets built without touching Postgres.

Run from the product root:
    cd /home/azael/Documents/Code/abuse
    source .venv/bin/activate
    python3 workers/tests/test_process_logs.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from workers.tasks.process_logs import _persist_scan_run, _persist_verdict, _upsert_ip_memory

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
_results: list[tuple[str, str]] = []


def test(name: str, fn) -> None:
    try:
        fn()
        print(f"  {PASS} {name}")
        _results.append(("PASS", name))
    except Exception:
        print(f"  {FAIL} {name}")
        traceback.print_exc()
        _results.append(("FAIL", name))


class _FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None


class _FakeDB:
    """Duck-types just enough of a SQLAlchemy Session for these two helpers."""

    def __init__(self):
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    def query(self, *args, **kwargs):
        return _FakeQuery()


_ATTACKER_IP = "198.51.100.7"
_BYSTANDER_IP = "10.0.0.1"


def _batch_with_benign_first_attacker_dominant() -> list[dict]:
    """First record is an innocent bystander; the rest of the batch is the attacker."""
    return [
        {"timestamp": "2024-01-15T14:00:00Z", "ip": _BYSTANDER_IP,
         "method": "GET", "endpoint": "/home"},
    ] + [
        {"timestamp": f"2024-01-15T14:00:{i:02d}Z", "ip": _ATTACKER_IP,
         "method": "POST", "endpoint": "/login"}
        for i in range(1, 50)
    ]


def test_persist_verdict_uses_attacker_ip_not_batch_zero():
    batch = _batch_with_benign_first_attacker_dominant()
    verdict_dict = {
        "ip": _ATTACKER_IP, "method": "POST", "endpoint": "/login",
        "threat_type": "BRUTE_FORCE", "severity": "critical", "confidence": 0.95,
        "agents_triggered": ["AuthAgent"], "explanation": "brute force",
        "cost_prevented": 0.0,
    }
    db = _FakeDB()
    _persist_verdict(db, "client-1", batch, verdict_dict)
    assert len(db.added) == 1
    v = db.added[0]
    assert v.ip == _ATTACKER_IP, f"expected attacker IP, got {v.ip}"
    assert v.ip != batch[0]["ip"]
    assert v.method == "POST"
    assert v.endpoint == "/login"


def test_upsert_ip_memory_uses_attacker_ip_not_batch_zero():
    batch = _batch_with_benign_first_attacker_dominant()
    verdict_dict = {"ip": _ATTACKER_IP, "is_attack": True, "confidence": 0.95}
    db = _FakeDB()
    _upsert_ip_memory(db, "client-1", batch, verdict_dict)
    assert len(db.added) == 1
    mem = db.added[0]
    assert mem.ip == _ATTACKER_IP
    assert mem.ip != batch[0]["ip"]
    # first_seen/last_seen must still span the whole batch, not just batch[0]
    assert mem.total_requests == len(batch)


def test_persist_scan_run_records_record_count_and_timestamp():
    batch = [
        {"timestamp": f"2024-01-15T14:00:{i:02d}Z", "ip": "192.0.2.{}".format(i),
         "method": "GET", "endpoint": "/home"}
        for i in range(50)
    ]
    verdict_dict = {"ip": "192.0.2.1", "is_attack": False, "severity": "none", "confidence": 0.0}
    db = _FakeDB()
    _persist_scan_run(db, "client-1", batch, verdict_dict)
    assert len(db.added) == 1
    s = db.added[0]
    assert s.org_id == "client-1"
    assert s.record_count == len(batch)
    assert s.scanned_at is not None


if __name__ == "__main__":
    print("\nprocess_logs.py attribution tests\n")

    test("persist_verdict uses attacker IP, not batch[0]",   test_persist_verdict_uses_attacker_ip_not_batch_zero)
    test("upsert_ip_memory uses attacker IP, not batch[0]",  test_upsert_ip_memory_uses_attacker_ip_not_batch_zero)
    test("persist_scan_run records count + timestamp",       test_persist_scan_run_records_record_count_and_timestamp)

    passed = sum(1 for s, _ in _results if s == "PASS")
    failed = sum(1 for s, _ in _results if s == "FAIL")
    print(f"\n{'='*40}")
    print(f"  {passed} passed   {failed} failed   ({len(_results)} total)")
    print(f"{'='*40}\n")
    sys.exit(0 if failed == 0 else 1)
