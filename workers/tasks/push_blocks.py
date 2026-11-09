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
from api.auth_utils import decrypt_secret
from api.aws import aws_session_for_org
from blocking.aws_waf import add_ip_to_set, remove_ip_from_set
from blocking.cloudflare import block_ip, unblock_ip

logger = logging.getLogger(__name__)

BLOCK_CONFIDENCE_THRESHOLD = 0.75


@celery_app.task(
    name="workers.tasks.push_blocks.push_block",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def push_block(self, verdict_id: str, org_id: str, confidence_threshold: float | None = None) -> dict:
    """
    Attempt to push a block rule for the IP in verdict_id.
    Updates verdict.blocked = True if at least one integration succeeds.

    confidence_threshold: Phase 8. The automatic path passes the org's own
    block confidence; manual blocks omit it and keep BLOCK_CONFIDENCE_THRESHOLD.
    """
    threshold = BLOCK_CONFIDENCE_THRESHOLD if confidence_threshold is None else confidence_threshold
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

        # No tier gate here: both callers already check the tier set that
        # applies to them before enqueueing this task (process_logs.py checks
        # AUTO_BLOCK_TIERS for the automatic pipeline path, verdicts.py checks
        # the wider MANUAL_BLOCK_TIERS for the two manual-block endpoints). A
        # gate here checking only AUTO_BLOCK_TIERS used to silently no-op
        # every Basic/Starter manual block, since AUTO_BLOCK_TIERS excludes
        # "starter" but MANUAL_BLOCK_TIERS includes it.

        # --- Blocking Subscription Agreement gate ---
        # verdicts.py's manual-block routes and checkout both already check
        # this, but process_logs.py's automatic trigger did not, so an org
        # with a WAF/Cloudflare integration configured could get unattended
        # blocking with no agreement ever accepted. Defense in depth here too
        # in case a caller is ever added that forgets the check: a Celery
        # task has no HTTP response to 403 against, so this skips instead of
        # raising.
        if org.blocking_tos_accepted_at is None:
            return {"status": "skipped", "reason": "tos_not_accepted"}

        # --- Confidence gate ---
        if verdict.confidence < threshold:
            logger.debug(
                "push_block: verdict %s confidence %.2f below threshold %.2f",
                verdict_id, verdict.confidence, threshold,
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
                session=aws_session_for_org(org),
            )
            if ok:
                blocked_by.append("waf")
            if ip_memory is not None:
                ip_memory.waf_blocked = ok
                ip_memory.waf_block_error = None if ok else error

        # --- Cloudflare ---
        if org.cloudflare_zone_id and org.cloudflare_token:
            ok, error = block_ip(
                ip=ip,
                zone_id=org.cloudflare_zone_id,
                token=decrypt_secret(org.cloudflare_token),
            )
            if ok:
                blocked_by.append("cloudflare")
            if ip_memory is not None:
                ip_memory.cloudflare_blocked = ok
                ip_memory.cloudflare_block_error = None if ok else error

        if not blocked_by:
            # Nothing was attempted (no WAF IP set, no complete Cloudflare
            # pair): leave a user-facing reason where the dashboard already
            # reads block errors, instead of a silent no-op.
            integration_configured = bool(org.waf_ip_set_id) or bool(
                org.cloudflare_zone_id and org.cloudflare_token
            )
            if not integration_configured and ip_memory is not None:
                ip_memory.waf_block_error = (
                    "No blocking integration is set up. Connect AWS WAF or Cloudflare in Settings."
                )
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
            name, _, set_id = org.waf_ip_set_id.partition("::")
            if not set_id:
                set_id = name
                name = "clew-blocked-ips"
            ok, error = remove_ip_from_set(
                ip=ip,
                waf_ip_set_id=set_id,
                waf_ip_set_name=name,
                region=org.aws_region or "us-east-1",
                session=aws_session_for_org(org),
            )
            if ok:
                unblocked_by.append("waf")
            if ip_memory is not None:
                ip_memory.waf_blocked = not ok
                ip_memory.waf_block_error = None if ok else error

        if org.cloudflare_zone_id and org.cloudflare_token:
            ok, error = unblock_ip(
                ip=ip,
                zone_id=org.cloudflare_zone_id,
                token=decrypt_secret(org.cloudflare_token),
            )
            if ok:
                unblocked_by.append("cloudflare")
            if ip_memory is not None:
                ip_memory.cloudflare_blocked = not ok
                ip_memory.cloudflare_block_error = None if ok else error

        # Item 56: mirror push_block's "no integration succeeded" guard. Only
        # treat this as a failure when at least one integration was actually
        # configured and attempted. An org with no integration configured has
        # nothing to remove remotely: the verdict is cleared locally and the
        # result says "no_integration" so it is never mistaken for a push that
        # really removed a rule ("unblocked", with the integrations in "via").
        integration_configured = bool(org.waf_ip_set_id) or bool(
            org.cloudflare_zone_id and org.cloudflare_token
        )
        if integration_configured and not unblocked_by:
            db.commit()  # persist per-integration error fields even on total failure
            logger.warning(
                "push_unblock: no integration succeeded for org %s", org_id
            )
            return {"status": "failed", "reason": "no_integration_succeeded"}

        db.query(Verdict).filter(Verdict.id == verdict_id).update({"blocked": False})
        db.commit()

        if not integration_configured:
            logger.warning(
                "push_unblock: org %s has no integration configured, verdict %s cleared locally only",
                org_id, verdict_id,
            )
            return {"status": "no_integration", "ip": ip, "via": [], "reason": "no_integration_configured"}

        logger.info(
            "push_unblock: unblocked %s for verdict=%s via %s",
            ip, verdict_id, ",".join(unblocked_by),
        )
        return {"status": "unblocked", "ip": ip, "via": unblocked_by}

    except Exception as exc:
        db.rollback()
        logger.exception("push_unblock: error for verdict %s: %s", verdict_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()
