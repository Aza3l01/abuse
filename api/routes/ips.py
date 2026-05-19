"""
api/routes/ips.py — IP memory / threat intelligence endpoints.

Route
-----
GET /ips    — paginated ip_memory table for the current client,
              sortable by risk_score / threat_count / last_seen,
              filterable by country code
"""
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_current_client, get_db
from db.models import Client, IpMemory

router = APIRouter()


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
    geo_country:    Optional[str]
    notes:          Optional[str]

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
    db:             Session = Depends(get_db),
    current_client: Client  = Depends(get_current_client),
):
    """
    Return the IP intelligence table for the current client.

    Each row represents the running profile of one source IP seen
    in processed logs. Sorted by risk_score (descending) by default.
    """
    q = db.query(IpMemory).filter(IpMemory.client_id == current_client.id)

    if country:
        q = q.filter(IpMemory.geo_country == country.upper()[:2])

    col = _SORT_COLS.get(sort, IpMemory.risk_score)
    q = q.order_by(col.asc() if order == "asc" else col.desc())

    total = q.count()
    items = q.offset((page - 1) * limit).limit(limit).all()

    return IpList(items=items, total=total, page=page, limit=limit)
