"""workers/heartbeat.py: Better Stack heartbeat pings.

A heartbeat is a URL the service calls on a schedule. Better Stack alerts
when a ping does not arrive in time, which is how a dead Beat or a stuck
worker gets noticed. An empty URL (the local default) means no ping.

A ping never raises and never blocks a task for more than a few seconds: a
monitoring problem must not become an outage.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

# Seconds. Short on purpose, the ping runs inline in the task.
_TIMEOUT = 3


def ping(env_name: str, failed: bool = False) -> bool:
    """Ping the heartbeat URL held in the environment variable `env_name`.
    With failed=True the ping goes to <url>/fail, which Better Stack counts as
    an immediate failure. Returns True if a ping was sent and answered."""
    url = os.environ.get(env_name, "").strip().rstrip("/")
    if not url:
        return False
    try:
        httpx.get(f"{url}/fail" if failed else url, timeout=_TIMEOUT)
        return True
    except Exception:
        logger.warning("heartbeat: ping to %s failed", env_name)
        return False
