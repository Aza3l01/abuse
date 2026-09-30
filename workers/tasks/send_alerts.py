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

from db.models import AlertSent, Organization, Verdict
from db.session import SessionLocal
from api.auth_utils import send_email, _email_html, _p, FROM_ALERTS, REPLY_TO_ALERTS, FROM_BILLING, REPLY_TO_BILLING, FRONTEND_URL
from api.tiers import CALL_VOLUME_CAPS, MANUAL_BLOCK_TIERS

logger = logging.getLogger(__name__)

_CHANNEL = "email"


def build_alert_email(verdict) -> tuple[str, str, str]:
    """Compose the (subject, body_text, body_html) for a threat alert email.

    Shared by the real `send_alert_email` task and item 20's `POST
    /alerts/test` endpoint, so a test alert exercises the exact same
    rendering path a real one does. `verdict` only needs to duck-type
    Verdict's fields (severity, ip, method, endpoint, threat_type,
    confidence, timestamp). item 20's test alert uses a non-persisted
    stand-in object, not a real row.
    """
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
    return subject, body_text, body_html


@celery_app.task(
    name="workers.tasks.send_alerts.send_alert_email",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def send_alert_email(self, verdict_id: str, org_id: str) -> dict:
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
        # Load verdict + org
        # ------------------------------------------------------------------
        verdict: Verdict | None = db.query(Verdict).filter(Verdict.id == verdict_id).first()
        if verdict is None:
            logger.warning("send_alert_email: verdict %s not found", verdict_id)
            return {"status": "skipped", "reason": "verdict_not_found"}

        org: Organization | None = db.query(Organization).filter(Organization.id == org_id).first()
        if org is None or not org.alert_email:
            logger.warning("send_alert_email: no alert_email for org %s", org_id)
            return {"status": "skipped", "reason": "no_alert_email"}

        # Item 70 (section 4): the free tier is bare-bones by design, no
        # email alerts, dashboard only. MANUAL_BLOCK_TIERS happens to equal
        # "every paid tier" today, reused here instead of a bare string so
        # this stays correct if the paid ladder ever changes.
        if org.tier not in MANUAL_BLOCK_TIERS:
            logger.debug("send_alert_email: free tier, skipping email for org %s", org_id)
            return {"status": "skipped", "reason": "free_tier"}

        # Item 22: severity threshold ("All threats" default vs
        # "High + Critical only")
        if org.alert_severity_threshold == "high_critical_only" and verdict.severity not in ("high", "critical"):
            logger.debug("send_alert_email: below severity threshold for org %s", org_id)
            return {"status": "skipped", "reason": "below_severity_threshold"}

        # ------------------------------------------------------------------
        # Compose and send
        # ------------------------------------------------------------------
        subject, body_text, body_html = build_alert_email(verdict)

        success = send_email(
            to=org.alert_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            from_address=FROM_ALERTS,
            reply_to=REPLY_TO_ALERTS,
        )
        status = "sent" if success else "failed"

        # ------------------------------------------------------------------
        # Record the dispatch attempt (sent or failed — avoids retry spam)
        # ------------------------------------------------------------------
        db.add(AlertSent(
            id=str(uuid.uuid4()),
            org_id=org_id,
            verdict_id=verdict_id,
            channel=_CHANNEL,
            sent_at=datetime.now(timezone.utc),
            status=status,
            delivery_error=None if success else "Resend rejected or failed to deliver this message.",
        ))
        db.commit()

        logger.info("send_alert_email: verdict=%s status=%s to=%s", verdict_id, status, org.alert_email)
        return {"status": status}

    except Exception as exc:
        db.rollback()
        logger.exception("send_alert_email: error for verdict %s: %s", verdict_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(
    name="workers.tasks.send_alerts.send_quota_warning_email",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def send_quota_warning_email(self, org_id: str, level: str) -> dict:
    """Item 30 (section 5) soft-limit email: never pauses scanning, this is
    a notice only. `level` is "warning" (80% of the tier's monthly call
    volume) or "exceeded" (100%). Idempotency (one email per threshold per
    billing month) is enforced by the caller (process_logs.py's
    _check_quota_thresholds), not here.
    """
    db = SessionLocal()
    try:
        org: Organization | None = db.query(Organization).filter(Organization.id == org_id).first()
        if org is None or not org.alert_email:
            logger.warning("send_quota_warning_email: no alert_email for org %s", org_id)
            return {"status": "skipped", "reason": "no_alert_email"}

        cap = CALL_VOLUME_CAPS.get(org.tier)
        used = org.monthly_requests_processed or 0
        cap_display = f"{cap:,}" if cap else "your plan's"
        used_display = f"{used:,}"

        if level == "exceeded":
            subject = "You've reached your Clew monthly call volume"
            heading = "Monthly call volume reached"
            headline = f"Your organisation has processed {used_display} API calls this month, reaching {cap_display} call/month volume."
        else:
            subject = "Approaching your Clew monthly call volume"
            heading = "Approaching your monthly call volume"
            headline = f"Your organisation has processed {used_display} API calls this month, over 80% of {cap_display} call/month volume."

        note = "Clew keeps scanning your traffic regardless. Consider upgrading for a higher monthly volume."
        body_text = f"{headline}\n\n{note}\n{FRONTEND_URL}/dashboard/settings#billing"
        body_html = _email_html(
            heading=heading,
            body_html=(
                _p(headline)
                + _p(note)
                + _p(
                    f'<a href="{FRONTEND_URL}/dashboard/settings#billing" style="color:#0D0D0D;">View plans &rarr;</a>'
                )
            ),
            footer_note="You are receiving this because your organisation has email alerts enabled.",
        )

        success = send_email(
            to=org.alert_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            from_address=FROM_BILLING,
            reply_to=REPLY_TO_BILLING,
        )

        logger.info("send_quota_warning_email: org=%s level=%s status=%s", org_id, level, "sent" if success else "failed")
        return {"status": "sent" if success else "failed"}

    except Exception as exc:
        logger.exception("send_quota_warning_email: error for org %s: %s", org_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()

