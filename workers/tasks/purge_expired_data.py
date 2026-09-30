"""
workers/tasks/purge_expired_data.py: item 30 (section 5) daily tiered
retention purge.

Runs daily. For every org, looks up its tier's retention window
(RETENTION_DAYS in api/tiers.py) and hard-deletes alerts_sent / verdicts /
scan_runs / ip_memory rows older than that cutoff. Enterprise
(RETENTION_DAYS value None, "Unlimited") is skipped entirely: no cutoff to
enforce.

Deletion order is FK-safe, per section 5's own spec: alerts_sent
references verdicts (ondelete="CASCADE"), so it is purged first. The other
three have no FK dependents among each other, deleted in the same order
section 5 lists them (verdicts, then scan_runs, then ip_memory) for
consistency with that spec, not because their relative order matters.

Hard delete, no soft-hide, per section 5's own decision: simpler, and
matches the DPDP data-minimisation language already in the Privacy Policy.

Unrelated to purge_deleted_accounts.py: that task removes whole
Organizations/Clients whose owner requested account deletion (item 40).
This task runs against every live org, purging only old log-derived rows,
not the org itself.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from db.models import AlertSent, IpMemory, Organization, ScanRun, Verdict
from db.session import SessionLocal
from api.tiers import RETENTION_DAYS
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.purge_expired_data.purge_expired_data")
def purge_expired_data() -> dict:
    db = SessionLocal()
    totals = {"alerts_sent": 0, "verdicts": 0, "scan_runs": 0, "ip_memory": 0}
    try:
        now = datetime.now(timezone.utc)
        orgs = db.query(Organization.id, Organization.tier).all()

        for org_id, tier in orgs:
            days = RETENTION_DAYS.get(tier)
            if days is None:
                continue  # enterprise (or an unrecognised tier): unlimited, nothing to purge
            cutoff = now - timedelta(days=days)

            totals["alerts_sent"] += (
                db.query(AlertSent)
                .filter(AlertSent.org_id == org_id, AlertSent.sent_at < cutoff)
                .delete(synchronize_session=False)
            )
            totals["verdicts"] += (
                db.query(Verdict)
                .filter(Verdict.org_id == org_id, Verdict.timestamp < cutoff)
                .delete(synchronize_session=False)
            )
            totals["scan_runs"] += (
                db.query(ScanRun)
                .filter(ScanRun.org_id == org_id, ScanRun.scanned_at < cutoff)
                .delete(synchronize_session=False)
            )
            totals["ip_memory"] += (
                db.query(IpMemory)
                .filter(IpMemory.org_id == org_id, IpMemory.last_seen < cutoff)
                .delete(synchronize_session=False)
            )
            db.commit()

        logger.info("purge_expired_data: purged %s", totals)
        return totals
    finally:
        db.close()
