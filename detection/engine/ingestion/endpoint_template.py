"""
engine/source/ingestion/endpoint_template.py — collapse identifier-like path
segments into a stable template so REST endpoints with embedded IDs count as
one distinct endpoint instead of one per request.

Kept as its own module (rather than living directly in normalizer.py) so both
alb_parser.py and apigw_parser.py can import it without a circular import
back through normalizer.py, which imports both parsers.

Rules (in priority order, first match wins):
  - UUID                       -> {uuid}
  - purely numeric              -> {id}
  - hex string >= 16 chars      -> {hash}
  - long base64/token-ish blob  -> {token}
  - anything else               -> left untouched
"""

from __future__ import annotations

import re

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_NUMERIC_RE = re.compile(r"^\d+$")
_HEX_RE = re.compile(r"^[0-9a-fA-F]{16,}$")
# Long alphanumeric-ish segment containing at least one digit — distinguishes
# tokens/hashes from ordinary human-readable path words like "descriptive-slug".
_TOKEN_RE = re.compile(r"^(?=.*\d)[A-Za-z0-9_-]{20,}$")


def _template_segment(segment: str) -> str:
    if _UUID_RE.match(segment):
        return "{uuid}"
    if _NUMERIC_RE.match(segment):
        return "{id}"
    if _HEX_RE.match(segment):
        return "{hash}"
    if _TOKEN_RE.match(segment):
        return "{token}"
    return segment


def template_endpoint(path: str) -> str:
    """Collapse identifier-like segments, e.g. /users/12345 -> /users/{id}."""
    if not path:
        return path
    base, _, _query = path.partition("?")
    segments = base.split("/")
    return "/".join(_template_segment(s) for s in segments)
