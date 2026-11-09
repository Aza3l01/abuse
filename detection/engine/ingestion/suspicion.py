"""Per-line suspicion scoring for the verdict's raw log sample (Phase 8).

Replaces the old "lines matching ip or endpoint, padded with the first lines"
selection. Each parsed record gets an additive score, the top lines win. Pure
function of the batch and the verdict's attributed ip/endpoint, no I/O.
"""

from __future__ import annotations

from typing import Optional

from engine.agents.payload_agent import PayloadAgent

_IP_MATCH = 2.0
_ENDPOINT_MATCH = 1.0
_INJECTION_HIT = 3.0
_AUTH_FAILURE = 1.5
_NOT_FOUND = 0.5
_SERVER_ERROR = 0.5
_SLOW_MS = 5000.0
_SLOW = 0.5


def score_record(rec: dict, ip: Optional[str], endpoint: Optional[str]) -> float:
    score = 0.0
    if ip and rec.get("ip") == ip:
        score += _IP_MATCH
    if endpoint and rec.get("endpoint") == endpoint:
        score += _ENDPOINT_MATCH

    target = rec.get("endpoint") or ""
    if any(pattern.search(target) for _name, pattern in PayloadAgent._INJECTION_PATTERNS):
        score += _INJECTION_HIT

    status = rec.get("status")
    if status in (401, 403):
        score += _AUTH_FAILURE
    elif status == 404:
        score += _NOT_FOUND
    elif isinstance(status, int) and status >= 500:
        score += _SERVER_ERROR

    latency = rec.get("latency")
    if isinstance(latency, (int, float)) and latency > _SLOW_MS:
        score += _SLOW
    return score


def top_suspicious_lines(
    batch: list[dict],
    ip: Optional[str],
    endpoint: Optional[str],
    n: int = 5,
    max_len: int = 512,
) -> list[str]:
    """The n highest-scoring raw lines, ties broken by original order.

    Records without a `raw_line` (data parsed before item 19) are skipped. A
    line with score 0 only appears if fewer than n scored higher, so a clean
    batch still yields a sample.
    """
    candidates = [(i, r) for i, r in enumerate(batch) if r.get("raw_line")]
    ranked = sorted(candidates, key=lambda ir: (-score_record(ir[1], ip, endpoint), ir[0]))

    sample: list[str] = []
    for _i, rec in ranked:
        line = rec["raw_line"]
        if line in sample:
            continue
        sample.append(line)
        if len(sample) >= n:
            break
    return [line[:max_len] for line in sample]
