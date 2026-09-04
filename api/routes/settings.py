"""
api/routes/settings.py: item 23, WAF / Cloudflare credential validation.

Routes
------
POST /settings/test-waf         : wafv2:GetIPSet against the stored ARN/ID
POST /settings/test-cloudflare  : GET /zones/{zone_id} against the stored token

Same test-and-show-result pattern as `clients.py`'s S3 save-and-test (item 16).
Both blocking integrations are Growth+ only (enforced here too, not just in
the frontend section visibility).
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import CurrentOrg, require_role

router = APIRouter(prefix="/settings", tags=["settings"])

_BLOCKING_TIERS = {"growth", "pro"}


class TestResultOut(BaseModel):
    status: str            # 'connected' | 'error'
    message: str


def _require_blocking_tier(current_org: CurrentOrg) -> None:
    if current_org.organization.tier not in _BLOCKING_TIERS:
        raise HTTPException(status_code=403, detail="Blocking requires Growth or Pro plan.")


# ---------------------------------------------------------------------------
# POST /settings/test-waf
# ---------------------------------------------------------------------------

@router.post("/test-waf", response_model=TestResultOut)
def test_waf(current_org: CurrentOrg = Depends(require_role("owner", "admin"))):
    _require_blocking_tier(current_org)
    org = current_org.organization
    if not org.waf_ip_set_id:
        raise HTTPException(status_code=422, detail="No WAF IP set ARN configured yet.")

    import boto3
    from botocore.exceptions import ClientError

    name, _, set_id = org.waf_ip_set_id.partition("::")
    if not set_id:
        set_id = name
        name = "clew-blocked-ips"

    try:
        waf = boto3.client("wafv2", region_name=org.aws_region or "us-east-1")
        result = waf.get_ip_set(Name=name, Scope="REGIONAL", Id=set_id)
        count = len(result["IPSet"]["Addresses"])
        return TestResultOut(status="connected", message=f"Connected, IP set contains {count} IPs")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "WAFNonexistentItemException":
            return TestResultOut(status="error", message="Invalid ARN, IP set not found")
        if code == "WAFInvalidParameterException":
            return TestResultOut(status="error", message="Invalid ARN, check the IP set ID and scope")
        if code == "AccessDeniedException":
            return TestResultOut(status="error", message="Permission denied, missing wafv2:GetIPSet on this resource")
        return TestResultOut(status="error", message=f"AWS error: {code or str(exc)}")
    except Exception as exc:
        return TestResultOut(status="error", message=f"Connection test failed: {exc}")


# ---------------------------------------------------------------------------
# POST /settings/test-cloudflare
# ---------------------------------------------------------------------------

@router.post("/test-cloudflare", response_model=TestResultOut)
def test_cloudflare(current_org: CurrentOrg = Depends(require_role("owner", "admin"))):
    _require_blocking_tier(current_org)
    org = current_org.organization
    if not org.cloudflare_zone_id or not org.cloudflare_token:
        raise HTTPException(status_code=422, detail="Cloudflare zone ID and token must both be set.")

    url = f"https://api.cloudflare.com/client/v4/zones/{org.cloudflare_zone_id}"
    try:
        r = httpx.get(
            url,
            headers={"Authorization": f"Bearer {org.cloudflare_token}"},
            timeout=10.0,
        )
        data = r.json()
        if data.get("success"):
            zone_name = (data.get("result") or {}).get("name", "unknown")
            return TestResultOut(status="connected", message=f"Connected, Zone: {zone_name}")
        errors = data.get("errors") or []
        code = errors[0].get("code") if errors else None
        if code == 6003:
            return TestResultOut(status="error", message="Invalid API token")
        if code == 1003 or r.status_code == 404:
            return TestResultOut(status="error", message="Zone not found, check the zone ID")
        if code == 9109:
            return TestResultOut(status="error", message="Insufficient token permissions, needs Zone / Firewall Services / Edit")
        message = errors[0].get("message") if errors else "Unknown Cloudflare error"
        return TestResultOut(status="error", message=f"Cloudflare error: {message}")
    except httpx.RequestError as exc:
        return TestResultOut(status="error", message=f"Network error: {exc}")
