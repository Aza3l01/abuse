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
        "workers.tasks.send_alerts",
        "workers.tasks.trial_reminders",
        "workers.tasks.purge_deleted_accounts",
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
