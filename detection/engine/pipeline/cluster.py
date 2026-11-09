"""Cross-IP clustering for distributed low-and-slow attacks (Phase 8, Pro and up).

Pass A needs a dominant IP and Pass B needs 20+ requests from one IP, so a
botnet that sends one or two attempts per address slips past both. This pure
function looks at a whole poll cycle for the same pattern from many addresses:
the same endpoint, each address under the Pass B floor, almost all rejected
(401 or 403). It never decides blocking, the caller records an alert only.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Optional

_AGENT_LABEL = "ClusterDetector"
_FAILURE_STATUSES = frozenset({401, 403})
_MAX_LISTED_IPS = 25


def detect_distributed_cluster(
    records: list[dict],
    min_ips: int = 15,
    max_requests_per_ip: int = 19,
    min_failure_ratio: float = 0.80,
) -> Optional[dict]:
    """Return a verdict-shaped dict for the largest qualifying cluster, else None.

    An IP counts only if it made at most `max_requests_per_ip` requests across
    the whole poll (heavier IPs are already covered by Pass A and Pass B).
    """
    if not records:
        return None

    per_ip = Counter(r.get("ip", "") for r in records if r.get("ip"))
    low_volume = {ip for ip, n in per_ip.items() if n <= max_requests_per_ip}
    if len(low_volume) < min_ips:
        return None

    by_endpoint: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("ip") in low_volume:
            by_endpoint[r.get("endpoint_template") or r.get("endpoint") or ""].append(r)

    best: Optional[tuple[str, list[dict], list[str], float]] = None
    for endpoint, recs in by_endpoint.items():
        if not endpoint:
            continue
        failures = [r for r in recs if r.get("status") in _FAILURE_STATUSES]
        if not recs or len(failures) / len(recs) < min_failure_ratio:
            continue
        failing_ips = sorted({r["ip"] for r in failures})
        if len(failing_ips) < min_ips:
            continue
        ratio = len(failures) / len(recs)
        if best is None or len(failing_ips) > len(best[2]):
            best = (endpoint, recs, failing_ips, ratio)

    if best is None:
        return None

    endpoint, recs, failing_ips, ratio = best
    failure_counts = Counter(r["ip"] for r in recs if r.get("status") in _FAILURE_STATUSES)
    lead_ip = max(failing_ips, key=lambda ip: (failure_counts[ip], ip))
    n_ips = len(failing_ips)
    confidence = round(min(0.95, 0.70 + (n_ips - min_ips) * 0.01), 4)
    listed = failing_ips[:_MAX_LISTED_IPS]
    more = n_ips - len(listed)

    explanation = (
        f"{n_ips} different addresses each made only a few requests to {endpoint} during this scan, "
        f"and {ratio:.0%} of those requests were rejected (401 or 403). One attempt per address stays "
        f"under the per-address detection floor, but together this matches a distributed credential "
        f"stuffing campaign. Addresses: {', '.join(listed)}"
        + (f" and {more} more." if more > 0 else ".")
    )
    sample = [r["raw_line"][:512] for r in recs if r.get("raw_line") and r.get("status") in _FAILURE_STATUSES][:5]

    return {
        "ip": lead_ip,
        "method": Counter(r.get("method", "") for r in recs).most_common(1)[0][0] or None,
        "endpoint": endpoint,
        "threat_type": "CREDENTIAL_STUFFING",
        "confidence": confidence,
        "agents_triggered": [_AGENT_LABEL],
        "explanation": explanation,
        "sample_logs": sample,
        "cluster_ips": failing_ips,
        "request_count": len(recs),
    }
