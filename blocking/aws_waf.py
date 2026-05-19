"""blocking/aws_waf.py — Add/remove IPs from an AWS WAF v2 IP set.

The client stores their WAF IP set ID in clients.waf_ip_set_id.
Clew only needs s3:GetObject/ListBucket for ingestion PLUS the WAF permissions
below for blocking — both come from the same IAM user.

Required IAM actions on the IP set resource:
  wafv2:GetIPSet
  wafv2:UpdateIPSet

The IP set scope must be REGIONAL (API Gateway / ALB are regional resources).
"""
from __future__ import annotations

import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_SCOPE = "REGIONAL"


def _client(region: str):
    return boto3.client("wafv2", region_name=region)


def add_ip_to_set(
    ip: str,
    waf_ip_set_id: str,
    waf_ip_set_name: str,
    region: str,
) -> bool:
    """
    Add a single IP (CIDR notation) to the WAF IP set.

    WAF requires CIDR — bare IPs are auto-suffixed with /32 (IPv4) or /128 (IPv6).
    Returns True on success, False on any error.
    """
    cidr = _to_cidr(ip)
    try:
        waf = _client(region)
        # Must read the current set first to get the lock token
        current = waf.get_ip_set(Name=waf_ip_set_name, Scope=_SCOPE, Id=waf_ip_set_id)
        addresses: list[str] = current["IPSet"]["Addresses"]

        if cidr in addresses:
            logger.debug("aws_waf: %s already in IP set %s", cidr, waf_ip_set_id)
            return True

        addresses.append(cidr)
        waf.update_ip_set(
            Name=waf_ip_set_name,
            Scope=_SCOPE,
            Id=waf_ip_set_id,
            Addresses=addresses,
            LockToken=current["LockToken"],
        )
        logger.info("aws_waf: added %s to IP set %s", cidr, waf_ip_set_id)
        return True

    except ClientError as exc:
        logger.error("aws_waf: failed to add %s to IP set %s: %s", cidr, waf_ip_set_id, exc)
        return False


def remove_ip_from_set(
    ip: str,
    waf_ip_set_id: str,
    waf_ip_set_name: str,
    region: str,
) -> bool:
    """Remove a single IP from the WAF IP set. Returns True on success."""
    cidr = _to_cidr(ip)
    try:
        waf = _client(region)
        current = waf.get_ip_set(Name=waf_ip_set_name, Scope=_SCOPE, Id=waf_ip_set_id)
        addresses: list[str] = current["IPSet"]["Addresses"]

        if cidr not in addresses:
            logger.debug("aws_waf: %s not in IP set %s — nothing to remove", cidr, waf_ip_set_id)
            return True

        addresses.remove(cidr)
        waf.update_ip_set(
            Name=waf_ip_set_name,
            Scope=_SCOPE,
            Id=waf_ip_set_id,
            Addresses=addresses,
            LockToken=current["LockToken"],
        )
        logger.info("aws_waf: removed %s from IP set %s", cidr, waf_ip_set_id)
        return True

    except ClientError as exc:
        logger.error("aws_waf: failed to remove %s from IP set %s: %s", cidr, waf_ip_set_id, exc)
        return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_cidr(ip: str) -> str:
    """Append /32 or /128 if the caller passed a bare IP address."""
    if "/" in ip:
        return ip
    return f"{ip}/128" if ":" in ip else f"{ip}/32"
