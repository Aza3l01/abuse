"""
engine/source/ingestion/normalizer.py — Route raw log lines to the correct parser.

This is the only file the Celery task talks to. It knows nothing about S3 or
parsers — it just takes raw lines, a log_format string, and an org_id, and
returns a list of normalised dicts ready for run_pipeline().

Supported log_format values (match db.models.Client.log_format):
  "apigw"  — AWS API Gateway access logs
  "alb"    — AWS Application Load Balancer access logs
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from engine.ingestion import apigw_parser, alb_parser

logger = logging.getLogger(__name__)

_PARSERS = {
    "apigw": apigw_parser.parse_line,
    "alb":   alb_parser.parse_line,
}


def parse_lines(
    lines: list[str], log_format: str, org_id: str,
    keys: Optional[list[str]] = None,
) -> list[dict]:
    """
    Parse raw log lines into normalised dicts (no batching/grouping).

    Shared by normalize() (Pass A's window batching) and item 1's Pass B
    (group_by_ip()) so both passes work from the exact same parsed records
    instead of parsing the same lines twice.

    Args:
      keys: item 3's source_key dedup — parallel list of per-line identifiers
            (same length as lines). When given, each successfully parsed
            record gets `result["source_key"] = keys[i]`. Optional and
            backward compatible — omit for callers that don't need it
            (calibration pass, tests).
    """
    parser = _PARSERS.get(log_format)
    if parser is None:
        raise ValueError(
            f"Unknown log_format: {log_format!r}. "
            f"Supported: {', '.join(sorted(_PARSERS))}"
        )

    records: list[dict] = []
    skipped = 0

    for i, line in enumerate(lines):
        result = parser(line)
        if result is None:
            skipped += 1
            continue
        result["org_id"] = org_id
        if keys is not None:
            result["source_key"] = keys[i]
        records.append(result)

    if skipped:
        logger.debug(
            "normalizer: skipped %d unparseable lines (format=%s, org=%s)",
            skipped, log_format, org_id,
        )

    return records


def chunk(records: list[dict], batch_size: int = 500) -> list[list[dict]]:
    """Split already-parsed records into fixed-size batches (Pass A)."""
    if not records:
        return []
    return [records[i : i + batch_size] for i in range(0, len(records), batch_size)]


def normalize(
    lines: list[str],
    log_format: str,
    org_id: str,
    batch_size: int = 500,
) -> list[list[dict]]:
    """
    Parse raw log lines and split into fixed-size batches.

    Args:
        lines:      Raw log lines (from S3Reader.read_all).
        log_format: "apigw" or "alb".
        org_id:     Injected into every dict as "org_id".
        batch_size: Number of records per batch passed to run_pipeline.
                    Matches the engine's calibrated window size.

    Returns:
        List of batches. Each batch is a list[dict] ready for run_pipeline().
        Empty lines and unparseable lines are silently dropped.
        Returns [] if no parseable records exist.
    """
    records = parse_lines(lines, log_format, org_id)
    return chunk(records, batch_size)


def group_by_ip(records: list[dict], min_requests: int = 20) -> dict[str, list[dict]]:
    """
    Group already-parsed records by source IP for item 1's per-IP focus pass
    (Pass B) — catches an attacker whose requests would otherwise be diluted
    across two or more of Pass A's window boundaries.

    Only IPs with at least `min_requests` records in this poll cycle get a
    group. Below that, every focus-mode agent's minimum floor
    (AuthAgent.MIN_ATTEMPTS_FOR_STUFFING=20 is the highest) means the agent
    would return early anyway — those IPs are still covered by Pass A instead.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        ip = r.get("ip", "")
        if ip:
            groups[ip].append(r)
    return {ip: recs for ip, recs in groups.items() if len(recs) >= min_requests}
