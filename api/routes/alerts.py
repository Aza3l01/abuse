"""
api/routes/alerts.py: item 20, alert email delivery log + test alert.

Routes
------
GET  /alerts       : paginated log of dispatched alert emails (alerts_sent),
                     joined with the triggering verdict's basics
POST /alerts/test  : owner/admin only. Sends a real email through the same
                     Resend path as a live alert, using a non-persisted
                     dummy verdict. Does not write an alerts_sent row (there
                     is no real verdict_id to attach one to).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth_utils import send_email, FROM_ALERTS, REPLY_TO_ALERTS
from api.deps import CurrentOrg, get_current_org, get_db, require_role
from db.models import AlertSent, Verdict

router = APIRouter(tags=["alerts"])


class AlertSentOut(BaseModel):
    id:               str
    verdict_id:       str
    channel:          str
    sent_at:          datetime
    status:           str
    delivery_error:   Optional[str]
    # Denormalised triggering-verdict basics, so the frontend doesn't need a
    # second round trip per row.
    verdict_ip:          Optional[str] = None
    verdict_severity:    Optional[str] = None
    verdict_threat_type: Optional[str] = None


class AlertSentList(BaseModel):
    items: list[AlertSentOut]
    total: int
    page:  int
    limit: int


@router.get("/alerts", response_model=AlertSentList)
def list_alerts_sent(
    page:        int = Query(1, ge=1),
    limit:       int = Query(25, ge=1, le=100),
    db:          Session    = Depends(get_db),
    current_org: CurrentOrg = Depends(get_current_org),
):
    q = (
        db.query(AlertSent, Verdict)
        .outerjoin(Verdict, Verdict.id == AlertSent.verdict_id)
        .filter(AlertSent.org_id == current_org.id)
        .order_by(AlertSent.sent_at.desc())
    )
    total = q.count()
    rows = q.offset((page - 1) * limit).limit(limit).all()

    items = [
        AlertSentOut(
            id=a.id,
            verdict_id=a.verdict_id,
            channel=a.channel,
            sent_at=a.sent_at,
            status=a.status,
            delivery_error=a.delivery_error,
            verdict_ip=v.ip if v else None,
            verdict_severity=v.severity if v else None,
            verdict_threat_type=v.threat_type if v else None,
        )
        for a, v in rows
    ]
    return AlertSentList(items=items, total=total, page=page, limit=limit)


class TestAlertOut(BaseModel):
    status:  str   # 'sent' | 'failed'
    message: str


@router.post("/alerts/test", response_model=TestAlertOut)
def send_test_alert(current_org: CurrentOrg = Depends(require_role("owner", "admin"))):
    from workers.tasks.send_alerts import build_alert_email

    org = current_org.organization
    if not org.alert_email:
        return TestAlertOut(status="failed", message="Set an alert email in Settings first.")

    dummy_verdict = SimpleNamespace(
        ip="203.0.113.42",
        method="POST",
        endpoint="/api/login",
        threat_type="credential_stuffing",
        severity="critical",
        confidence=0.97,
        timestamp=datetime.now(timezone.utc),
    )
    subject, body_text, body_html = build_alert_email(dummy_verdict)
    subject = f"[Clew Test] {subject}"

    success = send_email(
        to=org.alert_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        from_address=FROM_ALERTS,
        reply_to=REPLY_TO_ALERTS,
    )
    if success:
        return TestAlertOut(status="sent", message=f"Test alert sent to {org.alert_email}.")
    return TestAlertOut(status="failed", message="Failed to send, check your Resend configuration.")
