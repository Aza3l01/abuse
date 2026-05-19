"""
workers/tasks/send_alerts.py — Email alert task for high/critical verdicts.

Deduplication strategy: before sending, check the `alerts_sent` table for a row
with the same (verdict_id, channel).  This prevents duplicate emails if the task
is retried after a network error that occurred after SES accepted the message.

SES is used via `api.auth_utils.send_email`, which handles LOG_EMAILS dev mode
(prints to console instead of calling SES when LOG_EMAILS=1).
"""
from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from workers.celery_app import celery_app

# ---------------------------------------------------------------------------
# Path bootstrap — mirrors process_logs.py
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent.parent
for _p in [str(_REPO_ROOT), str(_REPO_ROOT / "engine")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from db.models import AlertSent, Client, Verdict
from db.session import SessionLocal
from api.auth_utils import send_email

logger = logging.getLogger(__name__)

_CHANNEL = "email"


@celery_app.task(
    name="workers.tasks.send_alerts.send_alert_email",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def send_alert_email(self, verdict_id: str, client_id: str) -> dict:
    """
    Send a security alert email for a single verdict.

    Idempotent: returns early (status='already_sent') if an alerts_sent row
    already exists for this (verdict_id, 'email') pair.
    """
    db = SessionLocal()
    try:
        # ------------------------------------------------------------------
        # Deduplication check
        # ------------------------------------------------------------------
        already = (
            db.query(AlertSent)
            .filter(
                AlertSent.verdict_id == verdict_id,
                AlertSent.channel == _CHANNEL,
            )
            .first()
        )
        if already:
            logger.debug("send_alert_email: already sent for verdict %s — skipping", verdict_id)
            return {"status": "already_sent"}

        # ------------------------------------------------------------------
        # Load verdict + client
        # ------------------------------------------------------------------
        verdict: Verdict | None = db.query(Verdict).filter(Verdict.id == verdict_id).first()
        if verdict is None:
            logger.warning("send_alert_email: verdict %s not found", verdict_id)
            return {"status": "skipped", "reason": "verdict_not_found"}

        client: Client | None = db.query(Client).filter(Client.id == client_id).first()
        if client is None or not client.alert_email:
            logger.warning("send_alert_email: no alert_email for client %s", client_id)
            return {"status": "skipped", "reason": "no_alert_email"}

        if client.tier == "free":
            logger.debug("send_alert_email: free tier — skipping email for client %s", client_id)
            return {"status": "skipped", "reason": "free_tier"}

        # ------------------------------------------------------------------
        # Compose and send
        # ------------------------------------------------------------------
        subject = f"[Clew] {verdict.severity.upper()} threat detected — {verdict.ip}"
        body = (
            f"Clew detected a {verdict.severity} severity threat.\n\n"
            f"IP:          {verdict.ip}\n"
            f"Method:      {verdict.method or 'N/A'}\n"
            f"Endpoint:    {verdict.endpoint or 'N/A'}\n"
            f"Threat type: {verdict.threat_type or 'Unknown'}\n"
            f"Confidence:  {verdict.confidence:.0%}\n"
            f"Detected at: {verdict.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
            f"Log in to the Clew dashboard to review this incident and take action.\n"
        )

        success = send_email(to=client.alert_email, subject=subject, body_text=body)
        status = "sent" if success else "failed"

        # ------------------------------------------------------------------
        # Record the dispatch attempt (sent or failed — avoids retry spam)
        # ------------------------------------------------------------------
        db.add(AlertSent(
            id=str(uuid.uuid4()),
            client_id=client_id,
            verdict_id=verdict_id,
            channel=_CHANNEL,
            sent_at=datetime.now(timezone.utc),
            status=status,
        ))
        db.commit()

        logger.info("send_alert_email: verdict=%s status=%s to=%s", verdict_id, status, client.alert_email)
        return {"status": status}

    except Exception as exc:
        db.rollback()
        logger.exception("send_alert_email: error for verdict %s: %s", verdict_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()
