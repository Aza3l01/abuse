"""
workers/celery_app.py — Celery application factory.

All tasks import `celery_app` from here; beat also uses it.
Configuration lives here so there is a single source of truth.
"""
from __future__ import annotations

import os

from celery import Celery
from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local", override=True)  # local dev overrides (gitignored)

REDIS_URL: str = os.environ["REDIS_URL"]

celery_app = Celery(
    "clew",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "workers.tasks.process_logs",
        "workers.tasks.push_blocks",
        "workers.tasks.send_alerts",
        "workers.tasks.trial_reminders",
        "workers.tasks.purge_deleted_accounts",
        "workers.tasks.reset_usage_counters",
        "workers.tasks.purge_expired_data",
        "workers.tasks.billing_cycle",
        "workers.tasks.billing_emails",
        "workers.tasks.metrics_snapshot",
        "workers.tasks.reconcile_payments",
    ],
)

celery_app.conf.update(
    # Serialisation — JSON is safe and readable
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Retry / ack behaviour
    task_acks_late=True,           # ack only after the task function returns
    task_reject_on_worker_lost=True,

    # Result TTL — keep results for 24 h for debugging, then evict
    result_expires=86_400,

    # Beat schedule — polled from beat.py via beat_schedule attr
)

# Registers the task_postrun handler behind the ops panel's last-run times.
import workers.task_runs  # noqa: E402,F401


# Phase 11 error tracking. Both handlers are best effort (api.analytics never
# raises). Imported here, at module level, so forked workers have them ready.
from celery.signals import task_failure, task_postrun  # noqa: E402

from api import analytics  # noqa: E402


@task_failure.connect
def _report_task_failure(sender=None, task_id=None, exception=None, **kwargs):
    if exception is not None:
        analytics.capture_exception(
            exception,
            {"source": "celery", "task": getattr(sender, "name", None), "task_id": task_id},
        )


@task_postrun.connect
def _flush_analytics(**kwargs):
    # A prefork child can be recycled before PostHog's sender thread runs.
    analytics.flush()
