"""
engine/source/pipeline/run.py — Product pipeline adapter.

This is the single entry point the Celery task (Phase 5) calls.

Responsibilities:
  1. Convert a list of raw log dicts (from S3 ingestion) to LogRecord objects.
  2. Construct a ProductSharedMemory instance backed by Redis/Postgres.
  3. Run MetaAgentOrchestrator.
  4. Flush LTM state back to Redis.
  5. Return a verdict dict ready to be inserted into the `verdicts` Postgres table.

The orchestrator is created fresh per task invocation. State continuity between
batches comes entirely from the ProductSharedMemory (Redis LTM snapshot).

Usage:
    from engine.pipeline.run import run_pipeline

    verdict = run_pipeline(
        records=[{"timestamp": "...", "ip": "...", ...}, ...],
        org_id="uuid-...",
        redis_client=redis_conn,   # optional — omit in tests
    )
"""

from __future__ import annotations

import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure engine/ is on the path when this module is used from the product backend.
# engine/source/pipeline/run.py → .parent.parent.parent = engine/
_ENGINE_ROOT = Path(__file__).parent.parent.parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from engine.coordinator.meta_agent import MetaAgentOrchestrator
from engine.memory.product_memory import ProductSharedMemory
from schemas.models import FusionVerdict, LogRecord, ThreatType

logger = logging.getLogger(__name__)

# Phase 3 (legacy item 33): read at call time, not import time, so tests that
# monkeypatch os.environ don't need to reimport this module.
_LLM_CALL_TIMEOUT_SECONDS = 10.0


