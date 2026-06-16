"""
engine/source/ingestion/alb_parser.py — AWS Application Load Balancer access log parser.

ALB access log format (space-delimited, fixed-field-count):
https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-access-logs.html

Example line:
  http 2024-01-15T14:23:01.123456Z app/my-alb/abc123 203.0.113.4:55012
  10.0.1.5:80 0.000 0.045 0.000 200 200 512 1024
  "GET https://api.example.com:443/api/users HTTP/1.1"
  "python-requests/2.28" - - arn:aws:elasticloadbalancing:... "Root=..."
  "-" "-" 0 2024-01-15T14:23:01.123456Z "forward" "-" "-" "10.0.1.5:80"
  "200" "-" "..."
"""

from __future__ import annotations

import re
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# The ALB log format is complex — simplest robust approach is to split on
# whitespace while respecting quoted strings.
_QUOTED_OR_TOKEN = re.compile(r'"[^"]*"|\S+')


def _split_alb_line(line: str) -> list[str]:
    return _QUOTED_OR_TOKEN.findall(line)


def parse_line(line: str) -> Optional[dict]:
    """
    Parse one ALB access log line.
    Returns a normalised dict or None if the line cannot be parsed.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    fields = _split_alb_line(line)

    # ALB lines have at least 29 fields; bail early if malformed
    if len(fields) < 12:
        return None

    # Field indices (0-based) for the standard ALB format:
    # 0  type (http/https/h2/grpcs/ws/wss)
    # 1  timestamp (ISO-8601 with microseconds)
    # 2  elb name
    # 3  client:port
    # 4  target:port
    # 5  request_processing_time
    # 6  target_processing_time
    # 7  response_processing_time
    # 8  elb_status_code
    # 9  target_status_code
    # 10 received_bytes
    # 11 sent_bytes
    # 12 "METHOD URL HTTP/ver"
    # 13 "User-Agent"
    # ... (many more optional fields)

    try:
        ts = datetime.fromisoformat(fields[1].replace("Z", "+00:00"))
    except (ValueError, IndexError):
        return None

    # client:port → extract IP (handles IPv6 like [::1]:port)
    client_field = fields[3]
    ip = client_field.rsplit(":", 1)[0].strip("[]")

    # request field: "METHOD URL HTTP/ver"
    request_raw = fields[12].strip('"')
    request_parts = request_raw.split()
    if len(request_parts) < 2:
        return None
    method = request_parts[0].upper()
    url = request_parts[1]
    # Extract path from full URL if present
    try:
        from urllib.parse import urlparse
        endpoint = urlparse(url).path or url
    except Exception:
        endpoint = url

    # Status codes — prefer target status over ELB status
    try:
        status = int(fields[9]) if fields[9] != "-" else int(fields[8])
    except (ValueError, IndexError):
        status = 0

    # Latency: target_processing_time (field 6) in seconds → convert to ms
    try:
        latency_ms = float(fields[6]) * 1000.0 if fields[6] != "-1" else 0.0
    except (ValueError, IndexError):
        latency_ms = 0.0

    # Sent bytes (response size)
    try:
        sent_bytes = int(fields[11]) if fields[11] != "-" else 0
    except (ValueError, IndexError):
        sent_bytes = 0

    # User agent (field 13)
    user_agent = ""
    if len(fields) > 13:
        user_agent = fields[13].strip('"')
        if user_agent == "-":
            user_agent = ""

    if not ip:
        return None

    return {
        "timestamp":     ts.isoformat(),
        "ip":            ip,
        "method":        method,
        "endpoint":      endpoint,
        "status":        status,
        "response_size": sent_bytes,
        "latency":       round(latency_ms, 3),
        "user_agent":    user_agent,
    }
