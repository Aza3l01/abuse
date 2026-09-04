"""
api/routes/clients.py — Organisation self-service config endpoints.

Routes
------
GET  /clients/me   — return the current org's config
PATCH /clients/me  — update S3, alert, and blocking config

Note: kept at the historical `/clients/me` path (not renamed to `/org/me`)
so the frontend Settings page didn't need a second unrelated change during
Phase 2's rekey. Backed by `Organization` now, not `Client` — S3/blocking/
alert config is org-scoped, not per-login (Phase 2, item 7).
"""
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from api.deps import CurrentOrg, get_current_org, get_db, require_role
from db.models import Organization

router = APIRouter()


# ---------------------------------------------------------------------------
# Item 16: S3 connection test, fired by every PATCH that touches S3 config.
#
# The bucket owner's IAM policy is checked against Clew's single shared IAM
# user (env AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY on the worker/API host,
# see IamPolicyGuide in the frontend Settings page). There is no per-org
# access key/secret in this schema; that would be item 42's cross-account
# IAM role work, explicitly POST-MVP.
# ---------------------------------------------------------------------------

def _test_s3_connection(bucket: str, prefix: str, region: str) -> tuple[str, Optional[str]]:
    """Return (status, message). status is 'connected' or 'error'."""
    try:
        s3 = boto3.client("s3", region_name=region)
        s3.list_objects_v2(Bucket=bucket, Prefix=prefix or "", MaxKeys=1)
        return "connected", None
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("InvalidAccessKeyId",):
            return "error", "Invalid Access Key ID, verify AWS_ACCESS_KEY_ID in your IAM console"
        if code in ("SignatureDoesNotMatch",):
            return "error", "Invalid secret access key, verify the key pair matches in your IAM console"
        if code in ("NoSuchBucket", "PermanentRedirect"):
            return "error", f"Bucket '{bucket}' not found in region '{region}', check the bucket name and AWS region"
        if code in ("AccessDenied",):
            return "error", (
                f"Access denied to s3://{bucket}. Missing permission: `s3:GetObject`. "
                'Add this to your IAM policy: {"Effect": "Allow", "Action": '
                f'["s3:GetObject", "s3:ListBucket"], "Resource": ["arn:aws:s3:::{bucket}", '
                f'"arn:aws:s3:::{bucket}/*"]}}'
            )
        return "error", f"AWS error: {code or str(exc)}"
    except Exception as exc:
        return "error", f"Connection test failed: {exc}"


# ---------------------------------------------------------------------------
# Response schema — what the client can read back
# ---------------------------------------------------------------------------

