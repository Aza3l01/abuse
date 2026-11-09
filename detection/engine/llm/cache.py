"""Per-org cache for LLM verdict explanations (Phase 8).

Keyed by the verdict signature (threat type, contributing agents, confidence
bucket). Per org on purpose: text is never shared across customers. The
explanation prompt forbids exact figures, so reusing the text for another
batch with the same signature is accurate.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

_KEY_PREFIX = "clew:llmcache:"
DEFAULT_TTL_SECONDS = 6 * 3600
DEFAULT_BUCKET_WIDTH = 0.10


class ExplanationCache:
    def __init__(
        self,
        org_id: str,
        redis_client: Optional[Any] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        bucket_width: float = DEFAULT_BUCKET_WIDTH,
    ) -> None:
        self._org_id = org_id
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._bucket_width = bucket_width
        self._local: Dict[str, str] = {}
        self.hits = 0
        self.misses = 0

    def key(self, threat_type: str, agents: Iterable[str], confidence: float) -> str:
        bucket = int(confidence / self._bucket_width + 1e-9)
        return f"{_KEY_PREFIX}{self._org_id}:{threat_type}:{'+'.join(sorted(agents))}:{bucket}"

    def get(self, key: str) -> Optional[str]:
        text: Optional[str] = None
        if self._redis is not None:
            try:
                text = self._redis.get(key)
            except Exception as exc:
                logger.warning("ExplanationCache: Redis read failed: %s", exc)
        else:
            text = self._local.get(key)
        if text:
            self.hits += 1
            return text
        self.misses += 1
        return None

    def set(self, key: str, text: str) -> None:
        if self._redis is not None:
            try:
                self._redis.set(key, text, ex=self._ttl)
            except Exception as exc:
                logger.warning("ExplanationCache: Redis write failed: %s", exc)
        else:
            self._local[key] = text
