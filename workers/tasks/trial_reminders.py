"""
workers/tasks/trial_reminders.py — item 11 trial-expiry email schedule.

Runs daily via Beat. For each org with an active, unpaid trial
(trial_ends_at set, billing_provider still pilot/null):
  - 5 days before trial_ends_at: manual_outreach (30-day) trials only —
    for self_serve's 7-day trial this would land within hours of signup.
  - 2 days before trial_ends_at: both trial_source values.
Each reminder fires at most once, tracked by the trial_reminder_5d_sent /
trial_reminder_2d_sent booleans on Organization.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import or_

from api.auth_utils import send_trial_reminder_email
from db.models import Client, Organization, OrganizationMember
from db.session import SessionLocal
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _owner_emails(db, org_id: str) -> list[str]:
    rows = (
        db.query(Client.email)
        .join(OrganizationMember, OrganizationMember.client_id == Client.id)
        .filter(OrganizationMember.org_id == org_id, OrganizationMember.role == "owner")
        .all()
    )
    return [r[0] for r in rows]


@celery_app.task(name="workers.tasks.trial_reminders.send_trial_reminders")
def send_trial_reminders() -> dict:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        pending = (
            db.query(Organization)
            .filter(
                Organization.trial_ends_at.isnot(None),
                or_(
                    Organization.billing_provider.is_(None),
                    Organization.billing_provider == "pilot",
                ),
            )
            .all()
        )

        sent = 0
        expired = 0
        for org in pending:
            trial_days_total = 30 if org.trial_source == "manual_outreach" else 7
            days_remaining = (org.trial_ends_at - now).days

            # Item 27 point 6: trial ended with no payment method added:
            # revert tier, leave a persistent dashboard banner (TrialBanner.tsx
            # already renders an "expired" message once trial_ends_at has passed).
            if org.trial_ends_at <= now and org.tier != "free":
                org.tier = "free"
                db.commit()
                expired += 1
                continue

            if (
                org.trial_source == "manual_outreach"
                and not org.trial_reminder_5d_sent
                and 0 <= days_remaining <= 5
            ):
                for email in _owner_emails(db, org.id):
                    send_trial_reminder_email(email, 5, trial_days_total)
                org.trial_reminder_5d_sent = True
                db.commit()
                sent += 1

            if not org.trial_reminder_2d_sent and 0 <= days_remaining <= 2:
                for email in _owner_emails(db, org.id):
                    send_trial_reminder_email(email, 2, trial_days_total)
                org.trial_reminder_2d_sent = True
                db.commit()
                sent += 1

        logger.info("send_trial_reminders: sent %d reminder batches, expired %d trials", sent, expired)
        return {"sent": sent, "expired": expired}
    finally:
        db.close()
