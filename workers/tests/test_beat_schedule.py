"""Phase 14 F-001: the beat schedule loads with `-A workers.celery_app`.

Every beat command in the repo is `celery -A workers.celery_app beat`. Nothing
else imported workers/beat.py, so beat used to start with an empty schedule
and no periodic task (polling, billing, purges, metrics) ever ran.
"""
from __future__ import annotations

import subprocess
import sys

EXPECTED = {
    "poll-all-clients-every-15min",
    "send-trial-reminders-daily",
    "purge-deleted-accounts-daily",
    "reset-monthly-usage-counters",
    "purge-expired-data-daily",
    "billing-cycle-daily",
    "metrics-snapshot-daily",
    "reconcile-payments-daily",
}


def test_importing_the_celery_app_loads_the_beat_schedule():
    from workers.celery_app import celery_app

    assert set(celery_app.conf.beat_schedule) == EXPECTED


def test_every_scheduled_task_is_registered_with_the_app():
    from workers.celery_app import celery_app

    celery_app.loader.import_default_modules()
    for name, entry in celery_app.conf.beat_schedule.items():
        assert entry["task"] in celery_app.tasks, f"{name}: {entry['task']} not registered"


def test_fresh_interpreter_sees_the_schedule():
    # A clean process is what `celery beat` is: no test module has imported
    # workers.beat on its behalf.
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "from workers.celery_app import celery_app; "
            "print(len(celery_app.conf.beat_schedule))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip().splitlines()[-1] == str(len(EXPECTED))
