"""
workers/beat.py — Celery Beat scheduler.

Registers a single periodic task that wakes up every 15 minutes and fans out one
`process_logs` task per client whose S3 bucket has been configured.

Why one generic `poll_all_clients` instead of per-client schedules?
  - Adding / removing per-client schedules at runtime requires a database-backed
    scheduler (e.g. django_celery_beat). A single dispatcher task is simpler and
    has negligible overhead because the per-client `process_logs` tasks do the
    actual work on worker nodes.
  - 15 minutes matches the ALB/APIGW log delivery latency from S3, so we rarely
    waste cycles on empty buckets.

Run with:
    celery -A workers.celery_app beat --loglevel=info
"""
from __future__ import annotations

from celery.schedules import crontab

from workers.celery_app import celery_app

# ---------------------------------------------------------------------------
# Beat schedule
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {
    "poll-all-clients-every-15min": {
        "task":     "workers.tasks.process_logs.poll_all_clients",
        "schedule": crontab(minute="*/15"),
    },
    "send-trial-reminders-daily": {
        "task":     "workers.tasks.trial_reminders.send_trial_reminders",
        "schedule": crontab(hour=9, minute=0),
    },
    "purge-deleted-accounts-daily": {
        "task":     "workers.tasks.purge_deleted_accounts.purge_deleted_accounts",
        "schedule": crontab(hour=3, minute=0),
    },
    # Item 30 (section 5): zero every org's monthly call counter on the 1st.
    "reset-monthly-usage-counters": {
        "task":     "workers.tasks.reset_usage_counters.reset_monthly_counters",
        "schedule": crontab(hour=0, minute=0, day_of_month="1"),
    },
    # Item 30 (section 5): daily tiered retention purge across all four tables.
    "purge-expired-data-daily": {
        "task":     "workers.tasks.purge_expired_data.purge_expired_data",
        "schedule": crontab(hour=4, minute=0),
    },
    # Phase 3: daily bill engine. 19:00 UTC is 00:30 IST, just after the IST
    # midnight the billing rules (the 1st, 17th, 20th) are evaluated at.
    "billing-cycle-daily": {
        "task":     "workers.tasks.billing_cycle.billing_cycle",
        "schedule": crontab(hour=19, minute=0),
    },
    # Phase 6: daily business metrics snapshot, 30 minutes after billing_cycle.
    "metrics-snapshot-daily": {
        "task":     "workers.tasks.metrics_snapshot.metrics_snapshot",
        "schedule": crontab(hour=19, minute=30),
    },
    # Phase 10: daily Razorpay vs local payments check, 19:45 UTC (01:15 IST).
    # Reports differences to the ops panel, applies nothing.
    "reconcile-payments-daily": {
        "task":     "workers.tasks.reconcile_payments.reconcile_payments",
        "schedule": crontab(hour=19, minute=45),
    },
}
