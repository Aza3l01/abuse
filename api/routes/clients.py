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

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from api.deps import CurrentOrg, get_current_org, get_db, require_role
from api.auth_utils import encrypt_secret
from api.aws import CLEW_AWS_ACCOUNT_ID, AWSAccessError, aws_session_for_org
from api.detection_config import validate_detection_config
from api.tiers import AUTO_BLOCK_TIERS, CUSTOM_THRESHOLD_TIERS, MANUAL_BLOCK_TIERS
from db.models import Organization

router = APIRouter()


# ---------------------------------------------------------------------------
# Item 16: S3 connection test, fired by every PATCH that touches S3 config.
#
# Phase 2: reads via aws_session_for_org, so an org with aws_role_arn set is
# tested against its own cross-account role (with the External ID), and an
# org without one falls back to Clew's shared IAM user (env
# AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY), the pre-phase-2 behavior.
# ---------------------------------------------------------------------------

def _test_s3_connection(org: Organization, bucket: str, prefix: str, region: str) -> tuple[str, Optional[str]]:
    """Return (status, message). status is 'connected' or 'error'."""
    try:
        s3 = aws_session_for_org(org).client("s3", region_name=region)
        s3.list_objects_v2(Bucket=bucket, Prefix=prefix or "", MaxKeys=1)
        return "connected", None
    except AWSAccessError as exc:
        return "error", str(exc)
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
    # TODO.md priority item 2: explicit opt-in for the unattended
    # pipeline-triggered block, visible only for Growth and above on the
    # Settings page, off by default.
    auto_block_enabled:  bool
    # Phase 8: dry-run for automatic blocking (log what would have been
    # blocked, touch nothing) and the Pro tuning config (null = engine defaults).
    auto_block_dry_run:  bool
    detection_config:    Optional[dict]
    # Item 61: tenant's expected home country, used by GeoIPAgent
    home_country:        Optional[str]
    # Phase 2: cross-account IAM role. aws_external_id is server-generated,
    # read-only (never in ClientUpdate/_ALLOWED_FIELDS). clew_aws_account_id
    # isn't stored on the org at all, it's the same value for every org, read
    # from env so the settings page can build the trust policy without a
    # separate endpoint.
    aws_role_arn:        Optional[str]
    aws_external_id:     Optional[str]
    clew_aws_account_id: str
    # Phase 4 (section 4c): guided onboarding state.
    onboarding_completed_at: Optional[datetime]
    onboarding_dismissed_at: Optional[datetime]

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Update schema — what the client can write
# ---------------------------------------------------------------------------

