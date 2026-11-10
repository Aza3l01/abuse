"""api/routes/internal.py: the Phase 6 internal ops panel API (staff only).

Mounted at /internal. Reachable in production only through the internal host
(nginx 404s /internal on every other host). Every route except login depends
on require_staff, which reads only the staff cookie.

No `from __future__ import annotations` here on purpose: see the FastAPI body
parameter note in CONTEXT.md (it breaks body detection behind decorators).
"""
import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api import staff_ops, staff_views
from api.auth_utils import decrypt_secret
from api.deps import get_db
from api.metrics import (
    CSV_HEADER, HEADLINE_CURRENCY, combine, combine_by_date, compute_snapshot, csv_row, derive,
    parse_rate, rate_text, reporting_rate, row_to_dict, with_rate,
)
from api.staff_auth import (
    STAFF_COOKIE,
    audit,
    clear_staff_cookie,
    create_staff_token,
    client_ip,
    decode_staff_token,
    ip_within_limit,
    is_locked_out,
    password_matches,
    record_failure,
    require_staff,
    reset_failures,
    set_staff_cookie,
    verify_totp,
)
from db.models import MetricsDaily, Organization, StaffAuditLog, StaffUser

router = APIRouter(prefix="/internal")

_NO_STORE = {"Cache-Control": "no-store"}


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class LoginBody(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=256)
    code: str = Field(max_length=12)


class RawBody(BaseModel):
    kind: str = Field(max_length=20)
    reason: str = Field(max_length=500)
    limit: int = Field(default=50, ge=1, le=100)


class MarkPaidBody(BaseModel):
    bill_id: str = Field(max_length=64)
    reference: str = Field(min_length=1, max_length=200)
    reason: str = Field(max_length=500)


class VoidBody(BaseModel):
    bill_id: str = Field(max_length=64)
    reason: str = Field(max_length=500)


class ExtendPeriodBody(BaseModel):
    months: int
    reason: str = Field(max_length=500)


class PauseBody(BaseModel):
    days: int = 14
    reason: str = Field(max_length=500)


class ReinstateBody(BaseModel):
    tier: str = Field(max_length=20)
    period: str = Field(max_length=10)
    reference: str = Field(min_length=1, max_length=200)
    reason: str = Field(max_length=500)


class ExtendPilotBody(BaseModel):
    days: int
    reason: str = Field(max_length=500)


class PilotCodesBody(BaseModel):
    count: int
    reason: str = Field(max_length=500)


