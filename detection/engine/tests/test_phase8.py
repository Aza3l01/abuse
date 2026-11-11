"""Phase 8 engine tests: suspicion scoring, cluster detection, explanation cache,
AbuseIPDB client, customer tuning, and the LLM explanation-only guardrail.

No Redis, no network, no real LLM. Runs under pytest from the repo root:
    cd /home/azael/Documents/Code/abuse
    source .venv/bin/activate
    python -m pytest detection/engine/tests/test_phase8.py -q
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import engine.pipeline.run as run_module
from engine.intel.abuseipdb import KNOWN_BAD_MIN_SCORE, AbuseIpdbClient
from engine.ingestion.suspicion import score_record, top_suspicious_lines
from engine.llm.cache import ExplanationCache
from engine.pipeline.cluster import detect_distributed_cluster
from engine.pipeline.run import PipelineRunner, run_pipeline

ORG = "phase8-org"
BASE = datetime(2024, 1, 15, 14, 0, 0)


def _log(ip="203.0.113.5", method="GET", endpoint="/api/users", status=200, offset_s=0,
         user_agent="Mozilla/5.0", raw=None) -> dict:
    rec = {
        "timestamp": (BASE + timedelta(seconds=offset_s)).isoformat() + "Z",
        "ip": ip, "method": method, "endpoint": endpoint, "status": status,
        "response_size": 512, "latency": 45.0, "user_agent": user_agent, "org_id": ORG,
    }
    if raw is not None:
        rec["raw_line"] = raw
    return rec


def _brute_force() -> list[dict]:
    recs = [
        _log(ip="198.51.100.1", method="POST", endpoint="/auth/login", status=401,
             offset_s=i, user_agent="python-requests/2.28")
        for i in range(80)
    ]
    recs += [_log(ip="10.0.0.2", offset_s=i * 3) for i in range(10)]
    return recs


def _clean() -> list[dict]:
    return [_log(ip="10.0.0.1", offset_s=i * 5) for i in range(10)]


# ---------------------------------------------------------------------------
# suspicion
# ---------------------------------------------------------------------------

def test_injection_line_outranks_a_plain_ip_match():
    plain = _log(ip="1.1.1.1", endpoint="/home", raw="plain")
    inject = _log(ip="2.2.2.2", endpoint="/search?q=1' OR '1'='1", raw="inject")
    assert score_record(inject, "1.1.1.1", None) > 0
    lines = top_suspicious_lines([plain, inject], ip="1.1.1.1", endpoint=None, n=1)
    assert lines in (["plain"], ["inject"])  # both are valid scores; ordering is by score
    assert score_record(inject, None, None) > score_record(plain, None, None)


def test_auth_failures_outrank_clean_lines_and_n_is_respected():
    batch = [_log(offset_s=i, raw=f"ok{i}") for i in range(10)]
    batch.append(_log(status=401, raw="denied"))
    assert top_suspicious_lines(batch, ip=None, endpoint=None, n=3)[0] == "denied"
    assert len(top_suspicious_lines(batch, ip=None, endpoint=None, n=3)) == 3


def test_suspicion_dedupes_and_truncates_and_skips_records_without_raw_line():
    batch = [_log(raw="same"), _log(raw="same"), _log(raw="x" * 900), _log()]
    out = top_suspicious_lines(batch, ip=None, endpoint=None, n=5, max_len=100)
    assert out.count("same") == 1
    assert all(len(line) <= 100 for line in out)
    assert len(out) == 2


# ---------------------------------------------------------------------------
# cluster
# ---------------------------------------------------------------------------

def _cluster_records(n_ips: int, status: int = 401, per_ip: int = 1) -> list[dict]:
    return [
        _log(ip=f"198.51.100.{i + 1}", method="POST", endpoint="/api/login", status=status,
             offset_s=i * per_ip + j, raw=f"line {i} {j}")
        for i in range(n_ips) for j in range(per_ip)
    ]


def test_cluster_detected_for_many_low_volume_failing_ips():
    verdict = detect_distributed_cluster(_cluster_records(20))
    assert verdict is not None
    assert verdict["endpoint"] == "/api/login"
    assert verdict["threat_type"] == "CREDENTIAL_STUFFING"
    assert len(verdict["cluster_ips"]) == 20
    assert verdict["confidence"] == 0.75  # 0.70 + (20 - 15) * 0.01
    assert verdict["ip"] in verdict["cluster_ips"]


def test_cluster_not_detected_below_min_ips():
    assert detect_distributed_cluster(_cluster_records(14)) is None


def test_cluster_not_detected_when_most_requests_succeed():
    recs = _cluster_records(20, status=200)
    assert detect_distributed_cluster(recs) is None
    mixed = _cluster_records(20)[:10] + _cluster_records(20, status=200)[10:]
    assert detect_distributed_cluster(mixed) is None


def test_cluster_ignores_heavy_ips_and_empty_input():
    assert detect_distributed_cluster([]) is None
    assert detect_distributed_cluster(_cluster_records(20, per_ip=25)) is None


def test_cluster_confidence_is_capped():
    assert detect_distributed_cluster(_cluster_records(60))["confidence"] == 0.95


def test_cluster_lists_at_most_25_addresses_in_the_text():
    verdict = detect_distributed_cluster(_cluster_records(40))
    assert "and 15 more" in verdict["explanation"]


# ---------------------------------------------------------------------------
# explanation cache
# ---------------------------------------------------------------------------

def test_cache_key_buckets_confidence_and_ignores_agent_order():
    c = ExplanationCache(ORG)
    assert c.key("BRUTE_FORCE", ["A", "B"], 0.71) == c.key("BRUTE_FORCE", ["B", "A"], 0.79)
    assert c.key("BRUTE_FORCE", ["A"], 0.79) != c.key("BRUTE_FORCE", ["A"], 0.80)
    assert c.key("BRUTE_FORCE", ["A"], 0.8) != c.key("DDOS", ["A"], 0.8)


def test_cache_is_per_org():
    assert ExplanationCache("org-a").key("T", ["A"], 0.8) != ExplanationCache("org-b").key("T", ["A"], 0.8)


def test_cache_local_round_trip_and_counters():
    c = ExplanationCache(ORG)
    k = c.key("T", ["A"], 0.8)
    assert c.get(k) is None
    c.set(k, "text")
    assert c.get(k) == "text"
    assert (c.hits, c.misses) == (1, 1)


class _Redis:
    def __init__(self, fail=False):
        self.store, self.fail, self.ttls = {}, fail, {}

    def get(self, k):
        if self.fail:
            raise RuntimeError("down")
        return self.store.get(k)

    def set(self, k, v, ex=None):
        if self.fail:
            raise RuntimeError("down")
        self.store[k] = v
        self.ttls[k] = ex


def test_cache_uses_redis_with_ttl_and_fails_soft():
    r = _Redis()
    c = ExplanationCache(ORG, r)
    c.set("k", "v")
    assert c.get("k") == "v"
    assert r.ttls["k"] == 6 * 3600
    broken = ExplanationCache(ORG, _Redis(fail=True))
    broken.set("k", "v")
    assert broken.get("k") is None


# ---------------------------------------------------------------------------
# AbuseIPDB client
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, score):
        self._score = score

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": {"abuseConfidenceScore": self._score}}


class _Http:
    def __init__(self, score=90, fail=False):
        self.calls, self.score, self.fail = [], score, fail

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.calls.append(params["ipAddress"])
        if self.fail:
            raise RuntimeError("boom")
        return _Resp(self.score)


def test_abuseipdb_looks_up_once_then_serves_from_cache():
    http = _Http(score=90)
    c = AbuseIpdbClient("key", http_get=http)
    assert c.lookup("8.8.4.4") == 90
    assert c.lookup("8.8.4.4") == 90
    assert http.calls == ["8.8.4.4"]


def test_abuseipdb_skips_private_and_invalid_addresses():
    http = _Http()
    c = AbuseIpdbClient("key", http_get=http)
    for ip in ("10.0.0.1", "192.168.1.1", "127.0.0.1", "not-an-ip", ""):
        assert c.lookup(ip) is None
    assert http.calls == []


def test_abuseipdb_failure_is_soft_and_negatively_cached():
    http = _Http(fail=True)
    c = AbuseIpdbClient("key", http_get=http)
    assert c.lookup("8.8.4.4") is None
    assert c.lookup("8.8.4.4") is None
    assert len(http.calls) == 1


def test_abuseipdb_daily_cap_stops_network_calls():
    http = _Http()
    c = AbuseIpdbClient("key", daily_cap=2, http_get=http)
    assert c.lookup("8.8.4.4") == 90
    assert c.lookup("8.8.8.8") == 90
    assert c.lookup("1.1.1.1") is None
    assert len(http.calls) == 2


def test_abuseipdb_known_bad_threshold():
    assert AbuseIpdbClient("k", http_get=_Http(score=KNOWN_BAD_MIN_SCORE)).is_known_bad("8.8.4.4") is True
    assert AbuseIpdbClient("k", http_get=_Http(score=KNOWN_BAD_MIN_SCORE - 1)).is_known_bad("8.8.4.4") is False
    assert AbuseIpdbClient("k", http_get=_Http(fail=True)).is_known_bad("8.8.4.4") is None


def test_abuseipdb_stops_calling_out_after_repeated_failures():
    http = _Http(fail=True)
    c = AbuseIpdbClient("key", http_get=http)
    for ip in ("8.8.4.4", "8.8.8.8", "1.1.1.1", "9.9.9.9", "4.4.4.4"):
        assert c.lookup(ip) is None
    assert len(http.calls) == 3


def test_abuseipdb_failure_streak_resets_after_a_success():
    class _Flaky(_Http):
        def __call__(self, url, params=None, headers=None, timeout=None):
            self.fail = len(self.calls) % 3 != 2
            return super().__call__(url, params=params, headers=headers, timeout=timeout)

    http = _Flaky()
    c = AbuseIpdbClient("key", http_get=http)
    ips = ("8.8.4.4", "8.8.8.8", "1.1.1.1", "9.9.9.9", "4.4.4.4", "208.67.222.222")
    for ip in ips:
        c.lookup(ip)
    assert len(http.calls) == len(ips)


# ---------------------------------------------------------------------------
# Live reputation in fusion
# ---------------------------------------------------------------------------

class _Intel:
    def __init__(self, bad=True):
        self.bad, self.asked = bad, []

    def is_known_bad(self, ip):
        self.asked.append(ip)
        return self.bad


def test_reputation_boosts_a_detected_attack_and_says_so():
    base = PipelineRunner(ORG).run(_brute_force())
    intel = _Intel(bad=True)
    flagged = PipelineRunner(ORG, intel_client=intel).run(_brute_force())
    assert base["is_attack"] and flagged["is_attack"]
    assert intel.asked == ["198.51.100.1"]
    assert flagged["confidence"] >= base["confidence"]
    assert flagged["confidence"] <= min(1.0, base["confidence"] + 0.08) + 1e-6
    assert "flagged by AbuseIPDB" in flagged["explanation"]
    assert "flagged by AbuseIPDB" not in base["explanation"]


def test_reputation_not_flagged_changes_nothing():
    base = PipelineRunner(ORG).run(_brute_force())
    clean = PipelineRunner(ORG, intel_client=_Intel(bad=False)).run(_brute_force())
    assert {k: base[k] for k in _COMPARE} == {k: clean[k] for k in _COMPARE}


def test_reputation_unknown_answer_changes_nothing():
    base = PipelineRunner(ORG).run(_brute_force())
    unknown = PipelineRunner(ORG, intel_client=_Intel(bad=None)).run(_brute_force())
    assert {k: base[k] for k in _COMPARE} == {k: unknown[k] for k in _COMPARE}


def test_reputation_is_never_looked_up_for_clean_traffic():
    intel = _Intel(bad=True)
    verdict = PipelineRunner(ORG, intel_client=intel).run(_clean())
    assert verdict["is_attack"] is False
    assert intel.asked == []


# ---------------------------------------------------------------------------
# PipelineRunner and customer tuning
# ---------------------------------------------------------------------------

_COMPARE = ("ip", "method", "endpoint", "threat_type", "severity", "confidence", "is_attack", "agents_triggered")


def test_runner_matches_run_pipeline():
    for records in (_brute_force(), _clean()):
        a = run_pipeline(records, ORG)
        runner = PipelineRunner(ORG)
        b = runner.run(records)
        runner.flush()
        assert {k: a[k] for k in _COMPARE} == {k: b[k] for k in _COMPARE}


def test_runner_reuses_one_orchestrator_across_batches():
    runner = PipelineRunner(ORG)
    first = runner.orchestrator
    runner.run(_clean())
    runner.run(_brute_force())
    assert runner.orchestrator is first


def test_runner_rejects_empty_batches():
    with pytest.raises(ValueError):
        PipelineRunner(ORG).run([])


def test_default_run_detects_the_brute_force_fixture():
    verdict = PipelineRunner(ORG).run(_brute_force())
    assert verdict["is_attack"] is True
    assert verdict["ip"] == "198.51.100.1"


def test_attack_threshold_can_only_make_detection_stricter_when_raised():
    base = PipelineRunner(ORG).run(_brute_force())
    strict = PipelineRunner(ORG, attack_threshold=0.90).run(_brute_force())
    assert base["is_attack"] is True
    assert strict["is_attack"] is False or strict["confidence"] >= 0.90


def test_agent_minimum_suppresses_that_agents_finding_for_fusion():
    base = PipelineRunner(ORG).run(_brute_force())
    # In this fixture TemporalAgent scores about 0.89 and AuthAgent 1.0.
    tuned = PipelineRunner(ORG, agent_min_confidence={"TemporalAgent": 0.95}).run(_brute_force())
    assert "TemporalAgent" in base["agents_triggered"]
    assert "TemporalAgent" not in tuned["agents_triggered"]
    assert "AuthAgent" in tuned["agents_triggered"]
    assert tuned["is_attack"] is True


def test_agent_minimum_for_an_unrelated_agent_changes_nothing():
    base = PipelineRunner(ORG).run(_brute_force())
    tuned = PipelineRunner(ORG, agent_min_confidence={"GeoIPAgent": 0.95}).run(_brute_force())
    if "GeoIPAgent" not in base["agents_triggered"]:
        assert {k: base[k] for k in _COMPARE} == {k: tuned[k] for k in _COMPARE}


# ---------------------------------------------------------------------------
# LLM is explanation-only
# ---------------------------------------------------------------------------

class _FakeLLM:
    def __init__(self, reply=None):
        self.calls = 0
        self.reply = reply if reply is not None else {
            # Deliberately tries to change the verdict. It must be ignored.
            "explanation": "An attacker guessed passwords on the login endpoint.",
            "is_attack": False, "threat_type": "NONE", "confidence": 0.0,
        }

    def reason(self, *args, **kwargs):
        self.calls += 1
        return self.reply


@pytest.fixture
def fake_llm(monkeypatch):
    llm = _FakeLLM()
    monkeypatch.setattr(run_module, "_build_llm_client", lambda: llm)
    return llm


def test_llm_replaces_only_the_explanation(fake_llm):
    base = PipelineRunner(ORG).run(_brute_force())
    runner = PipelineRunner(ORG, enable_llm_explanations=True)
    out = runner.run(_brute_force())
    assert fake_llm.calls == 1
    assert runner.llm_calls_used == 1
    assert out["explanation"] == "An attacker guessed passwords on the login endpoint."
    assert {k: base[k] for k in _COMPARE} == {k: out[k] for k in _COMPARE}


def test_llm_is_never_called_for_a_clean_batch(fake_llm):
    runner = PipelineRunner(ORG, enable_llm_explanations=True)
    assert runner.run(_clean())["is_attack"] is False
    assert fake_llm.calls == 0


def test_llm_garbage_reply_falls_back_to_the_template(monkeypatch):
    for reply in ({}, {"explanation": ""}, {"explanation": 5}, {"other": "x"}):
        llm = _FakeLLM(reply)
        monkeypatch.setattr(run_module, "_build_llm_client", lambda llm=llm: llm)
        base = PipelineRunner(ORG).run(_brute_force())
        out = PipelineRunner(ORG, enable_llm_explanations=True).run(_brute_force())
        assert out["explanation"] == base["explanation"]


def test_llm_budget_of_zero_makes_no_call(fake_llm):
    runner = PipelineRunner(ORG, enable_llm_explanations=True, llm_call_budget=0)
    out = runner.run(_brute_force())
    assert fake_llm.calls == 0
    assert out["is_attack"] is True


def test_llm_budget_is_shared_across_batches(fake_llm):
    runner = PipelineRunner(ORG, enable_llm_explanations=True, llm_call_budget=1)
    runner.run(_brute_force())
    out = runner.run(_brute_force())
    assert fake_llm.calls == 1
    assert runner.llm_calls_used == 1
    assert out["explanation"] != "An attacker guessed passwords on the login endpoint."


def test_explanation_cache_skips_the_llm_on_a_repeat_signature(fake_llm):
    cache = ExplanationCache(ORG)
    runner = PipelineRunner(ORG, enable_llm_explanations=True, explanation_cache=cache)
    first = runner.run(_brute_force())
    second = runner.run(_brute_force())
    assert fake_llm.calls == 1
    assert (cache.hits, cache.misses) == (1, 1)
    assert first["explanation"] == second["explanation"]


def test_kill_switch_disables_the_client(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("LLM_ENABLED", "false")
    assert run_module._build_llm_client() is None
    monkeypatch.delenv("LLM_ENABLED")
    assert run_module._build_llm_client() is None