_ALLOWED_LOG_FORMATS = {"apigw", "alb"}
# Every standard public AWS region where a customer can realistically hold an
# S3 bucket. Excludes GovCloud and China (isolated partitions, not reachable
# from the shared/cross-account IAM role this product uses). Mirrors
# frontend/src/lib/awsRegions.ts, keep both in sync.
_ALLOWED_REGIONS = {
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "af-south-1",
    "ap-east-1",
    "ap-south-1", "ap-south-2",
    "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
    "ap-southeast-1", "ap-southeast-2", "ap-southeast-3", "ap-southeast-4",
    "ca-central-1", "ca-west-1",
    "eu-central-1", "eu-central-2",
    "eu-west-1", "eu-west-2", "eu-west-3",
    "eu-north-1", "eu-south-1", "eu-south-2",
    "me-south-1", "me-central-1",
    "sa-east-1",
    "il-central-1",
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
    # TODO.md priority item 2: validated server-side in update_me (requires
    # blocking_tos_accepted_at already set before it can be switched on),
    # not just by the Settings page's own modal-gated toggle.
    auto_block_enabled: Optional[bool] = None
    # Phase 8: Growth and above (same tiers as auto-block). Only takes effect
    # while auto_block_enabled is on.
    auto_block_dry_run: Optional[bool] = None
    # Phase 8: Pro and Enterprise. {} resets to engine defaults. Shape and
    # ranges are validated by api/detection_config.py.
    detection_config: Optional[dict] = None
    # Item 61: tenant's expected home country, ISO 3166-1 alpha-2
    home_country:      Optional[str] = None
    # Phase 2: cross-account IAM role ARN, pasted back after the customer
    # creates the role from the Settings page's generated trust/permissions
    # policies. aws_external_id is deliberately NOT writable here, it is
    # server-generated at org creation and never customer-chosen.
    aws_role_arn:      Optional[str] = None

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

    @field_validator("detection_config")
    @classmethod
    def validate_detection_config_field(cls, v: Optional[dict]) -> Optional[dict]:
        if v is None:
            return None
        return validate_detection_config(v) or {}

    @field_validator("home_country")
    @classmethod
    def validate_home_country(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip().upper()
        if len(v) != 2 or not v.isalpha():
            raise ValueError("home_country must be a 2-letter ISO 3166-1 alpha-2 code")
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

    @field_validator("aws_role_arn")
    @classmethod
    def validate_aws_role_arn(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip()
        import re
        if not re.match(r'^arn:aws:iam::\d{12}:role/[\w+=,.@-]+$', v):
            raise ValueError(
                "aws_role_arn must look like arn:aws:iam::<12-digit-account-id>:role/<role-name>"
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
        auto_block_enabled=org.auto_block_enabled,
        auto_block_dry_run=bool(org.auto_block_dry_run),
        detection_config=org.detection_config or None,
        home_country=org.home_country,
        aws_role_arn=org.aws_role_arn,
        aws_external_id=org.aws_external_id,
        clew_aws_account_id=CLEW_AWS_ACCOUNT_ID,
        onboarding_completed_at=org.onboarding_completed_at,
        onboarding_dismissed_at=org.onboarding_dismissed_at,
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
        "auto_block_dry_run", "detection_config",
        "waf_ip_set_id", "cloudflare_zone_id", "cloudflare_token",
        "home_country", "aws_role_arn", "auto_block_enabled",
    }
    old_s3_bucket, old_s3_prefix, old_log_format = (
        org.s3_bucket, org.s3_prefix, org.log_format,
    )

    # TODO.md priority item 2: auto_block_enabled can only be switched on
    # once the Blocking Subscription Agreement is accepted. The Settings
    # page already gates this with a modal, this is the actual enforcement
    # boundary so a direct API call can't bypass it.
    if update_data.get("auto_block_enabled") and org.blocking_tos_accepted_at is None:
        raise HTTPException(
            status_code=400,
            detail="Accept the Blocking Subscription Agreement before enabling automatic blocking.",
        )
    # Phase 8 tier gates. Turning dry-run off is always allowed (so a
    # downgraded org is never stuck in it), turning it on needs the
    # automatic-blocking tiers. Detection tuning is Pro and Enterprise only.
    if update_data.get("auto_block_dry_run") and org.tier not in AUTO_BLOCK_TIERS:
        raise HTTPException(status_code=403, detail="Dry-run mode is available on Growth and above.")
    if "detection_config" in update_data and org.tier not in CUSTOM_THRESHOLD_TIERS:
        raise HTTPException(status_code=403, detail="Custom detection thresholds are available on Pro and above.")
    for field, value in update_data.items():
        if field not in _ALLOWED_FIELDS:
            continue
        # Item 57: encrypt at rest, same primitive as TOTP secrets.
        if field == "cloudflare_token":
            value = encrypt_secret(value)
        if field == "detection_config":
            value = value or None  # {} resets to engine defaults
        setattr(org, field, value)

    # Changing ingestion config resets progress so we don't skip new logs
    s3_fields_touched = any(f in update_data for f in ("s3_bucket", "s3_prefix", "log_format", "aws_region"))
    if any(f in update_data for f in ("s3_bucket", "s3_prefix", "log_format")):
        org.last_processed_key = None
        # Item 5: clear any stale format-mismatch error from a prior connection
        org.s3_status = None
        org.s3_status_message = None

    # Item 16: the save itself triggers the connection test, confirmation
    # only appears after the test passes. Phase 2: also re-test on an
    # aws_role_arn-only save, so pasting back a role ARN gets immediate
    # feedback instead of waiting for the next 15-minute poll.
    if (s3_fields_touched or "aws_role_arn" in update_data) and org.s3_bucket:
        status, message = _test_s3_connection(org, org.s3_bucket, org.s3_prefix or "", org.aws_region or "us-east-1")
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
# Item 28/69: one-time acceptance of the Blocking Subscription Agreement.
# Backend block actions (verdicts.py) 403 until this is set. Owner-only.
#
# Phase 4: a purchase records the acceptance itself, at payment capture (the
# accept_blocking_tos flag on billing/razorpay/create-order). This endpoint
# remains only for orgs that already have blocking without a checkout, which
# today means Growth pilots, so it returns 403 unless the org's current tier
# is one that can manually block. A free org can never record it.
# ---------------------------------------------------------------------------

@router.post("/clients/me/accept-blocking-tos", response_model=OrgConfig)
async def accept_blocking_tos(
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    if org.tier not in MANUAL_BLOCK_TIERS:
        raise HTTPException(
            status_code=403,
            detail="The Blocking Subscription Agreement can only be accepted on a plan that includes blocking.",
        )
    if org.blocking_tos_accepted_at is None:
        org.blocking_tos_accepted_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(org)
    return _to_org_config(org, current_org.role)


# ---------------------------------------------------------------------------
# Guided onboarding (Phase 4, section 4c)
#
# Dismissed stops the wizard from auto-opening again; completed stops
# showing the prompt entirely. Both owner/admin only, a viewer never gets
# the wizard, so it can't dismiss or complete it either.
# ---------------------------------------------------------------------------

@router.post("/clients/me/onboarding/dismiss", response_model=OrgConfig)
async def dismiss_onboarding(
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    if org.onboarding_dismissed_at is None:
        org.onboarding_dismissed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(org)
    return _to_org_config(org, current_org.role)


@router.post("/clients/me/onboarding/complete", response_model=OrgConfig)
async def complete_onboarding(
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    if org.onboarding_completed_at is None:
        org.onboarding_completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(org)
    return _to_org_config(org, current_org.role)