class CreditActionBody(BaseModel):
    reason: str = Field(max_length=500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_org(db: Session, org_id: str, lock: bool = False) -> Organization:
    canonical = staff_views.parse_org_id(org_id)
    if canonical is None:
        raise HTTPException(404, "Organisation not found.")
    query = db.query(Organization).filter(Organization.id == canonical)
    if lock:
        query = query.with_for_update()
    org = query.first()
    if org is None:
        raise HTTPException(404, "Organisation not found.")
    return org


def _writable_org(db: Session, org_id: str) -> Organization:
    org = _get_org(db, org_id, lock=True)
    if org.deleted_at is not None:
        raise HTTPException(409, "This account is deleted.")
    return org


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@router.post("/auth/login")
def login(request: Request, response: Response, body: LoginBody, db: Session = Depends(get_db)):
    ip = client_ip(request) or "unknown"
    if not ip_within_limit(ip):
        raise HTTPException(429, "Too many attempts. Try again later.")
    email = body.email.strip().lower()
    if is_locked_out(email):
        raise HTTPException(429, "Too many attempts. Try again later.")

    staff = db.query(StaffUser).filter(StaffUser.email == email).first()
    password_ok = password_matches(staff, body.password)
    step = None
    if password_ok and staff is not None and staff.is_active and staff.totp_active:
        step = verify_totp(decrypt_secret(staff.totp_secret), body.code, staff.last_totp_step)

    if step is None:
        record_failure(email)
        if staff is not None:
            audit(db, staff, "staff_login_failed", request=request)
            db.commit()
        raise HTTPException(401, "Invalid credentials.")

    reset_failures(email)
    staff.last_totp_step = step
    staff.last_login_at = datetime.now(timezone.utc)
    audit(db, staff, "staff_login", request=request)
    db.commit()
    set_staff_cookie(response, create_staff_token(staff.id))
    response.headers["Cache-Control"] = "no-store"
    return {"email": staff.email}


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(STAFF_COOKIE)
    payload = decode_staff_token(token) if token else None
    staff = db.get(StaffUser, payload["sub"]) if payload and payload.get("sub") else None
    if staff is not None:
        audit(db, staff, "staff_logout", request=request)
        db.commit()
    clear_staff_cookie(response)
    return {"ok": True}


@router.get("/auth/me")
def me(response: Response, staff: StaffUser = Depends(require_staff)):
    response.headers["Cache-Control"] = "no-store"
    return {"email": staff.email}


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

@router.get("/orgs/search")
def orgs_search(
    response: Response,
    q: str = Query(min_length=2, max_length=100),
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    return {"results": staff_views.search_orgs(db, q)}


@router.get("/orgs/{org_id}")
def org_detail(
    org_id: str,
    response: Response,
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    org = _get_org(db, org_id)
    return staff_views.account_view(db, org)


@router.post("/orgs/{org_id}/raw")
def org_raw(
    org_id: str,
    request: Request,
    response: Response,
    body: RawBody,
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Raw verdict rows or IP memory of one org. A reason is required, and the
    view is written to the audit log before any data is returned."""
    response.headers["Cache-Control"] = "no-store"
    reason = staff_ops.clean_reason(body.reason)
    if body.kind not in ("verdicts", "ips"):
        raise HTTPException(400, "Kind must be verdicts or ips.")
    org = _get_org(db, org_id)
    audit(
        db, staff, "raw_view", org=org, reason=reason,
        details={"kind": body.kind, "limit": body.limit}, request=request,
    )
    db.commit()
    rows = (
        staff_views.raw_verdicts(db, org, body.limit)
        if body.kind == "verdicts"
        else staff_views.raw_ips(db, org, body.limit)
    )
    return {"kind": body.kind, "rows": rows}


# ---------------------------------------------------------------------------
# Billing actions
# ---------------------------------------------------------------------------

@router.post("/orgs/{org_id}/bills/mark-paid")
def bill_mark_paid(
    org_id: str,
    request: Request,
    body: MarkPaidBody,
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    reason = staff_ops.clean_reason(body.reason)
    org = _writable_org(db, org_id)
    payment = staff_ops.mark_bill_paid(db, org, body.bill_id, body.reference.strip())
    audit(
        db, staff, "bill_mark_paid", org=org, reason=reason, request=request,
        details={
            "bill_id": body.bill_id, "payment_id": payment.id, "reference": body.reference.strip(),
            "amount_minor": payment.amount_paise, "currency": payment.currency,
        },
    )
    db.commit()
    return {"ok": True, "payment_id": payment.id}


@router.post("/orgs/{org_id}/bills/void")
def bill_void(
    org_id: str,
    request: Request,
    body: VoidBody,
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    reason = staff_ops.clean_reason(body.reason)
    org = _writable_org(db, org_id)
    bill = staff_ops.void_bill(db, org, body.bill_id)
    audit(
        db, staff, "bill_void", org=org, reason=reason, request=request,
        details={"bill_id": bill.id, "amount_minor": bill.amount_paise, "currency": bill.currency},
    )
    db.commit()
    return {"ok": True}


@router.post("/orgs/{org_id}/extend-period")
def extend_period(
    org_id: str,
    request: Request,
    body: ExtendPeriodBody,
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    reason = staff_ops.clean_reason(body.reason)
    org = _writable_org(db, org_id)
    result = staff_ops.extend_period(db, org, body.months)
    audit(db, staff, "period_extend", org=org, reason=reason, request=request,
          details={"months": body.months, **result})
    db.commit()
    return {"ok": True, **result}


@router.post("/orgs/{org_id}/pause-downgrade")
def pause_downgrade(
    org_id: str,
    request: Request,
    body: PauseBody,
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    reason = staff_ops.clean_reason(body.reason)
    org = _writable_org(db, org_id)
    result = staff_ops.pause_downgrade(db, org, body.days)
    audit(db, staff, "downgrade_pause", org=org, reason=reason, request=request,
          details={"days": body.days, **result})
    db.commit()
    return {"ok": True, **result}


@router.post("/orgs/{org_id}/reinstate")
def reinstate(
    org_id: str,
    request: Request,
    body: ReinstateBody,
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    reason = staff_ops.clean_reason(body.reason)
    org = _writable_org(db, org_id)
    payment = staff_ops.reinstate_org(db, org, body.tier, body.period, body.reference.strip())
    audit(
        db, staff, "org_reinstate", org=org, reason=reason, request=request,
        details={
            "tier": body.tier, "period": body.period, "payment_id": payment.id,
            "reference": body.reference.strip(), "amount_minor": payment.amount_paise,
            "currency": payment.currency,
        },
    )
    db.commit()
    return {"ok": True, "payment_id": payment.id}


# ---------------------------------------------------------------------------
# Pilot actions
# ---------------------------------------------------------------------------

@router.post("/orgs/{org_id}/extend-pilot")
def extend_pilot(
    org_id: str,
    request: Request,
    body: ExtendPilotBody,
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    reason = staff_ops.clean_reason(body.reason)
    org = _writable_org(db, org_id)
    result = staff_ops.extend_pilot(db, org, body.days)
    audit(db, staff, "pilot_extend", org=org, reason=reason, request=request,
          details={"days": body.days, **result})
    db.commit()
    return {"ok": True, **result}


@router.post("/pilot-codes")
def pilot_codes(
    request: Request,
    body: PilotCodesBody,
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    reason = staff_ops.clean_reason(body.reason)
    codes = staff_ops.generate_pilot_codes(db, body.count)
    audit(db, staff, "pilot_codes_generate", reason=reason, request=request,
          details={"count": len(codes)})
    db.commit()
    return {"codes": codes}


# ---------------------------------------------------------------------------
# Referrals (Phase 12): the graph and velocity view, revoke and approve
# ---------------------------------------------------------------------------

@router.get("/referrals")
def referrals_overview(
    response: Response,
    limit: int = Query(default=100, ge=1, le=500),
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    return staff_views.referral_overview(db, limit)


@router.post("/referrals/credits/{credit_id}/revoke")
def referral_credit_revoke(
    credit_id: str,
    request: Request,
    body: CreditActionBody,
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    reason = staff_ops.clean_reason(body.reason)
    credit = staff_ops.revoke_referral_credit(db, credit_id, reason)
    audit(
        db, staff, "referral_credit_revoke", org=db.get(Organization, credit.org_id), reason=reason,
        request=request,
        details={"credit_id": credit.id, "amount_minor": credit.amount_paise, "currency": credit.currency},
    )
    db.commit()
    return {"ok": True}


@router.post("/referrals/credits/{credit_id}/approve")
def referral_credit_approve(
    credit_id: str,
    request: Request,
    body: CreditActionBody,
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    reason = staff_ops.clean_reason(body.reason)
    credit = staff_ops.approve_referral_credit(db, credit_id)
    audit(
        db, staff, "referral_credit_approve", org=db.get(Organization, credit.org_id), reason=reason,
        request=request,
        details={"credit_id": credit.id, "amount_minor": credit.amount_paise, "currency": credit.currency},
    )
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# System health
# ---------------------------------------------------------------------------

@router.get("/health")
def health(
    response: Response,
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    return staff_views.system_health(db)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _metrics_out(data: dict) -> dict:
    out = {**data, "snapshot_date": data["snapshot_date"].isoformat(), "inr_per_usd": rate_text(data.get("inr_per_usd"))}
    out.update(derive(data))
    return out


def _combined_out(day, combined: dict | None) -> dict:
    """A combined row for the response. With no rate on that date, only the date
    and an empty rate (the page shows a dash for every figure)."""
    if combined is None:
        return {"snapshot_date": day.isoformat(), "currency": HEADLINE_CURRENCY, "inr_per_usd": None}
    return _metrics_out(combined)


def _entered_rate(raw: str | None):
    """The rate staff typed on the page, or None when none was sent."""
    if raw is None or not raw.strip():
        return None
    rate = parse_rate(raw)
    if rate is None:
        raise HTTPException(status_code=422, detail="Rate must be a positive number of INR per 1 USD.")
    return rate


@router.get("/metrics")
def metrics(
    response: Response,
    history_days: int = Query(default=60, ge=1, le=366),
    rate: str | None = Query(default=None, max_length=20),
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    live = compute_snapshot(db)
    stored = (
        db.query(MetricsDaily)
        .order_by(MetricsDaily.snapshot_date.desc(), MetricsDaily.currency)
        .limit(history_days * 2)
        .all()
    )
    history = [row_to_dict(row) for row in stored]
    entered = _entered_rate(rate)
    if entered is not None:
        live = with_rate(live, entered)
        history = with_rate(history, entered)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "headline_currency": HEADLINE_CURRENCY,
        "rate": rate_text(entered if entered is not None else reporting_rate()),
        "rate_source": "entered" if entered is not None else ("server" if reporting_rate() is not None else None),
        "current": [_metrics_out(row) for row in live],
        "history": [_metrics_out(row) for row in history],
        "combined_current": _combined_out(live[0]["snapshot_date"], combine(live)) if live else None,
        "combined_history": [_combined_out(day, c) for day, c in combine_by_date(history).items()],
    }


@router.get("/metrics/export.csv")
def metrics_export(
    request: Request,
    rate: str | None = Query(default=None, max_length=20),
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    entered = _entered_rate(rate)
    live = compute_snapshot(db)
    merged = {
        (row.snapshot_date, row.currency): row_to_dict(row)
        for row in db.query(MetricsDaily).all()
    }
    for row in live:
        merged[(row["snapshot_date"], row["currency"])] = row
    if entered is not None:
        merged = {key: {**row, "inr_per_usd": entered} for key, row in merged.items()}
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    combined = combine_by_date(list(merged.values()))
    for key in sorted(merged):
        writer.writerow(csv_row(merged[key], combined[key[0]]))
    audit(db, staff, "metrics_export", details={"rows": len(merged)}, request=request)
    db.commit()
    return Response(
        content=buffer.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="clew-metrics.csv"', **_NO_STORE},
    )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@router.get("/audit")
def audit_log(
    response: Response,
    limit: int = Query(default=100, ge=1, le=500),
    staff: StaffUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    rows = db.query(StaffAuditLog).order_by(StaffAuditLog.created_at.desc()).limit(limit).all()
    return {"rows": [staff_views.audit_row(r) for r in rows]}