def _build_llm_client():
    """Construct an LLMClient from env vars, or None if not configured/available.

    The engine itself must not import api.tiers or know about tiers at all
    (the caller decides enable_llm_explanations). This only decides whether
    a GROQ_API_KEY is present to actually build a client with.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return None
    base_url = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    model = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
    try:
        from engine.llm.client import LLMClient
        return LLMClient(base_url=base_url, model=model, api_key=api_key, timeout=_LLM_CALL_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("run_pipeline: failed to construct LLMClient, falling back to rule-based explanations", exc_info=True)
        return None

# Severity bands mapped from confidence score.
# These feed the `verdicts.severity` column used by the dashboard.
_SEVERITY_BANDS = [
    (0.80, "critical"),
    (0.60, "high"),
    (0.40, "medium"),
    (0.00, "low"),
]

# Cost-prevented estimate, in USD per malicious request in the batch. Mirrors
# the same base rates `frontend/src/components/home/CostCalculator.tsx` already
# publishes on the landing page (INR figures there, converted here at the same
# ~84 rate that component uses), so the dashboard number and the marketing
# estimate share one set of assumptions instead of two unrelated guesses.
# Still a rough estimate, not a guarantee.
_INFRA_COST_PER_REQUEST_USD = 0.9 / 84    # bot/DoS/scan/enumeration traffic
_ATO_SUCCESS_RATE = 0.003                 # fraction of credential-stuffing/brute-force attempts that would have succeeded
_ATO_COST_USD = 8_000 / 84                # average cost of one successful account takeover
_ATO_THREAT_TYPES = frozenset({ThreatType.CREDENTIAL_STUFFING, ThreatType.BRUTE_FORCE})


def _estimate_cost_prevented(threat_type: ThreatType, ip_request_count: int, confidence: float) -> float:
    """Rough USD estimate of the cost this verdict's detection avoided.

    ip_request_count must be the flagged IP's own request count, not the size
    of whatever batch/window it was detected in (a window batch mixes many
    IPs together, so using the whole batch size over-attributes cost to
    unrelated, benign traffic that happened to share the window).
    """
    if threat_type in _ATO_THREAT_TYPES:
        raw = ip_request_count * _ATO_SUCCESS_RATE * _ATO_COST_USD
    else:
        raw = ip_request_count * _INFRA_COST_PER_REQUEST_USD
    return round(raw * confidence, 2)


def _severity(confidence: float) -> str:
    for threshold, label in _SEVERITY_BANDS:
        if confidence >= threshold:
            return label
    return "low"


def dict_to_log_record(d: dict) -> LogRecord:
    """
    Convert a normalised log dict (internal schema) to a LogRecord.

    Required keys: timestamp (ISO-8601 str or datetime), ip, method, endpoint, status
    Optional keys: response_size, latency, user_agent, org_id
    """
    ts = d["timestamp"]
    if isinstance(ts, str):
        # Parse ISO-8601; replace trailing Z with +00:00 for fromisoformat
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))

    return LogRecord(
        timestamp=ts,
        ip=str(d["ip"]),
        method=str(d.get("method", "GET")),
        endpoint=str(d["endpoint"]),
        endpoint_template=d.get("endpoint_template"),
        status=int(d["status"]),
        response_size=int(d.get("response_size", 0)),
        latency=float(d.get("latency", 0.0)),
        user_agent=str(d.get("user_agent", "")),
        org_id=str(d.get("org_id", "")),
        # Research fields — not set from production logs
        label="BENIGN",
        attack_category="Benign",
        is_attack=False,
    )


def run_pipeline(
    records: list[dict],
    org_id: str,
    redis_client: Optional[Any] = None,
    home_country: str = "",
    mode: str = "window",
    ltm_ttl_seconds: Optional[int] = None,
    enable_llm_explanations: bool = False,
) -> dict:
    """
    Run the detection engine on a batch of normalised log dicts.

    Args:
        records:      List of normalised log dicts (internal schema from CONTEXT.md).
        org_id:       Clew organisation UUID (used to scope Redis LTM key).
        redis_client: Optional redis.Redis instance. When omitted LTM is in-process only.
        home_country: Tenant's expected home country (ISO 3166-1 alpha-2), from
                      Organization.home_country. Empty string means "unknown" —
                      GeoIPAgent suppresses its foreign-concentration check in
                      that case.
        mode:         "window" (default, Pass A — mixed-IP batches) or "focus"
                      (item 1's Pass B — a single-IP group). Forwarded to
                      MetaAgentOrchestrator.run().
        ltm_ttl_seconds: Item 30/section 5's per-tier override for how long the
                      Redis LTM snapshot survives (ProductSharedMemory's normal
                      default otherwise). None (default) leaves the engine's
                      own default untouched.
        enable_llm_explanations: Phase 3/item 33. Decided by the caller from the
                      org's tier (this module must not import api.tiers). When
                      True and GROQ_API_KEY is set, a real LLMClient is built and
                      wired into the orchestrator, which fails soft to the
                      rule-based explanation on any LLM error or missing key.

    Returns:
        A dict ready to be inserted into the `verdicts` Postgres table.
        Keys: org_id, ip, method, endpoint, threat_type, severity, confidence,
              agents_triggered, explanation, blocked, cost_prevented, timestamp, is_attack.
    """
    if not records:
        raise ValueError("run_pipeline: records list must not be empty")

    log_records: list[LogRecord] = [dict_to_log_record(r) for r in records]

    # Tag all records with the org_id (they may not have it set from the dict)
    for lr in log_records:
        if not lr.org_id:
            lr.org_id = org_id

    memory_kwargs: dict[str, Any] = {"org_id": org_id, "redis_client": redis_client}
    if ltm_ttl_seconds is not None:
        memory_kwargs["ttl_seconds"] = ltm_ttl_seconds
    memory = ProductSharedMemory(**memory_kwargs)
    if home_country:
        memory.ltm._tenant_home_country = home_country
    llm_client = _build_llm_client() if enable_llm_explanations else None
    orchestrator = MetaAgentOrchestrator(memory, llm_client=llm_client)

    verdict: FusionVerdict = orchestrator.run(log_records, mode=mode)

    memory.flush()

    if mode == "focus":
        # Focus batches are already a single IP's records by construction
        # (group_by_ip()) — no need for a Counter majority vote.
        primary_ip = log_records[0].ip
        primary_ip_requests = len(log_records)
    else:
        # Derive primary IP: the most frequent IP in the batch.
        ip_counter: Counter = Counter(lr.ip for lr in log_records)
        primary_ip = ip_counter.most_common(1)[0][0]
        # Window batches mix many IPs together (chunk() groups up to 500
        # records regardless of IP). Cost prevented must scale with the
        # flagged IP's own request volume, not the whole mixed-IP window,
        # or a single attacker hiding in a large benign batch gets credited
        # with preventing damage from traffic that was never theirs.
        primary_ip_requests = ip_counter[primary_ip]

    # Derive representative method/endpoint from the most common values.
    method_counter: Counter = Counter(lr.method for lr in log_records)
    endpoint_counter: Counter = Counter(lr.endpoint for lr in log_records)

    logger.info(
        "Pipeline verdict: org=%s  is_attack=%s  threat=%s  confidence=%.2f  primary_ip=%s",
        org_id,
        verdict.is_attack,
        verdict.threat_type.value,
        verdict.confidence_score,
        primary_ip,
    )

    # Item 19: per-agent score table for the verdict detail page — every
    # dispatched/skipped agent's own finding, not just the triggered subset
    # `agents_triggered` carries. Skipped agents already carry a placeholder
    # AgentFinding (confidence_score=0.0, threat_detected=False) from the
    # orchestrator's triage step, so this is a full 6-row breakdown.
    agent_scores = [
        {
            "agent_name": f.agent_name,
            "score": round(f.confidence_score, 4),
            "triggered": f.threat_detected,
        }
        for f in verdict.agent_findings
    ]

    return {
        "org_id": org_id,
        "ip": primary_ip,
        "method": method_counter.most_common(1)[0][0],
        "endpoint": endpoint_counter.most_common(1)[0][0],
        "threat_type": verdict.threat_type.value,
        "severity": _severity(verdict.confidence_score) if verdict.is_attack else "none",
        "confidence": round(verdict.confidence_score, 4),
        "agents_triggered": verdict.contributing_agents,
        "agent_scores": agent_scores,
        "explanation": verdict.explanation,
        "blocked": False,          # blocking integrations added in Phase 7
        "cost_prevented": (
            _estimate_cost_prevented(verdict.threat_type, primary_ip_requests, verdict.confidence_score)
            if verdict.is_attack else 0.0
        ),
        "timestamp": verdict.timestamp.isoformat(),
        "is_attack": verdict.is_attack,
    }