class OrgConfig(BaseModel):
    id:                  str
    company_name:        str
    tier:                str
    role:                str
    # S3 ingestion
    s3_bucket:           Optional[str]
    s3_prefix:           Optional[str]
    log_format:          Optional[str]
    aws_region:          Optional[str]
    last_processed_key:  Optional[str]
    calibration_status:  Optional[str]
    s3_status:           Optional[str]
    s3_status_message:   Optional[str]
    s3_connected_at:     Optional[datetime]
    # Item 17: worker health / last-scanned indicator
    last_scan_completed_at: Optional[datetime]
    last_scan_status:       Optional[str]
    last_scan_error:        Optional[str]
    # Alerts
    alert_email:              Optional[str]
    alert_severity_threshold: str
    # Blocking (IDs only — never return cloudflare_token)
    waf_ip_set_id:       Optional[str]
    cloudflare_zone_id:  Optional[str]
    blocking_tos_accepted_at: Optional[datetime]

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
    alert_email:              Optional[str] = None
    alert_severity_threshold: Optional[str] = None
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

    @field_validator("alert_severity_threshold")
    @classmethod
    def validate_alert_severity_threshold(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("all", "high_critical_only"):
            raise ValueError("alert_severity_threshold must be 'all' or 'high_critical_only'")
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
# Shared response builder
# ---------------------------------------------------------------------------

def _to_org_config(org: Organization, role: str) -> OrgConfig:
    return OrgConfig(
        id=org.id,
        company_name=org.company_name,
        tier=org.tier,
        role=role,
        s3_bucket=org.s3_bucket,
        s3_prefix=org.s3_prefix,
        log_format=org.log_format,
        aws_region=org.aws_region,
        last_processed_key=org.last_processed_key,
        calibration_status=org.calibration_status,
        s3_status=org.s3_status,
        s3_status_message=org.s3_status_message,
        s3_connected_at=org.s3_connected_at,
        last_scan_completed_at=org.last_scan_completed_at,
        last_scan_status=org.last_scan_status,
        last_scan_error=org.last_scan_error,
        alert_email=org.alert_email,
        alert_severity_threshold=org.alert_severity_threshold,
        waf_ip_set_id=org.waf_ip_set_id,
        cloudflare_zone_id=org.cloudflare_zone_id,
        blocking_tos_accepted_at=org.blocking_tos_accepted_at,
    )


# ---------------------------------------------------------------------------
# GET /clients/me
#
# Settings is hidden from viewers in the frontend; enforced here too so the
# API itself never returns org config (including the blocking token-bearing
# fields' presence/absence) to a read-only role.
# ---------------------------------------------------------------------------

@router.get("/clients/me", response_model=OrgConfig)
async def get_me(
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
):
    return _to_org_config(current_org.organization, current_org.role)


# ---------------------------------------------------------------------------
# PATCH /clients/me
# ---------------------------------------------------------------------------

@router.patch("/clients/me", response_model=OrgConfig)
async def update_me(
    body: ClientUpdate,
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    update_data = body.model_dump(exclude_none=True)

    if not update_data:
        raise HTTPException(status_code=422, detail="No fields to update.")

    _ALLOWED_FIELDS = {
        "s3_bucket", "s3_prefix", "log_format", "aws_region",
        "alert_email", "alert_severity_threshold",
        "waf_ip_set_id", "cloudflare_zone_id", "cloudflare_token",
    }
    old_s3_bucket, old_s3_prefix, old_log_format = (
        org.s3_bucket, org.s3_prefix, org.log_format,
    )
    for field, value in update_data.items():
        if field in _ALLOWED_FIELDS:
            setattr(org, field, value)

    # Changing ingestion config resets progress so we don't skip new logs
    s3_fields_touched = any(f in update_data for f in ("s3_bucket", "s3_prefix", "log_format", "aws_region"))
    if any(f in update_data for f in ("s3_bucket", "s3_prefix", "log_format")):
        org.last_processed_key = None
        # Item 5: clear any stale format-mismatch error from a prior connection
        org.s3_status = None
        org.s3_status_message = None

    # Item 16: the save itself triggers the connection test, confirmation
    # only appears after the test passes.
    if s3_fields_touched and org.s3_bucket:
        status, message = _test_s3_connection(org.s3_bucket, org.s3_prefix or "", org.aws_region or "us-east-1")
        org.s3_status = status
        org.s3_status_message = message
        if status == "connected" and org.s3_connected_at is None:
            org.s3_connected_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(org)

    # Item 45 Gap A: (re)connecting a *changed* S3 config kicks off a silent
    # calibration pass over the last 24h of logs, seeding LTM thresholds
    # before live detection starts. Only fires on an actual value change
    # (not a resubmit of the same values, which would otherwise fan out a
    # new overlapping calibration task on every unrelated save) and only
    # once the org has a usable config, s3_prefix is legitimately optional
    # (bucket-root orgs), so it is not required to be truthy.
    s3_config_changed = (
        org.s3_bucket != old_s3_bucket
        or org.s3_prefix != old_s3_prefix
        or org.log_format != old_log_format
    )
    if s3_config_changed and org.s3_bucket and org.log_format and org.s3_status == "connected":
        from workers.tasks.process_logs import calibrate_client
        org.calibration_status = "running"
        db.commit()
        calibrate_client.delay(org.id)

    # Item 22: a successful S3 save immediately queues the first real scan,
    # separate from the silent calibration pass above (that only warms LTM
    # thresholds, it never writes verdicts).
    if s3_fields_touched and org.s3_status == "connected" and org.log_format:
        from workers.tasks.process_logs import process_logs
        process_logs.delay(org.id)

    return _to_org_config(org, current_org.role)


# ---------------------------------------------------------------------------
# POST /clients/me/accept-blocking-tos
#
# Item 28: one-time acceptance of the Growth Subscription Agreement, shown
# in a modal right before the upgrade-to-Growth payment flow opens. Backend
# block actions (verdicts.py) 403 until this is set. Owner-only, same as
# the billing upgrade action that triggers this modal.
# ---------------------------------------------------------------------------

@router.post("/clients/me/accept-blocking-tos", response_model=OrgConfig)
async def accept_blocking_tos(
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    if org.blocking_tos_accepted_at is None:
        org.blocking_tos_accepted_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(org)
    return _to_org_config(org, current_org.role)

