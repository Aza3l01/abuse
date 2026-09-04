"""
api/routes/verdicts.py: verdict feed endpoints.

Routes
------
GET  /verdicts             : paginated list, filterable by severity / threat_type /
                            date range / IP, scoped to the current client
GET  /verdicts/threat-types : distinct threat_type values seen by this org (item 18's filter dropdown)
GET  /verdicts/{id}        : single verdict detail, enriched with ip_memory context (item 19)
POST /verdicts/manual-block : item 21, block an IP with no existing verdict
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case
from sqlalchemy.orm import Session

from api.deps import CurrentOrg, get_current_org, get_db, require_role
from db.models import IpMemory, Verdict

router = APIRouter()

_SEVERITY_ORDER = case(
    (Verdict.severity == "critical", 0),
    (Verdict.severity == "high", 1),
    (Verdict.severity == "medium", 2),
    (Verdict.severity == "low", 3),
    else_=4,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class VerdictOut(BaseModel):
    id:               str
    timestamp:        datetime
    ip:               str
    method:           Optional[str]
    endpoint:         Optional[str]
    threat_type:      Optional[str]
    severity:         str
    confidence:       float
    agents_triggered: Optional[list[Any]]
    explanation:      Optional[str]
    blocked:          bool
    cost_prevented:   Optional[float]
    created_at:       datetime

    class Config:
        from_attributes = True


class VerdictList(BaseModel):
    items: list[VerdictOut]
    total: int
    page:  int
    limit: int


class AgentScoreOut(BaseModel):
    agent_name: str
    score:      float
    triggered:  bool


class VerdictDetailOut(VerdictOut):
    """Item 19's full detail spec, adds ip_memory context, the raw log
    sample, and per-agent scores on top of the base VerdictOut fields."""
    sample_logs:      Optional[list[str]] = None
    agent_scores:     Optional[list[AgentScoreOut]] = None
    geo_country:      Optional[str] = None
    geo_asn_number:   Optional[int] = None
    geo_asn_org:      Optional[str] = None
    ip_first_seen:    Optional[datetime] = None
    ip_last_seen:     Optional[datetime] = None
    ip_total_requests: Optional[int] = None
    viewer_role:      str = "viewer"
    # AI Analysis (Pro-only) and the Block/Unblock button both gate on org
    # tier. Sourced here (not a separate /clients/me call, which 403s for
    # viewers) so a viewer at a Pro-tier org still sees the real AI analysis
    # per item 19's spec — only the Block button is role-gated, not tier info.
    org_tier:         str = "free"


class ManualBlockBody(BaseModel):
    ip:     str
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/verdicts", response_model=VerdictList)
def list_verdicts(
    page:        int = Query(1, ge=1),
    limit:       int = Query(25, ge=1, le=100),
    severity:    Optional[list[Literal["critical", "high", "medium", "low"]]] = Query(None),
    threat_type: Optional[str] = None,
    ip:          Optional[str] = None,
    date_from:   Optional[datetime] = None,
    date_to:     Optional[datetime] = None,
    db:          Session    = Depends(get_db),
    current_org: CurrentOrg = Depends(get_current_org),
):
    """
    Return a paginated, filtered list of verdicts for the current org.

    All filter parameters are optional and combinable. Results are ordered
    newest first (timestamp DESC). `severity` accepts repeated query params
    (item 18's multi-select checkboxes). Omit for "all severities".
    `ip` is a prefix match (e.g. "192.168." finds a subnet), not exact-only.
    """
    q = db.query(Verdict).filter(Verdict.org_id == current_org.id)

    if severity:
        q = q.filter(Verdict.severity.in_(severity))
    if threat_type:
        q = q.filter(Verdict.threat_type == threat_type)
    if ip:
        q = q.filter(Verdict.ip.startswith(ip))
    if date_from:
        q = q.filter(Verdict.timestamp >= date_from)
    if date_to:
        q = q.filter(Verdict.timestamp <= date_to)

    total = q.count()
    items = (
        q.order_by(_SEVERITY_ORDER.asc(), Verdict.timestamp.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return VerdictList(items=items, total=total, page=page, limit=limit)


@router.get("/verdicts/threat-types", response_model=list[str])
def list_threat_types(
    db:          Session    = Depends(get_db),
    current_org: CurrentOrg = Depends(get_current_org),
):
    """Item 18: distinct threat_type values for this org, for the filter dropdown."""
    rows = (
        db.query(Verdict.threat_type)
        .filter(Verdict.org_id == current_org.id, Verdict.threat_type.isnot(None))
        .distinct()
        .all()
    )
    return sorted(r[0] for r in rows if r[0])


@router.get("/verdicts/{verdict_id}", response_model=VerdictDetailOut)
def get_verdict(
    verdict_id:  str,
    db:          Session    = Depends(get_db),
    current_org: CurrentOrg = Depends(get_current_org),
):
    """Return a single verdict by ID, scoped to the current org, enriched
    with ip_memory context for item 19's detail page."""
    v = (
        db.query(Verdict)
        .filter(Verdict.id == verdict_id, Verdict.org_id == current_org.id)
        .first()
    )
    if v is None:
        raise HTTPException(status_code=404, detail="Verdict not found")

    ip_memory = (
        db.query(IpMemory)
        .filter(IpMemory.org_id == current_org.id, IpMemory.ip == v.ip)
        .first()
    )

    return VerdictDetailOut(
        **VerdictOut.model_validate(v).model_dump(),
        sample_logs=v.sample_logs,
        agent_scores=v.agent_scores,
        geo_country=ip_memory.geo_country if ip_memory else None,
        geo_asn_number=ip_memory.geo_asn_number if ip_memory else None,
        geo_asn_org=ip_memory.geo_asn_org if ip_memory else None,
        ip_first_seen=ip_memory.first_seen if ip_memory else None,
        ip_last_seen=ip_memory.last_seen if ip_memory else None,
        ip_total_requests=ip_memory.total_requests if ip_memory else None,
        viewer_role=current_org.role,
        org_tier=current_org.organization.tier,
    )


@router.post("/verdicts/manual-block", response_model=VerdictOut)
def manual_block_ip(
    body:        ManualBlockBody,
    db:          Session    = Depends(get_db),
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
):
    """Item 21: block an IP that has no existing verdict. Creates a
    threat_type='manual' verdict (confidence=1.0, severity='high') and
    triggers the normal block flow, so it appears in both the verdicts
    list (labeled "Manual block") and the blocked IPs tab.
    """
    if current_org.organization.tier not in ("growth", "pro"):
        raise HTTPException(status_code=403, detail="Blocking requires Growth or Pro plan.")
    if current_org.organization.blocking_tos_accepted_at is None:
        raise HTTPException(status_code=403, detail="Accept the Growth Subscription Agreement before blocking IPs.")

    v = Verdict(
        id=str(uuid.uuid4()),
        org_id=current_org.id,
        timestamp=datetime.now(timezone.utc),
        ip=body.ip,
        method=None,
        endpoint=None,
        threat_type="manual",
        severity="high",
        confidence=1.0,
        agents_triggered=[],
        explanation=body.reason or "Manually blocked by a team member.",
        blocked=False,
        cost_prevented=None,
    )
    db.add(v)

    ip_memory = (
        db.query(IpMemory)
        .filter(IpMemory.org_id == current_org.id, IpMemory.ip == body.ip)
        .first()
    )
    if ip_memory is None:
        now = datetime.now(timezone.utc)
        db.add(IpMemory(
            id=str(uuid.uuid4()),
            org_id=current_org.id,
            ip=body.ip,
            first_seen=now,
            last_seen=now,
            total_requests=0,
            threat_count=1,
            risk_score=1.0,
        ))
    db.commit()
    db.refresh(v)

    from workers.tasks.push_blocks import push_block
    push_block.delay(v.id, current_org.id)
    return v


@router.post("/verdicts/{verdict_id}/block", response_model=VerdictOut)
def manual_block(
    verdict_id:  str,
    db:          Session    = Depends(get_db),
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
):
    """Manually trigger a block for this verdict's IP."""
    v = (
        db.query(Verdict)
        .filter(Verdict.id == verdict_id, Verdict.org_id == current_org.id)
        .first()
    )
    if v is None:
        raise HTTPException(status_code=404, detail="Verdict not found")
    if current_org.organization.tier not in ("growth", "pro"):
        raise HTTPException(status_code=403, detail="Blocking requires Growth or Pro plan.")
    if current_org.organization.blocking_tos_accepted_at is None:
        raise HTTPException(status_code=403, detail="Accept the Growth Subscription Agreement before blocking IPs.")
    from workers.tasks.push_blocks import push_block
    push_block.delay(verdict_id, current_org.id)
    return v


@router.post("/verdicts/{verdict_id}/unblock", response_model=VerdictOut)
def manual_unblock(
    verdict_id:  str,
    db:          Session    = Depends(get_db),
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
):
    """Manually remove the block for this verdict's IP."""
    v = (
        db.query(Verdict)
        .filter(Verdict.id == verdict_id, Verdict.org_id == current_org.id)
        .first()
    )
    if v is None:
        raise HTTPException(status_code=404, detail="Verdict not found")
    if current_org.organization.tier not in ("growth", "pro"):
        raise HTTPException(status_code=403, detail="Blocking requires Growth or Pro plan.")
    from workers.tasks.push_blocks import push_unblock
    push_unblock.delay(verdict_id, current_org.id)
    return v
