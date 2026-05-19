"""
engine/source/ingestion/normalizer.py — Route raw log lines to the correct parser.

This is the only file the Celery task talks to. It knows nothing about S3 or
parsers — it just takes raw lines, a log_format string, and a client_id, and
returns a list of normalised dicts ready for run_pipeline().

Supported log_format values (match db.models.Client.log_format):
  "apigw"  — AWS API Gateway access logs
  "alb"    — AWS Application Load Balancer access logs
"""

from __future__ import annotations

import logging
from typing import Optional

from engine.ingestion import apigw_parser, alb_parser

logger = logging.getLogger(__name__)

_PARSERS = {
    "apigw": apigw_parser.parse_line,
    "alb":   alb_parser.parse_line,
}


def normalize(
    lines: list[str],
    log_format: str,
    client_id: str,
    batch_size: int = 500,
) -> list[list[dict]]:
    """
    Parse raw log lines and split into fixed-size batches.

    Args:
        lines:      Raw log lines (from S3Reader.read_all).
        log_format: "apigw" or "alb".
        client_id:  Injected into every dict as "client_id".
        batch_size: Number of records per batch passed to run_pipeline.
                    Matches the engine's calibrated window size.

    Returns:
        List of batches. Each batch is a list[dict] ready for run_pipeline().
        Empty lines and unparseable lines are silently dropped.
        Returns [] if no parseable records exist.
    """
    parser = _PARSERS.get(log_format)
    if parser is None:
        raise ValueError(
            f"Unknown log_format: {log_format!r}. "
            f"Supported: {', '.join(sorted(_PARSERS))}"
        )

    records: list[dict] = []
    skipped = 0

    for line in lines:
        result = parser(line)
        if result is None:
            skipped += 1
            continue
        result["client_id"] = client_id
        records.append(result)

    if skipped:
        logger.debug(
            "normalizer: skipped %d unparseable lines (format=%s, client=%s)",
            skipped, log_format, client_id,
        )

    if not records:
        return []

    # Split into fixed-size batches
    return [records[i : i + batch_size] for i in range(0, len(records), batch_size)]
