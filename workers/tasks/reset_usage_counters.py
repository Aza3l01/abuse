"""
workers/tasks/reset_usage_counters.py: item 30 (section 5) monthly counter
reset.

Runs on the 1st of each month at 00:00 UTC. Zeroes every org's
monthly_requests_processed and clears the quota_warning_sent_at /
quota_exceeded_sent_at idempotency flags, so a new billing month starts
clean and can re-trigger the 80%/100% soft-limit emails if the org crosses
them again.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from db.models import Organization
from db.session import SessionLocal
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.reset_usage_counters.reset_monthly_counters")
def reset_monthly_counters() -> dict:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        updated = (
            db.query(Organization)
            .update(
                {
                    Organization.monthly_requests_processed: 0,
                    Organization.monthly_requests_reset_at: now,
                    Organization.quota_warning_sent_at: None,
                    Organization.quota_exceeded_sent_at: None,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        logger.info("reset_monthly_counters: reset %d organisations", updated)
        return {"organisations_reset": updated}
    finally:
        db.close()
