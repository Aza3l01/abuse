"""blocking/cloudflare.py — Block/unblock IPs via Cloudflare Access Rules API.

Uses the Cloudflare v4 REST API directly with httpx (already in requirements).
No Cloudflare SDK needed — the Access Rules endpoint is stable and simple.

Client setup:
  1. Dashboard → My Profile → API Tokens → Create Token
     Permissions: Zone / Firewall Services / Edit  (scoped to the target zone)
  2. Copy Zone ID from the zone's Overview page
  3. Store both in Clew settings (cloudflare_zone_id, cloudflare_token)
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_CF_API = "https://api.cloudflare.com/client/v4"
_TIMEOUT = 10.0  # seconds


def block_ip(ip: str, zone_id: str, token: str) -> bool:
    """
    Create a Cloudflare Zone Firewall Access Rule that blocks the given IP.
    Idempotent — silently succeeds if a block for this IP already exists.
    Returns True on success, False on any error.
    """
    url = f"{_CF_API}/zones/{zone_id}/firewall/access_rules/rules"
    payload = {
        "mode": "block",
        "configuration": {"target": "ip", "value": ip},
        "notes": "Blocked by Clew — automated threat detection",
    }
    try:
        r = httpx.post(
            url,
            json=payload,
            headers=_headers(token),
            timeout=_TIMEOUT,
        )
        data = r.json()
        if r.status_code == 409 or (not data.get("success") and _is_duplicate(data)):
            logger.debug("cloudflare: %s already blocked on zone %s", ip, zone_id)
            return True
        if not data.get("success"):
            logger.error("cloudflare: block %s failed: %s", ip, data.get("errors"))
            return False
        logger.info("cloudflare: blocked %s on zone %s", ip, zone_id)
        return True
    except httpx.RequestError as exc:
        logger.error("cloudflare: network error blocking %s: %s", ip, exc)
        return False


def unblock_ip(ip: str, zone_id: str, token: str) -> bool:
    """
    Remove the Cloudflare Access Rule blocking the given IP.
    Finds the rule by IP first, then deletes it.
    Returns True on success (or if no rule exists), False on any error.
    """
    rule_id = _find_rule_id(ip, zone_id, token)
    if rule_id is None:
        logger.debug("cloudflare: no block rule found for %s on zone %s", ip, zone_id)
        return True

    url = f"{_CF_API}/zones/{zone_id}/firewall/access_rules/rules/{rule_id}"
    try:
        r = httpx.delete(url, headers=_headers(token), timeout=_TIMEOUT)
        data = r.json()
        if not data.get("success"):
            logger.error("cloudflare: unblock %s failed: %s", ip, data.get("errors"))
            return False
        logger.info("cloudflare: unblocked %s on zone %s", ip, zone_id)
        return True
    except httpx.RequestError as exc:
        logger.error("cloudflare: network error unblocking %s: %s", ip, exc)
        return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _find_rule_id(ip: str, zone_id: str, token: str) -> str | None:
    """Return the rule ID for an existing block rule on this IP, or None."""
    url = f"{_CF_API}/zones/{zone_id}/firewall/access_rules/rules"
    try:
        r = httpx.get(
            url,
            params={"mode": "block", "configuration.target": "ip", "configuration.value": ip},
            headers=_headers(token),
            timeout=_TIMEOUT,
        )
        data = r.json()
        if data.get("success") and data.get("result"):
            return data["result"][0]["id"]
    except httpx.RequestError as exc:
        logger.error("cloudflare: error searching rules for %s: %s", ip, exc)
    return None


def _is_duplicate(response: dict) -> bool:
    """Return True if the Cloudflare error indicates the rule already exists."""
    for err in response.get("errors", []):
        if err.get("code") in (10009, 10004):  # already exists codes
            return True
        if "already exists" in str(err.get("message", "")).lower():
            return True
    return False
