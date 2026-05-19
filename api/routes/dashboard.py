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
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.deps import get_current_client, get_db
from db.models import Client, IpMemory, Verdict

router = APIRouter()


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
    ip:         str
    count:      int
    risk_score: float


class DashboardSummary(BaseModel):
    period_days:      int
    total_threats:    int
    new_threats_today: int
    by_severity:      dict[str, int]
    top_ips:          list[TopIp]
    cost_prevented:   float
    ips_flagged:      int
    trend:            list[TrendDay]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/dashboard/summary", response_model=DashboardSummary)
def get_summary(
    days:           int     = Query(7, ge=1, le=90),
    db:             Session = Depends(get_db),
    current_client: Client  = Depends(get_current_client),
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
            Verdict.client_id == current_client.id,
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
            Verdict.client_id == current_client.id,
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
            Verdict.client_id == current_client.id,
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
            Verdict.client_id == current_client.id,
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
            Verdict.client_id == current_client.id,
            Verdict.timestamp >= start_date,
        )
        .group_by(Verdict.ip)
        .order_by(func.count(Verdict.id).desc())
        .limit(5)
        .all()
    )

    ip_list = [r.ip for r in top_rows]
    risk_map: dict[str, float] = {}
    if ip_list:
        memories = (
            db.query(IpMemory)
            .filter(
                IpMemory.client_id == current_client.id,
                IpMemory.ip.in_(ip_list),
            )
            .all()
        )
        risk_map = {m.ip: m.risk_score for m in memories}

    top_ips = [
        TopIp(ip=r.ip, count=r.cnt, risk_score=risk_map.get(r.ip, 0.0))
        for r in top_rows
    ]

    return DashboardSummary(
        period_days=days,
        total_threats=total_threats,
        new_threats_today=new_today,
        by_severity=by_severity,
        top_ips=top_ips,
        cost_prevented=round(float(cost), 2),
        ips_flagged=ips_flagged,
        trend=list(day_map.values()),
    )
