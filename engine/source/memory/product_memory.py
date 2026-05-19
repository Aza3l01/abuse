"""
ProductSharedMemory — SharedMemory with Redis-backed LTM persistence.

In the research engine, SharedMemory is entirely in-process and resets
on every run. In the product, LTM state (baselines, agent outcome history,
IAT reference pools) must survive Celery worker restarts.

Architecture:
  - STM : unchanged — in-process sliding window per IP. Correct for the
          single-client-per-worker model (one Celery worker handles all
          batches for one client sequentially).
  - LTM : serialised as JSON to Redis key `clew:ltm:{client_id}` on each
          flush; restored from Redis on __init__. TTL = 30 days.
  - Board: unchanged — cleared per batch as normal.

Usage (in the Celery task):
    from engine.memory.product_memory import ProductSharedMemory

    mem = ProductSharedMemory(client_id, redis_client=redis_client)
    orchestrator = MetaAgentOrchestrator(mem)
    verdict = orchestrator.run(records)
    mem.flush()   # persist LTM back to Redis
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Optional

from engine.memory.shared_memory import SharedMemory

logger = logging.getLogger(__name__)

_LTM_KEY_PREFIX = "clew:ltm:"
_LTM_TTL_SECONDS = 30 * 24 * 3600  # 30 days


class ProductSharedMemory(SharedMemory):
    """
    SharedMemory subclass that persists LTM state to Redis.
    Safe to construct without a redis_client — falls back to pure in-process
    behaviour (useful for unit tests).
    """

    def __init__(
        self,
        client_id: str,
        redis_client: Optional[Any] = None,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(window_seconds=window_seconds)
        self._client_id = client_id
        self._redis = redis_client
        self._redis_key = f"{_LTM_KEY_PREFIX}{client_id}"

        if self._redis is not None:
            self._load_ltm()

    # ------------------------------------------------------------------
    # LTM serialisation helpers
    # ------------------------------------------------------------------

    def _dump_ltm(self) -> dict:
        """Serialise all LTM state to a JSON-compatible dict."""
        ltm = self.ltm
        with ltm._lock:
            data: dict = {
                "endpoint_rates": {k: list(v) for k, v in ltm._endpoint_rates.items()},
                "ip_auth_failures": {k: list(v) for k, v in ltm._ip_auth_failures.items()},
                "ip_rates": {k: list(v) for k, v in ltm._ip_rates.items()},
                "batch_count": ltm._batch_count,
                "iat_reference": list(getattr(ltm, "_iat_reference", [])),
                # tuples → [bool, bool] lists for JSON compatibility
                "agent_outcomes": {
                    name: [[int(p), int(v)] for p, v in pairs]
                    for name, pairs in getattr(ltm, "_agent_outcomes", {}).items()
                },
                "agent_batch_counts": dict(getattr(ltm, "_agent_batch_counts", {})),
                "batch_stats": {
                    name: list(snapshots)
                    for name, snapshots in getattr(ltm, "_batch_stats", {}).items()
                },
            }
        return data

    def _load_ltm(self) -> None:
        """Restore LTM state from Redis. Silently skips on any error."""
        try:
            raw = self._redis.get(self._redis_key)
            if not raw:
                return
            data: dict = json.loads(raw)
        except Exception as exc:
            logger.warning("ProductSharedMemory: failed to load LTM from Redis: %s", exc)
            return

        ltm = self.ltm
        with ltm._lock:
            ltm._endpoint_rates = defaultdict(
                list, {k: list(v) for k, v in data.get("endpoint_rates", {}).items()}
            )
            ltm._ip_auth_failures = defaultdict(
                list, {k: list(v) for k, v in data.get("ip_auth_failures", {}).items()}
            )
            ltm._ip_rates = defaultdict(
                list, {k: list(v) for k, v in data.get("ip_rates", {}).items()}
            )
            ltm._batch_count = data.get("batch_count", 0)
            ltm._iat_reference = data.get("iat_reference", [])
            ltm._agent_outcomes = defaultdict(
                list,
                {
                    name: [(bool(p), bool(v)) for p, v in pairs]
                    for name, pairs in data.get("agent_outcomes", {}).items()
                },
            )
            ltm._agent_batch_counts = dict(data.get("agent_batch_counts", {}))
            ltm._batch_stats = defaultdict(
                list,
                {k: list(v) for k, v in data.get("batch_stats", {}).items()},
            )

        logger.debug(
            "ProductSharedMemory: loaded LTM for client=%s  batch_count=%d",
            self._client_id,
            ltm._batch_count,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Write LTM snapshot back to Redis. Call once after each batch."""
        if self._redis is None:
            return
        try:
            payload = json.dumps(self._dump_ltm())
            self._redis.set(self._redis_key, payload, ex=_LTM_TTL_SECONDS)
            logger.debug("ProductSharedMemory: flushed LTM for client=%s", self._client_id)
        except Exception as exc:
            logger.error("ProductSharedMemory: failed to flush LTM to Redis: %s", exc)
