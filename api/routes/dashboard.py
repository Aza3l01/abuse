"""
api/routes/dashboard.py — Aggregated dashboard summary endpoint.

Route
-----
GET /dashboard/summary?days=7   — stat cards, trend data, top IPs

The response is designed so the frontend can render the full overview page
with a single API call. Period defaults to 7 days; pass ?days=30 for a
wider view.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from api.deps import CurrentOrg, get_current_org, get_db
from db.models import IpMemory, Verdict

router = APIRouter()

_SEVERITY_RANK = case(
    (Verdict.severity == "critical", 0),
    (Verdict.severity == "high", 1),
    (Verdict.severity == "medium", 2),
    (Verdict.severity == "low", 3),
    else_=4,
)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class TrendDay(BaseModel):
    date:     str
    critical: int = 0
    high:     int = 0
    medium:   int = 0
    low:      int = 0


class TopIp(BaseModel):
    ip:              str
    count:           int
    risk_score:      float
    highest_severity: Optional[str] = None
    geo_country:      Optional[str] = None
    geo_asn_org:      Optional[str] = None
    blocked:          bool = False


class DashboardSummary(BaseModel):
    period_days:      int
    total_threats:    int
    new_threats_today: int
    by_severity:      dict[str, int]
    top_ips:          list[TopIp]
    cost_prevented:   float
    ips_flagged:      int
    trend:            list[TrendDay]
    # Item 15/16/17: empty/scanning states + connection health + last-scanned
    s3_configured:          bool
    s3_connected_at:        Optional[datetime]
    s3_status:              Optional[str]
    s3_status_message:      Optional[str]
    calibration_status:     Optional[str]
    last_scan_completed_at: Optional[datetime]
    last_scan_status:       Optional[str]
    last_scan_error:        Optional[str]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/dashboard/summary", response_model=DashboardSummary)
def get_summary(
    days:        int        = Query(7, ge=1, le=90),
    db:          Session    = Depends(get_db),
    current_org: CurrentOrg = Depends(get_current_org),
):
    """
    Return aggregated stats for the current client over the last `days` days.

    trend — one entry per calendar day in the period, ordered oldest first.
            Days with zero threats are included so the chart always has
            exactly `days` bars.
    """
    now        = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    # ------------------------------------------------------------------
    # Severity trend — group by (day, severity) for the full period
    # ------------------------------------------------------------------
    trend_rows = (
        db.query(
            func.date_trunc("day", Verdict.timestamp).label("day"),
            Verdict.severity,
            func.count(Verdict.id).label("cnt"),
        )
        .filter(
            Verdict.org_id == current_org.id,
            Verdict.timestamp >= start_date,
        )
        .group_by(
            func.date_trunc("day", Verdict.timestamp),
            Verdict.severity,
        )
        .order_by(func.date_trunc("day", Verdict.timestamp))
        .all()
    )

    # Build a full day-keyed dict so every day in the period is present
    day_map: dict[str, TrendDay] = {}
    for i in range(days):
        d = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        day_map[d] = TrendDay(date=d)

    by_severity: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    for row in trend_rows:
        # date_trunc returns a datetime; take first 10 chars for YYYY-MM-DD
        key = str(row.day)[:10]
        if key in day_map:
            sev = row.severity
            if sev in ("critical", "high", "medium", "low"):
                setattr(day_map[key], sev, getattr(day_map[key], sev) + row.cnt)
                by_severity[sev] = by_severity.get(sev, 0) + row.cnt

    total_threats = sum(by_severity.values())

    # ------------------------------------------------------------------
    # New threats today
    # ------------------------------------------------------------------
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    new_today = (
        db.query(func.count(Verdict.id))
        .filter(
            Verdict.org_id == current_org.id,
            Verdict.timestamp >= today_start,
        )
        .scalar()
    ) or 0

    # ------------------------------------------------------------------
    # Cost prevented (sum for period)
    # ------------------------------------------------------------------
    cost = (
        db.query(func.sum(Verdict.cost_prevented))
        .filter(
            Verdict.org_id == current_org.id,
            Verdict.timestamp >= start_date,
        )
        .scalar()
    ) or 0.0

    # ------------------------------------------------------------------
    # IPs flagged (distinct IPs with at least one verdict in period)
    # ------------------------------------------------------------------
    ips_flagged = (
        db.query(func.count(func.distinct(Verdict.ip)))
        .filter(
            Verdict.org_id == current_org.id,
            Verdict.timestamp >= start_date,
        )
        .scalar()
    ) or 0

    # ------------------------------------------------------------------
    # Top 5 IPs by threat count in period
    # ------------------------------------------------------------------
    top_rows = (
        db.query(Verdict.ip, func.count(Verdict.id).label("cnt"))
        .filter(
            Verdict.org_id == current_org.id,
            Verdict.timestamp >= start_date,
        )
        .group_by(Verdict.ip)
        .order_by(func.count(Verdict.id).desc())
        .limit(5)
        .all()
    )

    ip_list = [r.ip for r in top_rows]
    memories: dict[str, IpMemory] = {}
    if ip_list:
        rows = (
            db.query(IpMemory)
            .filter(
                IpMemory.org_id == current_org.id,
                IpMemory.ip.in_(ip_list),
            )
            .all()
        )
        memories = {m.ip: m for m in rows}

    # Item 18: highest severity per top IP within the period
    best_severity: dict[str, str] = {}
    if ip_list:
        best_rank: dict[str, int] = {}
        sev_rows = (
            db.query(Verdict.ip, Verdict.severity, _SEVERITY_RANK.label("rank"))
            .filter(
                Verdict.org_id == current_org.id,
                Verdict.timestamp >= start_date,
                Verdict.ip.in_(ip_list),
            )
            .all()
        )
        for ip, sev, rank in sev_rows:
            if ip not in best_rank or rank < best_rank[ip]:
                best_rank[ip] = rank
                best_severity[ip] = sev

    top_ips = [
        TopIp(
            ip=r.ip,
            count=r.cnt,
            risk_score=memories[r.ip].risk_score if r.ip in memories else 0.0,
            highest_severity=best_severity.get(r.ip),
            geo_country=memories[r.ip].geo_country if r.ip in memories else None,
            geo_asn_org=memories[r.ip].geo_asn_org if r.ip in memories else None,
            blocked=bool(memories[r.ip].waf_blocked or memories[r.ip].cloudflare_blocked) if r.ip in memories else False,
        )
        for r in top_rows
    ]

    org = current_org.organization
    return DashboardSummary(
        period_days=days,
        total_threats=total_threats,
        new_threats_today=new_today,
        by_severity=by_severity,
        top_ips=top_ips,
        cost_prevented=round(float(cost), 2),
        ips_flagged=ips_flagged,
        trend=list(day_map.values()),
        s3_configured=bool(org.s3_bucket and org.log_format),
        s3_connected_at=org.s3_connected_at,
        s3_status=org.s3_status,
        s3_status_message=org.s3_status_message,
        calibration_status=org.calibration_status,
        last_scan_completed_at=org.last_scan_completed_at,
        last_scan_status=org.last_scan_status,
        last_scan_error=org.last_scan_error,
    )
