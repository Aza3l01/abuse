"""api/detection_config.py: validation and resolution of Organization.detection_config (Phase 8).

Shape (every key optional):
  attack_threshold            float 0.40-0.90, engine default 0.60
  block_confidence_threshold  float 0.50-0.95, default 0.75, automatic blocking only
  agent_min_confidence        {AgentName: float 0.50-0.95}
  endpoint_thresholds         [{"pattern": str, "min_confidence": float 0.50-0.99}], max 20

The engine never imports this module. workers/tasks/process_logs.py resolves
the effective values and passes them into the engine as plain arguments.
"""
from __future__ import annotations

from typing import Any, Optional

from api.tiers import CUSTOM_THRESHOLD_TIERS

AGENT_NAMES = ("VolumeAgent", "TemporalAgent", "AuthAgent", "PayloadAgent", "SequenceAgent", "GeoIPAgent")

DEFAULT_ATTACK_THRESHOLD = 0.60
DEFAULT_BLOCK_CONFIDENCE_THRESHOLD = 0.75

ATTACK_THRESHOLD_RANGE = (0.40, 0.90)
BLOCK_THRESHOLD_RANGE = (0.50, 0.95)
AGENT_MIN_RANGE = (0.50, 0.95)
ENDPOINT_MIN_RANGE = (0.50, 0.99)
MAX_ENDPOINT_THRESHOLDS = 20
MAX_PATTERN_LENGTH = 200


def _num(value: Any, lo: float, hi: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    if not (lo <= float(value) <= hi):
        raise ValueError(f"{label} must be between {lo:.2f} and {hi:.2f}")
    return round(float(value), 2)


def validate_detection_config(raw: Any) -> Optional[dict]:
    """Return a normalised config dict, or None for an empty config. Raises ValueError."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("detection_config must be an object")
    unknown = set(raw) - {"attack_threshold", "block_confidence_threshold", "agent_min_confidence", "endpoint_thresholds"}
    if unknown:
        raise ValueError(f"unknown detection_config keys: {', '.join(sorted(unknown))}")

    out: dict = {}
    if raw.get("attack_threshold") is not None:
        out["attack_threshold"] = _num(raw["attack_threshold"], *ATTACK_THRESHOLD_RANGE, "attack_threshold")
    if raw.get("block_confidence_threshold") is not None:
        out["block_confidence_threshold"] = _num(
            raw["block_confidence_threshold"], *BLOCK_THRESHOLD_RANGE, "block_confidence_threshold",
        )

    agents = raw.get("agent_min_confidence")
    if agents:
        if not isinstance(agents, dict):
            raise ValueError("agent_min_confidence must be an object")
        cleaned: dict[str, float] = {}
        for name, value in agents.items():
            if name not in AGENT_NAMES:
                raise ValueError(f"unknown agent: {name}")
            if value is None:
                continue
            cleaned[name] = _num(value, *AGENT_MIN_RANGE, f"agent_min_confidence.{name}")
        if cleaned:
            out["agent_min_confidence"] = cleaned

    endpoints = raw.get("endpoint_thresholds")
    if endpoints:
        if not isinstance(endpoints, list):
            raise ValueError("endpoint_thresholds must be a list")
        if len(endpoints) > MAX_ENDPOINT_THRESHOLDS:
            raise ValueError(f"at most {MAX_ENDPOINT_THRESHOLDS} endpoint thresholds are allowed")
        rows: list[dict] = []
        seen: set[str] = set()
        for row in endpoints:
            if not isinstance(row, dict):
                raise ValueError("each endpoint threshold must be an object")
            pattern = row.get("pattern")
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError("endpoint pattern is required")
            pattern = pattern.strip()
            if len(pattern) > MAX_PATTERN_LENGTH or not pattern.startswith("/"):
                raise ValueError("endpoint pattern must start with / and be at most 200 characters")
            if "*" in pattern[:-1]:
                raise ValueError("endpoint pattern may only use * as the last character")
            if pattern in seen:
                raise ValueError(f"duplicate endpoint pattern: {pattern}")
            seen.add(pattern)
            rows.append({
                "pattern": pattern,
                "min_confidence": _num(row.get("min_confidence"), *ENDPOINT_MIN_RANGE, "min_confidence"),
            })
        if rows:
            out["endpoint_thresholds"] = rows

    return out or None


def effective_detection_config(tier: str, stored: Any) -> dict:
    """The config the pipeline should apply: stored values only for eligible tiers.

    Never raises. A malformed stored value is treated as no config.
    """
    if tier not in CUSTOM_THRESHOLD_TIERS or not stored:
        return {}
    try:
        return validate_detection_config(stored) or {}
    except ValueError:
        return {}


def endpoint_matches(pattern: str, endpoint: str) -> bool:
    if pattern.endswith("*"):
        return endpoint.startswith(pattern[:-1])
    return endpoint == pattern


def endpoint_minimum(config: dict, endpoint: Optional[str]) -> Optional[float]:
    """Highest minimum confidence among the patterns matching this endpoint."""
    if not endpoint:
        return None
    mins = [
        row["min_confidence"]
        for row in config.get("endpoint_thresholds", [])
        if endpoint_matches(row["pattern"], endpoint)
    ]
    return max(mins) if mins else None
