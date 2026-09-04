"""
api/routes/ips.py: IP memory / threat intelligence endpoints.

Route
-----
GET /ips    : paginated ip_memory table for the current client,
              sortable by risk_score / threat_count / last_seen,
              filterable by country code, optionally blocked-only (item 21)
"""
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from api.deps import CurrentOrg, get_current_org, get_db, require_role
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
# Schemas
# ---------------------------------------------------------------------------

class IpOut(BaseModel):
    id:             str
    ip:             str
    first_seen:     datetime
    last_seen:      datetime
    total_requests: int
    threat_count:   int
    risk_score:     float
    highest_severity: Optional[str] = None
    geo_country:    Optional[str]
    geo_asn_number: Optional[int]
    geo_asn_org:    Optional[str]
    notes:          Optional[str]
    waf_blocked:            bool
    cloudflare_blocked:     bool
    waf_block_error:        Optional[str]
    cloudflare_block_error: Optional[str]

    class Config:
        from_attributes = True


class IpList(BaseModel):
    items: list[IpOut]
    total: int
    page:  int
    limit: int


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

_SORT_COLS = {
    "risk_score":    IpMemory.risk_score,
    "threat_count":  IpMemory.threat_count,
    "last_seen":     IpMemory.last_seen,
    "total_requests": IpMemory.total_requests,
}


@router.get("/ips", response_model=IpList)
def list_ips(
    page:    int     = Query(1, ge=1),
    limit:   int     = Query(25, ge=1, le=100),
    sort:    Literal["risk_score", "threat_count", "last_seen", "total_requests"] = "risk_score",
    order:   Literal["asc", "desc"] = "desc",
    country: Optional[str] = None,
    blocked_only: bool = Query(False, description="Item 21's Blocked tab: WAF- or Cloudflare-blocked IPs only"),
    db:          Session    = Depends(get_db),
    current_org: CurrentOrg = Depends(get_current_org),
):
    """
    Return the IP intelligence table for the current org.

    Each row represents the running profile of one source IP seen
    in processed logs. Sorted by risk_score (descending) by default.
    """
    q = db.query(IpMemory).filter(IpMemory.org_id == current_org.id)

    if country:
        q = q.filter(IpMemory.geo_country == country.upper()[:2])
    if blocked_only:
        q = q.filter(or_(IpMemory.waf_blocked.is_(True), IpMemory.cloudflare_blocked.is_(True)))

    col = _SORT_COLS.get(sort, IpMemory.risk_score)
    q = q.order_by(col.asc() if order == "asc" else col.desc())

    total = q.count()
    items = q.offset((page - 1) * limit).limit(limit).all()

    # Item 18: highest severity per IP on this page only (small set)
    ip_list = [row.ip for row in items]
    best_severity: dict[str, str] = {}
    if ip_list:
        best_rank: dict[str, int] = {}
        sev_rows = (
            db.query(Verdict.ip, Verdict.severity, _SEVERITY_RANK.label("rank"))
            .filter(Verdict.org_id == current_org.id, Verdict.ip.in_(ip_list))
            .all()
        )
        for ip_val, sev, rank in sev_rows:
            if ip_val not in best_rank or rank < best_rank[ip_val]:
                best_rank[ip_val] = rank
                best_severity[ip_val] = sev

    out_items = [
        IpOut(
            **IpOut.model_validate(row).model_dump(exclude={"highest_severity"}),
            highest_severity=best_severity.get(row.ip),
        )
        for row in items
    ]

    return IpList(items=out_items, total=total, page=page, limit=limit)


# ---------------------------------------------------------------------------
# POST /ips/{ip}/unblock: item 21's Blocked IPs tab unblock action.
#
# Blocking always happens through a verdict (a real detection or item 21's
# manual-block endpoint), so re-using push_block/push_unblock's existing
# per-verdict plumbing just needs the most recent verdict for this IP,
# there's no separate "unblock this IP" primitive in the blocking modules.
# ---------------------------------------------------------------------------

@router.post("/ips/{ip}/unblock", response_model=IpOut)
def unblock_ip(
    ip:          str,
    db:          Session    = Depends(get_db),
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
):
    ip_memory = (
        db.query(IpMemory)
        .filter(IpMemory.org_id == current_org.id, IpMemory.ip == ip)
        .first()
    )
    if ip_memory is None:
        raise HTTPException(status_code=404, detail="IP not found.")

    latest_verdict = (
        db.query(Verdict)
        .filter(Verdict.org_id == current_org.id, Verdict.ip == ip, Verdict.blocked.is_(True))
        .order_by(Verdict.timestamp.desc())
        .first()
    )
    if latest_verdict is None:
        raise HTTPException(status_code=422, detail="This IP has no active block to remove.")

    from workers.tasks.push_blocks import push_unblock
    push_unblock.delay(latest_verdict.id, current_org.id)
    return ip_memory
