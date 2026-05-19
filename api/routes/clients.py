"""
api/routes/clients.py — Client self-service config endpoints.

Routes
------
GET  /clients/me   — return the current client's config
PATCH /clients/me  — update S3, alert, and blocking config
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from api.deps import get_current_client, get_db
from db.models import Client

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schema — what the client can read back
# ---------------------------------------------------------------------------

class ClientConfig(BaseModel):
    id:                  str
    email:               str
    company_name:        str
    tier:                str
    email_verified:      bool
    mfa_enabled:         bool
    # S3 ingestion
    s3_bucket:           Optional[str]
    s3_prefix:           Optional[str]
    log_format:          Optional[str]
    aws_region:          Optional[str]
    last_processed_key:  Optional[str]
    # Alerts
    alert_email:         Optional[str]
    # Blocking (IDs only — never return cloudflare_token)
    waf_ip_set_id:       Optional[str]
    cloudflare_zone_id:  Optional[str]

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Update schema — what the client can write
# ---------------------------------------------------------------------------

_ALLOWED_LOG_FORMATS = {"apigw", "alb"}
_ALLOWED_REGIONS = {
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "eu-west-1", "eu-west-2", "eu-central-1",
    "ap-south-1", "ap-southeast-1", "ap-southeast-2", "ap-northeast-1",
}


class ClientUpdate(BaseModel):
    # S3 ingestion
    s3_bucket:         Optional[str] = None
    s3_prefix:         Optional[str] = None
    log_format:        Optional[str] = None
    aws_region:        Optional[str] = None
    # Alerts
    alert_email:       Optional[str] = None
    # Blocking — Cloudflare token is write-only (not returned in GET)
    waf_ip_set_id:     Optional[str] = None
    cloudflare_zone_id:Optional[str] = None
    cloudflare_token:  Optional[str] = None

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _ALLOWED_LOG_FORMATS:
            raise ValueError(f"log_format must be one of: {', '.join(sorted(_ALLOWED_LOG_FORMATS))}")
        return v

    @field_validator("aws_region")
    @classmethod
    def validate_aws_region(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _ALLOWED_REGIONS:
            raise ValueError(f"aws_region not recognised: {v}")
        return v

    @field_validator("s3_bucket")
    @classmethod
    def validate_s3_bucket(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) < 3 or len(v) > 63:
                raise ValueError("s3_bucket must be 3–63 characters")
            # Basic S3 bucket name rules — lowercase alphanumeric and hyphens only
            import re
            if not re.match(r'^[a-z0-9][a-z0-9\-]*[a-z0-9]$', v):
                raise ValueError(
                    "s3_bucket must start and end with a lowercase letter or digit "
                    "and contain only lowercase letters, digits, and hyphens"
                )
        return v


# ---------------------------------------------------------------------------
# GET /clients/me
# ---------------------------------------------------------------------------

@router.get("/clients/me", response_model=ClientConfig)
async def get_me(
    client: Client = Depends(get_current_client),
):
    return client


# ---------------------------------------------------------------------------
# PATCH /clients/me
# ---------------------------------------------------------------------------

@router.patch("/clients/me", response_model=ClientConfig)
async def update_me(
    body: ClientUpdate,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    update_data = body.model_dump(exclude_none=True)

    if not update_data:
        raise HTTPException(status_code=422, detail="No fields to update.")

    _ALLOWED_FIELDS = {
        "s3_bucket", "s3_prefix", "log_format", "aws_region",
        "alert_email", "waf_ip_set_id", "cloudflare_zone_id", "cloudflare_token",
    }
    for field, value in update_data.items():
        if field in _ALLOWED_FIELDS:
            setattr(client, field, value)

    # Changing ingestion config resets progress so we don't skip new logs
    if any(f in update_data for f in ("s3_bucket", "s3_prefix", "log_format")):
        client.last_processed_key = None

    db.commit()
    db.refresh(client)
    return client
