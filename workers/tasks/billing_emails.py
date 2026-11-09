"""
workers/tasks/billing_emails.py: Phase 5 Celery task that sends one billing
email. api/billing_notify.notify() queues it, api/billing_emails.py does the
work (recipients, content, sending).

Module-level imports only: a lazy import inside a Celery task body can fail
intermittently in a forked worker child. This module must also be listed in
the `include` of workers/celery_app.py or a worker never registers the task
(producers enqueue it without noticing).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from api.billing_emails import send_billing_emails
from db.models import Bill, Organization, Payment
from db.session import SessionLocal
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.billing_emails.send_billing_email")
def send_billing_email(
    kind: str, org_id: str, bill_id: str | None = None, payment_id: str | None = None
) -> int:
    """Send one billing email of `kind` for the org. Returns the number of
    recipients it was sent to (0 when the org is gone)."""
    db = SessionLocal()
    try:
        org = db.get(Organization, org_id)
        if org is None or org.deleted_at is not None:
            logger.info("billing email %s skipped: org %s is gone", kind, org_id)
            return 0
        bill = db.get(Bill, bill_id) if bill_id else None
        payment = db.get(Payment, payment_id) if payment_id else None
        return send_billing_emails(db, kind, org, bill, payment)
    finally:
        db.close()
