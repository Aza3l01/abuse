"""api/staff_views.py: read models for the Phase 6 ops panel.

Every view is an allow-list: fields are named one by one, nothing is dumped
from the model. Secrets are never included: the Cloudflare token, the AWS
external id and role ARN (only "is a role set"), MFA secrets and password
hashes. Raw customer data (verdict rows, IP memory) is reachable only through
raw_verdicts and raw_ips, which the route calls after a typed reason is given.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from api.billing_payments import open_bills
from api.referrals import referral_summary
from api.tiers import CALL_VOLUME_CAPS, LLM_CALL_CAPS
from db.models import (
    Bill,
    BillingEvent,
    Client,
    IpMemory,
    Organization,
    OrganizationMember,
    Payment,
    ProcessedWebhookEvent,
    StaffAuditLog,
    Verdict,
)
from workers.task_runs import EXPECTED_TASKS, read_reconciliation, read_runs

STUCK_PAYMENT_AFTER = timedelta(hours=2)
_UUID_RE = re.compile(r"[0-9a-fA-F-]{32,36}")


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def parse_org_id(org_id: str) -> str | None:
    """The canonical id string, or None if `org_id` is not a UUID."""
    try:
        return str(uuid.UUID(org_id))
    except (ValueError, AttributeError, TypeError):
        return None


def search_orgs(db, query: str, limit: int = 25) -> list[dict]:
    """Orgs matching an email, an org name or an exact org id."""
    q = query.strip()
    if len(q) < 2:
        return []
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    org_ids: set[str] = set()
    org_ids.update(
        oid for (oid,) in db.query(Organization.id)
        .filter(Organization.company_name.ilike(like, escape="\\"))
        .limit(limit)
    )
    org_ids.update(
        oid for (oid,) in db.query(OrganizationMember.org_id)
        .join(Client, Client.id == OrganizationMember.client_id)
        .filter(Client.email.ilike(like, escape="\\"))
        .limit(limit)
    )
    if _UUID_RE.fullmatch(q) and parse_org_id(q):
        org_ids.add(parse_org_id(q))
    if not org_ids:
        return []
    orgs = (
        db.query(Organization)
        .filter(Organization.id.in_(org_ids))
        .order_by(Organization.created_at.desc())
        .limit(limit)
        .all()
    )
    owners = dict(
        db.query(OrganizationMember.org_id, Client.email)
        .join(Client, Client.id == OrganizationMember.client_id)
        .filter(OrganizationMember.org_id.in_([o.id for o in orgs]), OrganizationMember.role == "owner")
        .all()
    )
    return [
        {
            "id": o.id,
            "company_name": o.company_name,
            "tier": o.tier,
            "billing_provider": o.billing_provider,
            "owner_email": owners.get(o.id),
            "created_at": _iso(o.created_at),
            "deleted": o.deleted_at is not None,
        }
        for o in orgs
    ]


def account_view(db, org: Organization, now: datetime | None = None) -> dict:
    """Metadata of one account. No raw IPs, endpoints or log lines."""
    moment = now or datetime.now(timezone.utc)
    cap = CALL_VOLUME_CAPS.get(org.tier)
    llm_cap = LLM_CALL_CAPS.get(org.tier)

    members = (
        db.query(OrganizationMember, Client)
        .join(Client, Client.id == OrganizationMember.client_id)
        .filter(OrganizationMember.org_id == org.id)
        .order_by(OrganizationMember.created_at)
        .all()
    )
    bills = (
        db.query(Bill).filter(Bill.org_id == org.id).order_by(Bill.period_start.desc()).limit(50).all()
    )
    payments = (
        db.query(Payment).filter(Payment.org_id == org.id).order_by(Payment.created_at.desc()).limit(50).all()
    )
    events = (
        db.query(BillingEvent)
        .filter(BillingEvent.org_id == org.id)
        .order_by(BillingEvent.created_at.desc())
        .limit(20)
        .all()
    )
    audit_rows = (
        db.query(StaffAuditLog)
        .filter(StaffAuditLog.org_id == org.id)
        .order_by(StaffAuditLog.created_at.desc())
        .limit(25)
        .all()
    )
    verdict_count = db.query(func.count(Verdict.id)).filter(Verdict.org_id == org.id).scalar() or 0
    ip_count = db.query(func.count(IpMemory.id)).filter(IpMemory.org_id == org.id).scalar() or 0

    return {
        "org": {
            "id": org.id,
            "company_name": org.company_name,
            "domain": org.domain,
            "tier": org.tier,
            "created_at": _iso(org.created_at),
            "deleted_at": _iso(org.deleted_at),
            "home_country": org.home_country,
            "alert_email": org.alert_email,
            "auto_block_enabled": bool(org.auto_block_enabled),
            "blocking_tos_accepted_at": _iso(org.blocking_tos_accepted_at),
            "has_aws_role": bool(org.aws_role_arn),
            "has_cloudflare_token": bool(org.cloudflare_token),
        },
        "onboarding": {
            "s3_bucket": org.s3_bucket,
            "s3_prefix": org.s3_prefix,
            "log_format": org.log_format,
            "aws_region": org.aws_region,
            "s3_connected_at": _iso(org.s3_connected_at),
            "calibration_status": org.calibration_status,
            "completed_at": _iso(org.onboarding_completed_at),
            "dismissed_at": _iso(org.onboarding_dismissed_at),
        },
        "usage": {
            "monthly_requests_processed": org.monthly_requests_processed,
            "monthly_request_cap": cap,
            "monthly_llm_calls": org.monthly_llm_calls,
            "monthly_llm_cap": llm_cap,
            "verdict_count": verdict_count,
            "ip_memory_count": ip_count,
        },
        "scan": {
            "last_scan_completed_at": _iso(org.last_scan_completed_at),
            "last_scan_status": org.last_scan_status,
            "last_scan_error": org.last_scan_error,
            "s3_status": org.s3_status,
            "s3_status_message": org.s3_status_message,
        },
        "billing": {
            "billing_provider": org.billing_provider,
            "billing_period": org.billing_period,
            "billing_currency": org.billing_currency,
            "billing_country": org.billing_country,
            "next_billing_date": _iso(org.next_billing_date),
            "first_charged_at": _iso(org.first_charged_at),
            "cancel_at_period_end": bool(org.cancel_at_period_end),
            "pending_tier": org.pending_tier,
            "pending_period": org.pending_period,
            "nonpayment_downgraded_at": _iso(org.nonpayment_downgraded_at),
            "retention_grace_tier": org.retention_grace_tier,
            "retention_grace_until": _iso(org.retention_grace_until),
            "legal_name": org.billing_legal_name,
            "address": org.billing_address,
            "gstin": org.gstin,
            "open_bill_count": len(open_bills(org.id, db)),
        },
        "trial": {
            "trial_source": org.trial_source,
            "trial_ends_at": _iso(org.trial_ends_at),
            "pilot_code_used": org.pilot_code_used,
            "reminder_5d_sent": bool(org.trial_reminder_5d_sent),
            "reminder_2d_sent": bool(org.trial_reminder_2d_sent),
        },
        "referral": referral_summary(org, db),
        "members": [
            {
                "email": client.email,
                "full_name": client.full_name,
                "role": member.role,
                "is_billing_contact": bool(member.is_billing_contact),
                "email_verified": bool(client.email_verified),
                "mfa_enabled": bool(client.mfa_enabled),
            }
            for member, client in members
        ],
        "bills": [
            {
                "id": b.id,
                "tier": b.tier,
                "period": b.period,
                "period_start": b.period_start.isoformat(),
                "period_end": b.period_end.isoformat(),
                "amount_paise": b.amount_paise,
                "currency": b.currency,
                "status": b.status,
                "due_date": b.due_date.isoformat(),
                "cancel_on": b.cancel_on.isoformat(),
                "paid_at": _iso(b.paid_at),
            }
            for b in bills
        ],
        "payments": [
            {
                "id": p.id,
                "purpose": p.purpose,
                "status": p.status,
                "amount_paise": p.amount_paise,
                "currency": p.currency,
                "razorpay_order_id": p.razorpay_order_id,
                "razorpay_payment_id": p.razorpay_payment_id,
                "manual": bool((p.line_items or {}).get("manual")),
                "reference": (p.line_items or {}).get("reference"),
                "created_at": _iso(p.created_at),
                "captured_at": _iso(p.captured_at),
                "refunded_at": _iso(p.refunded_at),
            }
            for p in payments
        ],
        "events": [
            {
                "event": e.event,
                "from_tier": e.from_tier,
                "to_tier": e.to_tier,
                "period": e.period,
                "amount_paise": e.amount_paise,
                "currency": e.currency,
                "created_at": _iso(e.created_at),
            }
            for e in events
        ],
        "audit": [audit_row(a) for a in audit_rows],
        "as_of": moment.isoformat(),
    }


def audit_row(row: StaffAuditLog) -> dict:
    return {
        "created_at": _iso(row.created_at),
        "staff_email": row.staff_email,
        "action": row.action,
        "org_id": row.org_id,
        "org_name": row.org_name_snapshot,
        "reason": row.reason,
        "details": row.details,
        "ip": row.ip,
    }


# ---------------------------------------------------------------------------
# Raw customer data: only after a typed reason, and the caller logs the view.
# ---------------------------------------------------------------------------

def raw_verdicts(db, org: Organization, limit: int) -> list[dict]:
    rows = (
        db.query(Verdict)
        .filter(Verdict.org_id == org.id)
        .order_by(Verdict.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "timestamp": _iso(v.timestamp),
            "ip": v.ip,
            "method": v.method,
            "endpoint": v.endpoint,
            "threat_type": v.threat_type,
            "severity": v.severity,
            "confidence": v.confidence,
            "blocked": bool(v.blocked),
            "explanation": v.explanation,
            "sample_logs": v.sample_logs,
        }
        for v in rows
    ]


def raw_ips(db, org: Organization, limit: int) -> list[dict]:
    rows = (
        db.query(IpMemory)
        .filter(IpMemory.org_id == org.id)
        .order_by(IpMemory.last_seen.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "ip": r.ip,
            "first_seen": _iso(r.first_seen),
            "last_seen": _iso(r.last_seen),
            "total_requests": r.total_requests,
            "threat_count": r.threat_count,
            "risk_score": r.risk_score,
            "geo_country": r.geo_country,
            "geo_asn_org": r.geo_asn_org,
            "waf_blocked": bool(r.waf_blocked),
            "cloudflare_blocked": bool(r.cloudflare_blocked),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# System health
# ---------------------------------------------------------------------------

def system_health(db, now: datetime | None = None) -> dict:
    moment = now or datetime.now(timezone.utc)
    runs = read_runs()
    names = list(EXPECTED_TASKS) + sorted(n for n in runs if n not in EXPECTED_TASKS)
    tasks = [
        {
            "name": name,
            "last_run_at": runs.get(name, {}).get("last_run_at"),
            "state": runs.get(name, {}).get("state"),
            "last_success_at": runs.get(name, {}).get("last_success_at"),
        }
        for name in names
    ]

    webhooks = (
        db.query(ProcessedWebhookEvent).order_by(ProcessedWebhookEvent.created_at.desc()).limit(25).all()
    )
    failed = (
        db.query(Payment).filter(Payment.status == "failed").order_by(Payment.created_at.desc()).limit(25).all()
    )
    stuck = (
        db.query(Payment)
        .filter(Payment.status == "created", Payment.created_at < moment - STUCK_PAYMENT_AFTER)
        .order_by(Payment.created_at.desc())
        .limit(25)
        .all()
    )

    def payment_out(p: Payment) -> dict:
        return {
            "id": p.id,
            "org_id": p.org_id,
            "org_name": p.org_name_snapshot,
            "purpose": p.purpose,
            "amount_paise": p.amount_paise,
            "currency": p.currency,
            "razorpay_order_id": p.razorpay_order_id,
            "created_at": _iso(p.created_at),
        }

    llm = (
        db.query(Organization)
        .filter(Organization.deleted_at.is_(None), Organization.monthly_llm_calls > 0)
        .order_by(Organization.monthly_llm_calls.desc())
        .limit(25)
        .all()
    )
    return {
        "tasks": tasks,
        "task_runs_recorded": bool(runs),
        "reconciliation": read_reconciliation(),
        "recent_webhook_events": [
            {"provider": w.provider, "event_id": w.event_id, "created_at": _iso(w.created_at)} for w in webhooks
        ],
        "failed_payments": [payment_out(p) for p in failed],
        "stuck_payments": [payment_out(p) for p in stuck],
        "llm_usage": [
            {
                "org_id": o.id,
                "company_name": o.company_name,
                "tier": o.tier,
                "monthly_llm_calls": o.monthly_llm_calls,
                "monthly_llm_cap": LLM_CALL_CAPS.get(o.tier),
                "monthly_requests_processed": o.monthly_requests_processed,
            }
            for o in llm
        ],
    }
