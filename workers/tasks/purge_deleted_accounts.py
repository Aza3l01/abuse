"""
workers/tasks/purge_deleted_accounts.py: item 40 hard-delete Beat task.

Runs daily. Any Organization or Client whose deleted_at is older than 30
days is hard-deleted (row DELETE, relying on the existing
ondelete="CASCADE" foreign keys to remove dependent rows):

- Organization  -> verdicts / ip_memory / alerts_sent / scan_runs /
  organization_members / org_invites for that org.
- Client        -> refresh_tokens / mfa_backup_codes / organization_members
  for that client.

Organizations are purged first: an org-owner deletion soft-deletes both the
Client and its Organization together (see api/routes/auth.py's
delete_account), so by the time 30 days have passed both are usually due at
once. Purging the org first, then the client, avoids relying on ordering
between two independent CASCADE paths into organization_members.

Item 62: also deletes processed_webhook_events rows older than 30 days
(the Razorpay/Stripe webhook idempotency guard's table). Folded in here
rather than a new Beat task since this one already runs daily.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from db.models import Client, Organization, ProcessedWebhookEvent
from db.session import SessionLocal
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_RETENTION_DAYS = 30


@celery_app.task(name="workers.tasks.purge_deleted_accounts.purge_deleted_accounts")
def purge_deleted_accounts() -> dict:
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)

        orgs = (
            db.query(Organization)
            .filter(Organization.deleted_at.isnot(None), Organization.deleted_at <= cutoff)
            .all()
        )
        for org in orgs:
            db.delete(org)
        db.commit()

        clients = (
            db.query(Client)
            .filter(Client.deleted_at.isnot(None), Client.deleted_at <= cutoff)
            .all()
        )
        for client in clients:
            db.delete(client)
        db.commit()

        # Item 62: same 30-day cutoff, unrelated table, just piggybacking on
        # this task's existing daily schedule rather than adding a new one.
        webhook_events_deleted = (
            db.query(ProcessedWebhookEvent)
            .filter(ProcessedWebhookEvent.created_at <= cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()

        logger.info(
            "purge_deleted_accounts: purged %d organisations, %d clients, %d webhook events",
            len(orgs), len(clients), webhook_events_deleted,
        )
        return {
            "organisations_purged": len(orgs),
            "clients_purged": len(clients),
            "webhook_events_purged": webhook_events_deleted,
        }
    finally:
        db.close()
