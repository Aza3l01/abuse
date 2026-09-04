"""workers/tasks/push_blocks.py — Push a block rule for a verdict's IP.

Called after process_logs for high/critical verdicts when the client is on
Growth or Pro tier and has at least one blocking integration configured.

Design decisions:
  - Fire-and-forget Celery task (not chained): a blocking failure must never
    cause the pipeline to retry or lose the verdict record.
  - Idempotent: both blocking modules handle "already blocked" gracefully.
  - Sets verdict.blocked = True only on confirmed success from at least one
    integration; never on partial failure.
  - Both WAF and Cloudflare are attempted if both are configured; either
    succeeding is sufficient to mark the verdict blocked.

Tier gate:
  Only Growth and Pro clients trigger this task. Free/Starter clients have
  detection + dashboard, but auto-blocking requires an upgrade.

Confidence threshold:
  Only verdicts with confidence >= BLOCK_CONFIDENCE_THRESHOLD (default 0.75)
  are automatically blocked. Below that the verdict is shown in the dashboard
  but no WAF rule is pushed.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from workers.celery_app import celery_app

_REPO_ROOT = Path(__file__).parent.parent.parent
for _p in [str(_REPO_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from db.models import IpMemory, Organization, Verdict
from db.session import SessionLocal

logger = logging.getLogger(__name__)

BLOCK_CONFIDENCE_THRESHOLD = 0.75
_BLOCKING_TIERS = {"growth", "pro"}


@celery_app.task(
    name="workers.tasks.push_blocks.push_block",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def push_block(self, verdict_id: str, org_id: str) -> dict:
    """
    Attempt to push a block rule for the IP in verdict_id.
    Updates verdict.blocked = True if at least one integration succeeds.
    """
    db = SessionLocal()
    try:
        verdict: Verdict | None = (
            db.query(Verdict)
            .filter(Verdict.id == verdict_id, Verdict.org_id == org_id)
            .first()
        )
        if verdict is None:
            logger.warning("push_block: verdict %s not found", verdict_id)
            return {"status": "skipped", "reason": "verdict_not_found"}

        if verdict.blocked:
            logger.debug("push_block: verdict %s already blocked", verdict_id)
            return {"status": "already_blocked"}

        org: Organization | None = db.query(Organization).filter(Organization.id == org_id).first()
        if org is None:
            return {"status": "skipped", "reason": "org_not_found"}

        # --- Tier gate ---
        if org.tier not in _BLOCKING_TIERS:
            logger.debug(
                "push_block: org %s on tier %s — blocking not available",
                org_id, org.tier,
            )
            return {"status": "skipped", "reason": "tier_not_eligible"}

        # --- Confidence gate ---
        if verdict.confidence < BLOCK_CONFIDENCE_THRESHOLD:
            logger.debug(
                "push_block: verdict %s confidence %.2f below threshold %.2f",
                verdict_id, verdict.confidence, BLOCK_CONFIDENCE_THRESHOLD,
            )
            return {"status": "skipped", "reason": "confidence_too_low"}

        ip = verdict.ip
        if not ip:
            return {"status": "skipped", "reason": "no_ip"}

        ip_memory: IpMemory | None = (
            db.query(IpMemory)
            .filter(IpMemory.org_id == org_id, IpMemory.ip == ip)
            .first()
        )

        blocked_by: list[str] = []

        # --- AWS WAF ---
        if org.waf_ip_set_id:
            from blocking.aws_waf import add_ip_to_set
            # WAF IP set name is stored as "name::id" or just the ID if legacy
            name, _, set_id = org.waf_ip_set_id.partition("::")
            if not set_id:
                # legacy: stored as bare ID, use a default name
                set_id = name
                name = "clew-blocked-ips"
            ok, error = add_ip_to_set(
                ip=ip,
                waf_ip_set_id=set_id,
                waf_ip_set_name=name,
                region=org.aws_region or "us-east-1",
            )
            if ok:
                blocked_by.append("waf")
            if ip_memory is not None:
                ip_memory.waf_blocked = ok
                ip_memory.waf_block_error = None if ok else error

        # --- Cloudflare ---
        if org.cloudflare_zone_id and org.cloudflare_token:
            from blocking.cloudflare import block_ip
            ok, error = block_ip(
                ip=ip,
                zone_id=org.cloudflare_zone_id,
                token=org.cloudflare_token,
            )
            if ok:
                blocked_by.append("cloudflare")
            if ip_memory is not None:
                ip_memory.cloudflare_blocked = ok
                ip_memory.cloudflare_block_error = None if ok else error

        if not blocked_by:
            db.commit()  # persist per-integration error fields even on total failure
            logger.warning(
                "push_block: no integrations configured or all failed for org %s", org_id
            )
            return {"status": "failed", "reason": "no_integration_succeeded"}

        # --- Mark verdict as blocked ---
        db.query(Verdict).filter(Verdict.id == verdict_id).update({"blocked": True})
        db.commit()

        logger.info(
            "push_block: blocked %s for verdict=%s via %s",
            ip, verdict_id, ",".join(blocked_by),
        )
        return {"status": "blocked", "ip": ip, "via": blocked_by}

    except Exception as exc:
        db.rollback()
        logger.exception("push_block: error for verdict %s: %s", verdict_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(
    name="workers.tasks.push_blocks.push_unblock",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def push_unblock(self, verdict_id: str, org_id: str) -> dict:
    """Remove a block rule for the IP in verdict_id."""
    db = SessionLocal()
    try:
        verdict: Verdict | None = (
            db.query(Verdict)
            .filter(Verdict.id == verdict_id, Verdict.org_id == org_id)
            .first()
        )
        if verdict is None:
            return {"status": "skipped", "reason": "verdict_not_found"}

        org: Organization | None = db.query(Organization).filter(Organization.id == org_id).first()
        if org is None:
            return {"status": "skipped", "reason": "org_not_found"}

        ip = verdict.ip
        if not ip:
            return {"status": "skipped", "reason": "no_ip"}

        ip_memory: IpMemory | None = (
            db.query(IpMemory)
            .filter(IpMemory.org_id == org_id, IpMemory.ip == ip)
            .first()
        )

        unblocked_by: list[str] = []

        if org.waf_ip_set_id:
            from blocking.aws_waf import remove_ip_from_set
            name, _, set_id = org.waf_ip_set_id.partition("::")
            if not set_id:
                set_id = name
                name = "clew-blocked-ips"
            ok, error = remove_ip_from_set(
                ip=ip,
                waf_ip_set_id=set_id,
                waf_ip_set_name=name,
                region=org.aws_region or "us-east-1",
            )
            if ok:
                unblocked_by.append("waf")
            if ip_memory is not None:
                ip_memory.waf_blocked = not ok
                ip_memory.waf_block_error = None if ok else error

        if org.cloudflare_zone_id and org.cloudflare_token:
            from blocking.cloudflare import unblock_ip
            ok, error = unblock_ip(
                ip=ip,
                zone_id=org.cloudflare_zone_id,
                token=org.cloudflare_token,
            )
            if ok:
                unblocked_by.append("cloudflare")
            if ip_memory is not None:
                ip_memory.cloudflare_blocked = not ok
                ip_memory.cloudflare_block_error = None if ok else error

        db.query(Verdict).filter(Verdict.id == verdict_id).update({"blocked": False})
        db.commit()

        logger.info(
            "push_unblock: unblocked %s for verdict=%s via %s",
            ip, verdict_id, ",".join(unblocked_by) or "none",
        )
        return {"status": "unblocked", "ip": ip, "via": unblocked_by}

    except Exception as exc:
        db.rollback()
        logger.exception("push_unblock: error for verdict %s: %s", verdict_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()
