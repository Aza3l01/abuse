"""
engine/source/ingestion/apigw_parser.py — AWS API Gateway access log parser.

API Gateway access logs use a configurable format string. The most common
production format (and the one Clew instructs clients to use) is:

  $context.requestTime $context.identity.sourceIp $context.httpMethod
  $context.path $context.status $context.responseLength
  $context.responseLatency $context.identity.userAgent $context.requestId

Clew logs are configured as a single-line JSON object:
  {
    "requestTime": "...",
    "ip": "...",
    "method": "...",
    "path": "...",
    "status": 200,
    "responseLength": 512,
    "latencyMs": 45,
    "userAgent": "..."
  }

We support both JSON format and the older CLF-style space-delimited format.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# CLF-style format that API Gateway emits with the default log format.
# Fields: ip time method path status response_length latency_ms user_agent request_id
# Example:
#   203.0.113.4 - - [15/Jan/2024:14:23:01 +0000] "GET /api/users HTTP/1.1" 200 512 45 "python-requests/2.28" "a1b2c3"
_CLF_PATTERN = re.compile(
    r'^(?P<ip>\S+)'           # source IP
    r'\s+\S+'                 # ident (-)
    r'\s+\S+'                 # auth (-)
    r'\s+\[(?P<time>[^\]]+)\]'# [date:time tz]
    r'\s+"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"'  # "METHOD PATH HTTP/x.x"
    r'\s+(?P<status>\d+)'     # status code
    r'\s+(?P<size>\S+)'       # response size (or -)
    r'(?:\s+(?P<latency>\S+))?' # optional latency (ms)
    r'(?:\s+"(?P<ua>[^"]*)")?'  # optional User-Agent
)

_CLF_TIME_FMT = "%d/%b/%Y:%H:%M:%S %z"


def _parse_json_line(line: str) -> Optional[dict]:
    """Parse a JSON-format API Gateway log line."""
    try:
        d = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    ts_raw = d.get("requestTime") or d.get("time") or d.get("timestamp")
    if not ts_raw:
        return None

    try:
        if isinstance(ts_raw, (int, float)):
            ts = datetime.fromtimestamp(ts_raw / 1000.0, tz=timezone.utc)
        else:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None

    return {
        "timestamp": ts.isoformat(),
        "ip":            str(d.get("ip") or d.get("sourceIp") or ""),
        "method":        str(d.get("method") or d.get("httpMethod") or "GET").upper(),
        "endpoint":      str(d.get("path") or d.get("endpoint") or "/"),
        "status":        int(d.get("status") or d.get("statusCode") or 0),
        "response_size": int(d.get("responseLength") or d.get("responseSize") or 0),
        "latency":       float(d.get("latencyMs") or d.get("latency") or 0.0),
        "user_agent":    str(d.get("userAgent") or d.get("user_agent") or ""),
    }


def _parse_clf_line(line: str) -> Optional[dict]:
    """Parse a CLF-format API Gateway log line."""
    m = _CLF_PATTERN.match(line.strip())
    if not m:
        return None

    try:
        ts = datetime.strptime(m.group("time"), _CLF_TIME_FMT)
    except ValueError:
        return None

    size_raw = m.group("size")
    latency_raw = m.group("latency")

    return {
        "timestamp":     ts.isoformat(),
        "ip":            m.group("ip"),
        "method":        m.group("method").upper(),
        "endpoint":      m.group("path"),
        "status":        int(m.group("status")),
        "response_size": 0 if size_raw == "-" else int(size_raw),
        "latency":       0.0 if not latency_raw or latency_raw == "-" else float(latency_raw),
        "user_agent":    m.group("ua") or "",
    }


def parse_line(line: str) -> Optional[dict]:
    """
    Parse one API Gateway log line. Tries JSON first, falls back to CLF.
    Returns a normalised dict or None if the line cannot be parsed.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    result = _parse_json_line(line) if line.startswith("{") else None
    if result is None:
        result = _parse_clf_line(line)

    if result and not result.get("ip"):
        return None  # can't do anything without an IP

    return result
