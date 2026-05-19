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
        client_id="uuid-...",
        redis_client=redis_conn,   # optional — omit in tests
    )
"""

from __future__ import annotations

import logging
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
from schemas.models import FusionVerdict, LogRecord

logger = logging.getLogger(__name__)

# Severity bands mapped from confidence score.
# These feed the `verdicts.severity` column used by the dashboard.
_SEVERITY_BANDS = [
    (0.80, "critical"),
    (0.60, "high"),
    (0.40, "medium"),
    (0.00, "low"),
]


def _severity(confidence: float) -> str:
    for threshold, label in _SEVERITY_BANDS:
        if confidence >= threshold:
            return label
    return "low"


def dict_to_log_record(d: dict) -> LogRecord:
    """
    Convert a normalised log dict (internal schema) to a LogRecord.

    Required keys: timestamp (ISO-8601 str or datetime), ip, method, endpoint, status
    Optional keys: response_size, latency, user_agent, client_id
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
        status=int(d["status"]),
        response_size=int(d.get("response_size", 0)),
        latency=float(d.get("latency", 0.0)),
        user_agent=str(d.get("user_agent", "")),
        client_id=str(d.get("client_id", "")),
        # Research fields — not set from production logs
        label="BENIGN",
        attack_category="Benign",
        is_attack=False,
    )


def run_pipeline(
    records: list[dict],
    client_id: str,
    redis_client: Optional[Any] = None,
) -> dict:
    """
    Run the detection engine on a batch of normalised log dicts.

    Args:
        records:      List of normalised log dicts (internal schema from PRODUCT_CONTEXT.md).
        client_id:    Clew client UUID (used to scope Redis LTM key).
        redis_client: Optional redis.Redis instance. When omitted LTM is in-process only.

    Returns:
        A dict ready to be inserted into the `verdicts` Postgres table.
        Keys: client_id, ip, method, endpoint, threat_type, severity, confidence,
              agents_triggered, explanation, blocked, cost_prevented, timestamp, is_attack.
    """
    if not records:
        raise ValueError("run_pipeline: records list must not be empty")

    log_records: list[LogRecord] = [dict_to_log_record(r) for r in records]

    # Tag all records with the client_id (they may not have it set from the dict)
    for lr in log_records:
        if not lr.client_id:
            lr.client_id = client_id

    memory = ProductSharedMemory(client_id=client_id, redis_client=redis_client)
    orchestrator = MetaAgentOrchestrator(memory)

    verdict: FusionVerdict = orchestrator.run(log_records)

    memory.flush()

    # Derive primary IP: the most frequent IP in the batch.
    ip_counter: Counter = Counter(lr.ip for lr in log_records)
    primary_ip: str = ip_counter.most_common(1)[0][0]

    # Derive representative method/endpoint from the most common values.
    method_counter: Counter = Counter(lr.method for lr in log_records)
    endpoint_counter: Counter = Counter(lr.endpoint for lr in log_records)

    logger.info(
        "Pipeline verdict: client=%s  is_attack=%s  threat=%s  confidence=%.2f  primary_ip=%s",
        client_id,
        verdict.is_attack,
        verdict.threat_type.value,
        verdict.confidence_score,
        primary_ip,
    )

    return {
        "client_id": client_id,
        "ip": primary_ip,
        "method": method_counter.most_common(1)[0][0],
        "endpoint": endpoint_counter.most_common(1)[0][0],
        "threat_type": verdict.threat_type.value,
        "severity": _severity(verdict.confidence_score) if verdict.is_attack else "none",
        "confidence": round(verdict.confidence_score, 4),
        "agents_triggered": verdict.contributing_agents,
        "explanation": verdict.explanation,
        "blocked": False,          # blocking integrations added in Phase 7
        "cost_prevented": 0.0,     # cost model added in Phase 6
        "timestamp": verdict.timestamp.isoformat(),
        "is_attack": verdict.is_attack,
    }
