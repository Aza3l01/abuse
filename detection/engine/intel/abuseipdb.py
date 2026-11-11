"""AbuseIPDB live lookups for the KnowledgeAgent (Phase 8).

Optional: with no ABUSEIPDB_API_KEY nothing here runs and the static seed in
datasets/threat_intel_cache.json stays the only source. Results are cached in
Redis for 24 hours (the reputation of a public address is not tenant data, so
the cache is shared) and a daily lookup counter keeps the account under the
free plan's 1000 checks a day. Every failure is soft: lookup() returns None.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_API_URL = "https://api.abuseipdb.com/api/v2/check"
_CACHE_PREFIX = "clew:abuseipdb:ip:"
_COUNTER_PREFIX = "clew:abuseipdb:count:"
DEFAULT_DAILY_CAP = 900
DEFAULT_CACHE_TTL_SECONDS = 24 * 3600
_FAILURE_CACHE_TTL_SECONDS = 300
# After this many network failures in a row the client stops calling out, so an
# AbuseIPDB outage cannot add a timeout to every batch.
_MAX_CONSECUTIVE_FAILURES = 3
KNOWN_BAD_MIN_SCORE = 75


class AbuseIpdbClient:
    def __init__(
        self,
        api_key: str,
        redis_client: Optional[Any] = None,
        daily_cap: int = DEFAULT_DAILY_CAP,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        timeout: float = 3.0,
        http_get: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._key = api_key
        self._redis = redis_client
        self._daily_cap = daily_cap
        self._ttl = cache_ttl_seconds
        self._timeout = timeout
        self._http_get = http_get
        self._local_cache: dict[str, Optional[int]] = {}
        self._local_counts: dict[str, int] = {}
        self.network_calls = 0
        self._consecutive_failures = 0

    @staticmethod
    def _is_public(ip: str) -> bool:
        try:
            return ipaddress.ip_address(ip).is_global
        except ValueError:
            return False

    def _under_cap(self) -> bool:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        try:
            if self._redis is not None:
                key = f"{_COUNTER_PREFIX}{day}"
                count = int(self._redis.incr(key))
                if count == 1:
                    self._redis.expire(key, 2 * 24 * 3600)
            else:
                count = self._local_counts.get(day, 0) + 1
                self._local_counts[day] = count
        except Exception as exc:
            logger.warning("AbuseIPDB: counter unavailable, skipping lookup: %s", exc)
            return False
        return count <= self._daily_cap

    def _cache_get(self, ip: str) -> tuple[bool, Optional[int]]:
        if self._redis is None:
            return (ip in self._local_cache), self._local_cache.get(ip)
        try:
            raw = self._redis.get(f"{_CACHE_PREFIX}{ip}")
        except Exception:
            return False, None
        if raw is None:
            return False, None
        try:
            return True, json.loads(raw).get("score")
        except Exception:
            return False, None

    def _cache_set(self, ip: str, score: Optional[int], ttl: int) -> None:
        if self._redis is None:
            self._local_cache[ip] = score
            return
        try:
            self._redis.set(f"{_CACHE_PREFIX}{ip}", json.dumps({"score": score}), ex=ttl)
        except Exception:
            pass

    def lookup(self, ip: str) -> Optional[int]:
        """AbuseIPDB confidence score 0-100, or None if unknown or unavailable."""
        if not self._is_public(ip):
            return None
        cached, score = self._cache_get(ip)
        if cached:
            return score
        if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            return None
        if not self._under_cap():
            return None
        getter = self._http_get
        if getter is None:
            import httpx
            getter = httpx.get
        self.network_calls += 1
        try:
            resp = getter(
                _API_URL,
                params={"ipAddress": ip, "maxAgeInDays": 90},
                headers={"Key": self._key, "Accept": "application/json"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            score = int(resp.json()["data"]["abuseConfidenceScore"])
        except Exception as exc:
            logger.warning("AbuseIPDB: lookup failed for %s: %s", ip, type(exc).__name__)
            self._consecutive_failures += 1
            self._cache_set(ip, None, _FAILURE_CACHE_TTL_SECONDS)
            return None
        self._consecutive_failures = 0
        self._cache_set(ip, score, self._ttl)
        return score

    def is_known_bad(self, ip: str) -> Optional[bool]:
        score = self.lookup(ip)
        return None if score is None else score >= KNOWN_BAD_MIN_SCORE
