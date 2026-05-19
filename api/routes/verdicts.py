"""
api/routes/verdicts.py — Verdict feed endpoints.

Routes
------
GET /verdicts          — paginated list, filterable by severity / threat_type /
                         date range / IP, scoped to the current client
GET /verdicts/{id}     — single verdict detail
"""
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_current_client, get_db
from db.models import Client, Verdict

router = APIRouter()


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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/verdicts", response_model=VerdictList)
def list_verdicts(
    page:        int = Query(1, ge=1),
    limit:       int = Query(25, ge=1, le=100),
    severity:    Optional[Literal["critical", "high", "medium", "low"]] = None,
    threat_type: Optional[str] = None,
    ip:          Optional[str] = None,
    date_from:   Optional[datetime] = None,
    date_to:     Optional[datetime] = None,
    db:             Session = Depends(get_db),
    current_client: Client  = Depends(get_current_client),
):
    """
    Return a paginated, filtered list of verdicts for the current client.

    All filter parameters are optional and combinable. Results are ordered
    newest first (timestamp DESC).
    """
    q = db.query(Verdict).filter(Verdict.client_id == current_client.id)

    if severity:
        q = q.filter(Verdict.severity == severity)
    if threat_type:
        q = q.filter(Verdict.threat_type == threat_type)
    if ip:
        q = q.filter(Verdict.ip == ip)
    if date_from:
        q = q.filter(Verdict.timestamp >= date_from)
    if date_to:
        q = q.filter(Verdict.timestamp <= date_to)

    total = q.count()
    items = (
        q.order_by(Verdict.timestamp.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return VerdictList(items=items, total=total, page=page, limit=limit)


@router.get("/verdicts/{verdict_id}", response_model=VerdictOut)
def get_verdict(
    verdict_id:     str,
    db:             Session = Depends(get_db),
    current_client: Client  = Depends(get_current_client),
):
    """Return a single verdict by ID, scoped to the current client."""
    v = (
        db.query(Verdict)
        .filter(Verdict.id == verdict_id, Verdict.client_id == current_client.id)
        .first()
    )
    if v is None:
        raise HTTPException(status_code=404, detail="Verdict not found")
    return v


@router.post("/verdicts/{verdict_id}/block", response_model=VerdictOut)
def manual_block(
    verdict_id:     str,
    db:             Session = Depends(get_db),
    current_client: Client  = Depends(get_current_client),
):
    """Manually trigger a block for this verdict's IP."""
    v = (
        db.query(Verdict)
        .filter(Verdict.id == verdict_id, Verdict.client_id == current_client.id)
        .first()
    )
    if v is None:
        raise HTTPException(status_code=404, detail="Verdict not found")
    if current_client.tier not in ("growth", "pro"):
        raise HTTPException(status_code=403, detail="Blocking requires Growth or Pro plan.")
    from workers.tasks.push_blocks import push_block
    push_block.delay(verdict_id, current_client.id)
    return v


@router.post("/verdicts/{verdict_id}/unblock", response_model=VerdictOut)
def manual_unblock(
    verdict_id:     str,
    db:             Session = Depends(get_db),
    current_client: Client  = Depends(get_current_client),
):
    """Manually remove the block for this verdict's IP."""
    v = (
        db.query(Verdict)
        .filter(Verdict.id == verdict_id, Verdict.client_id == current_client.id)
        .first()
    )
    if v is None:
        raise HTTPException(status_code=404, detail="Verdict not found")
    if current_client.tier not in ("growth", "pro"):
        raise HTTPException(status_code=403, detail="Blocking requires Growth or Pro plan.")
    from workers.tasks.push_blocks import push_unblock
    push_unblock.delay(verdict_id, current_client.id)
    return v
