"""
workers/tasks/send_alerts.py — Email alert task for high/critical verdicts.

Deduplication strategy: before sending, check the `alerts_sent` table for a row
with the same (verdict_id, channel).  This prevents duplicate emails if the task
is retried after a network error that occurred after Resend accepted the message.

Resend is used via `api.auth_utils.send_email`, which handles LOG_EMAILS dev mode
(prints to console instead of sending when LOG_EMAILS=1).
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
from api.auth_utils import send_email, _email_html, _p

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
        body_text = (
            f"Clew detected a {verdict.severity} severity threat.\n\n"
            f"IP:          {verdict.ip}\n"
            f"Method:      {verdict.method or 'N/A'}\n"
            f"Endpoint:    {verdict.endpoint or 'N/A'}\n"
            f"Threat type: {verdict.threat_type or 'Unknown'}\n"
            f"Confidence:  {verdict.confidence:.0%}\n"
            f"Detected at: {verdict.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
            f"Log in to the Clew dashboard to review this incident and take action.\n"
        )

        _SEVERITY_COLOURS = {
            "critical": "#E53E3E",
            "high":     "#DD6B20",
            "medium":   "#D69E2E",
            "low":      "#38A169",
        }
        badge_colour = _SEVERITY_COLOURS.get(verdict.severity.lower(), "#5A5A5A")
        badge = (
            f'<span style="display:inline-block;background:{badge_colour};color:#fff;'
            f'font-family:system-ui,-apple-system,BlinkMacSystemFont,sans-serif;'
            f'font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.07em;padding:4px 8px;margin-bottom:20px;">'
            f'{verdict.severity.upper()}</span>'
        )
        detail_row = (
            lambda label, val: (
                f'<tr>'
                f'<td style="font-family:system-ui,-apple-system,sans-serif;font-size:13px;'
                f'color:#5A5A5A;padding:4px 16px 4px 0;white-space:nowrap;">{label}</td>'
                f'<td style="font-family:\'Courier New\',Courier,monospace;font-size:13px;'
                f'color:#0D0D0D;padding:4px 0;">{val}</td>'
                f'</tr>'
            )
        )
        table = (
            '<table style="border-collapse:collapse;margin:16px 0 24px 0;width:100%;">'
            + detail_row("IP", verdict.ip)
            + detail_row("Method", verdict.method or "N/A")
            + detail_row("Endpoint", verdict.endpoint or "N/A")
            + detail_row("Threat type", verdict.threat_type or "Unknown")
            + detail_row("Confidence", f"{verdict.confidence:.0%}")
            + detail_row("Detected at", verdict.timestamp.strftime("%Y-%m-%d %H:%M UTC"))
            + '</table>'
        )
        dashboard_url = "https://clewsec.com/dashboard/alerts"
        button = (
            f'<a href="{dashboard_url}" style="display:inline-block;background:#0D0D0D;'
            f'color:#F5F5F5;padding:12px 24px;'
            f'font-family:system-ui,-apple-system,BlinkMacSystemFont,sans-serif;'
            f'font-size:14px;font-weight:600;text-decoration:none;">View in Dashboard</a>'
        )
        body_html = _email_html(
            heading="Threat detected",
            body_html=badge + table + button,
            footer_note="You are receiving this because email alerts are enabled for your account.",
        )

        success = send_email(
            to=client.alert_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
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
