"""workers/task_runs.py: remembers when each Celery task last ran, for the
internal ops panel's system health page.

Celery's own result backend expires results after 24 hours, which is useless
for tasks that run daily or monthly. A task_postrun handler instead keeps one
Redis hash entry per task name. Importing this module registers the handler
(workers/celery_app.py does so); it is failure-proof: a Redis problem is
swallowed so it can never break a task.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import redis
from celery.signals import task_postrun

logger = logging.getLogger(__name__)

TASK_RUNS_KEY = "clew:task_runs"

# Tasks the health page always lists, even before their first recorded run.
EXPECTED_TASKS = (
    "workers.tasks.process_logs.poll_all_clients",
    "workers.tasks.trial_reminders.send_trial_reminders",
    "workers.tasks.purge_deleted_accounts.purge_deleted_accounts",
    "workers.tasks.reset_usage_counters.reset_monthly_counters",
    "workers.tasks.purge_expired_data.purge_expired_data",
    "workers.tasks.billing_cycle.billing_cycle",
    "workers.tasks.metrics_snapshot.metrics_snapshot",
    "workers.tasks.reconcile_payments.reconcile_payments",
)

RECONCILIATION_KEY = "clew:reconciliation"

_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
        )
    return _client


def record_run(name: str, state: str, now: datetime | None = None) -> None:
    """Store the latest run of `name`. last_success_at keeps the previous value
    unless this run succeeded."""
    moment = (now or datetime.now(timezone.utc)).isoformat()
    r = _redis()
    previous = r.hget(TASK_RUNS_KEY, name)
    last_success = json.loads(previous).get("last_success_at") if previous else None
    if state == "SUCCESS":
        last_success = moment
    r.hset(TASK_RUNS_KEY, name, json.dumps({"last_run_at": moment, "state": state, "last_success_at": last_success}))


def read_runs() -> dict[str, dict]:
    """task name -> {last_run_at, state, last_success_at}. Empty if Redis is unreachable."""
    try:
        raw = _redis().hgetall(TASK_RUNS_KEY)
    except redis.exceptions.RedisError:
        return {}
    runs: dict[str, dict] = {}
    for name, value in raw.items():
        try:
            runs[name] = json.loads(value)
        except ValueError:
            continue
    return runs


def save_reconciliation(result: dict) -> None:
    """Keep the latest payment reconciliation result for the ops panel."""
    _redis().set(RECONCILIATION_KEY, json.dumps(result))


def read_reconciliation() -> dict | None:
    """The latest reconciliation result, or None if it never ran or Redis is unreachable."""
    try:
        raw = _redis().get(RECONCILIATION_KEY)
    except redis.exceptions.RedisError:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


@task_postrun.connect
def _on_task_postrun(sender=None, state=None, **_kwargs) -> None:
    try:
        if sender is not None and getattr(sender, "name", None):
            record_run(sender.name, str(state))
    except Exception:
        logger.debug("task_runs: could not record a run", exc_info=True)
