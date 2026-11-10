"""api/analytics.py: Phase 11 PostHog (EU) server side events and errors.

Everything here is best effort and silent: a PostHog outage, a missing key or
a bad payload must never fail a request, a payment or a Celery task. With
POSTHOG_API_KEY blank (the local default) every function is a no-op and no
extra database query is made.

Identity: events are identified by the org owner's Client UUID and nothing
else. No email, name, company name, IP or log content is ever attached. The
browser identifies with the same UUID (DashboardGate), so web and server
events join in PostHog.

Events tied to a database change (subscription_started, payment_captured,
plan_cancelled) are queued on the SQLAlchemy Session and sent only after that
Session commits, so a rolled back payment or downgrade never emits an event.
Events that read state without changing it (org_activated, bill_overdue) are
sent directly and de-duplicated with a Redis SET NX key.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

import redis
from posthog import Posthog
from sqlalchemy import event
from sqlalchemy.orm import Session

from db.models import OrganizationMember

logger = logging.getLogger(__name__)

DEFAULT_HOST = "https://eu.i.posthog.com"
_QUEUE_KEY = "posthog_events"
# How long a "once" key lives. Longer than any event it guards can recur.
_ONCE_TTL_SECONDS = 60 * 60 * 24 * 400

_client: Posthog | None = None
_client_pid: int | None = None
_lock = threading.Lock()
_redis: redis.Redis | None = None


def enabled() -> bool:
    return bool(os.environ.get("POSTHOG_API_KEY", "").strip())


def _get_client() -> Posthog | None:
    """One client per process. Built lazily and rebuilt after a fork, because
    the SDK's sender thread does not survive one."""
    global _client, _client_pid
    key = os.environ.get("POSTHOG_API_KEY", "").strip()
    if not key:
        return None
    pid = os.getpid()
    with _lock:
        if _client is None or _client_pid != pid:
            _client = Posthog(
                key,
                host=os.environ.get("POSTHOG_HOST", "").strip() or DEFAULT_HOST,
                flush_at=20,
                flush_interval=5.0,
                timeout=5,
                max_retries=1,
            )
            _client_pid = pid
        return _client


def capture(distinct_id: str, event_name: str, properties: dict[str, Any] | None = None) -> None:
    """Send one event now. Never raises."""
    try:
        client = _get_client()
        if client is None:
            return
        client.capture(event_name, distinct_id=distinct_id, properties=properties or {})
    except Exception:
        logger.debug("analytics: capture of %s failed", event_name, exc_info=True)


def capture_exception(exc: BaseException, properties: dict[str, Any] | None = None) -> None:
    """Send an error report (stack trace, no local variables). Never raises."""
    try:
        client = _get_client()
        if client is None:
            return
        client.capture_exception(exc, properties=properties or {})
    except Exception:
        logger.debug("analytics: capture_exception failed", exc_info=True)


def flush() -> None:
    """Block briefly until queued events are sent. Called after Celery tasks,
    because a prefork child can be recycled before the sender thread runs."""
    try:
        if _client is not None and _client_pid == os.getpid():
            _client.flush()
    except Exception:
        logger.debug("analytics: flush failed", exc_info=True)


def owner_client_id(db, org_id: str) -> str | None:
    """The org owner's Client UUID, the distinct id for org level events."""
    row = (
        db.query(OrganizationMember.client_id)
        .filter(OrganizationMember.org_id == org_id, OrganizationMember.role == "owner")
        .order_by(OrganizationMember.created_at)
        .first()
    )
    return row[0] if row else None


def major_units(minor: int | None) -> float | None:
    """Paise or cents to rupees or dollars."""
    return None if minor is None else round(minor / 100, 2)


# --- events tied to a database change ---------------------------------------

def queue_org_event(db, org_id: str, event_name: str, properties: dict[str, Any] | None = None) -> None:
    """Queue an org level event on `db`, sent after the next commit and
    dropped on rollback. Never raises."""
    if not enabled():
        return
    try:
        distinct_id = owner_client_id(db, org_id)
        if distinct_id is None:
            return
        props = {"org_id": org_id, **(properties or {})}
        db.info.setdefault(_QUEUE_KEY, []).append((distinct_id, event_name, props))
    except Exception:
        logger.debug("analytics: could not queue %s", event_name, exc_info=True)


@event.listens_for(Session, "after_commit")
def _send_queued(session: Session) -> None:
    queued = session.info.pop(_QUEUE_KEY, None)
    for distinct_id, event_name, props in queued or ():
        capture(distinct_id, event_name, props)


@event.listens_for(Session, "after_rollback")
def _drop_queued(session: Session) -> None:
    session.info.pop(_QUEUE_KEY, None)


# --- events that read state, sent at most once ------------------------------

def _first_time(key: str) -> bool:
    """True the first time `key` is seen. False when seen before or when Redis
    cannot be reached (better to miss an event than to send a duplicate)."""
    global _redis
    try:
        if _redis is None:
            _redis = redis.Redis.from_url(
                os.environ["REDIS_URL"], socket_timeout=2, socket_connect_timeout=2
            )
        return bool(_redis.set(f"clew:posthog_once:{key}", "1", nx=True, ex=_ONCE_TTL_SECONDS))
    except Exception:
        logger.debug("analytics: once-key check failed for %s", key, exc_info=True)
        return False


def capture_org_event_once(
    db, org_id: str, event_name: str, once_key: str, properties: dict[str, Any] | None = None
) -> bool:
    """Send an org level event the first time `once_key` is seen. Returns True
    if it was sent. Never raises."""
    if not enabled():
        return False
    try:
        distinct_id = owner_client_id(db, org_id)
        if distinct_id is None or not _first_time(once_key):
            return False
        capture(distinct_id, event_name, {"org_id": org_id, **(properties or {})})
        return True
    except Exception:
        logger.debug("analytics: could not send %s", event_name, exc_info=True)
        return False
