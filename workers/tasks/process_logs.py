"""
workers/tasks/process_logs.py — S3 ingestion ➜ engine ➜ DB pipeline task.

Safety contract
───────────────
  - `last_processed_key` is updated in the DB *only after* all verdict rows
    for the batch window have been committed.  If the task crashes mid-run,
    Celery retries from the beginning and re-processes the same S3 objects.
    This is intentional: the pipeline is idempotent at the DB level because
    each verdict has a unique UUID primary key.

  - The task holds a single SQLAlchemy session for the full run; it is closed
    in the `finally` block.  Celery does not share sessions between tasks.

  - Every raised exception is logged and re-raised so Celery records the
    failure properly (task_acks_late=True guarantees the message is
    re-queued on crash).

Phase 2: rekeyed from client_id to org_id — S3/blocking config and all
detection data (verdicts, ip_memory, scan_runs) are org-scoped now, not
per-login. `Client` is no longer used anywhere in this module.
"""
from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ipaddress

import httpx
import redis as redis_lib

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

try:
    import maxminddb as _maxminddb
    _MAXMIND_AVAILABLE = True
except ImportError:
    _MAXMIND_AVAILABLE = False

from workers.celery_app import celery_app

# ---------------------------------------------------------------------------
# Engine path — ensure `detection/` is importable even when Celery's cwd differs
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent.parent   # abuse/
_ENGINE_ROOT = _REPO_ROOT / "detection"
for _p in [str(_REPO_ROOT), str(_ENGINE_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from db.models import AlertSent, IpMemory, Organization, ScanRun, Verdict
from db.session import SessionLocal

from engine.ingestion.s3_reader import S3Reader
from engine.ingestion.normalizer import chunk, group_by_ip, parse_lines
from engine.pipeline.run import run_pipeline

_FORMAT_DISPLAY_NAMES = {"apigw": "API Gateway", "alb": "ALB"}

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis connection (shared within one worker process, not across coroutines)
# ---------------------------------------------------------------------------
import os
from dotenv import load_dotenv

load_dotenv()

_redis_client: redis_lib.Redis | None = None


def _get_redis() -> redis_lib.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    return _redis_client


# ---------------------------------------------------------------------------
# Item 32: GeoLite2 lookups (City for country, ASN for provider/network owner)
#
# Mirrors detection/engine/agents/geo_agent.py's pattern (module-level reader,
# per-process cache, graceful None on any failure) but lives here rather than
# in the engine, this is product plumbing for ip_memory, not detection logic.
# Uses maxminddb directly; geoip2 is NOT a dependency and must not be added.
# ---------------------------------------------------------------------------

_GEOIP_CITY_PATH = os.environ.get(
    "GEOIP_MMDB_PATH",
    str(_ENGINE_ROOT / "datasets" / "GeoLite2-City.mmdb"),
)
_GEOIP_ASN_PATH = os.environ.get(
    "GEOIP_ASN_DB_PATH",
    str(_ENGINE_ROOT / "datasets" / "GeoLite2-ASN.mmdb"),
)

_city_reader = None
_asn_reader = None
_geo_cache: dict[str, tuple[str | None, int | None, str | None]] = {}


def _is_private_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return True


def _lookup_geo(ip: str) -> tuple[str | None, int | None, str | None]:
    """Return (country_iso, asn_number, asn_org) for an IP.

    Any of the three can be None independently (e.g. an IP present in the
    City DB but not the ASN DB. Returns (None, None, None) for private IPs,
    unparseable IPs, or if maxminddb / the .mmdb files aren't available.
    """
    if ip in _geo_cache:
        return _geo_cache[ip]

    if not _MAXMIND_AVAILABLE or _is_private_ip(ip):
        _geo_cache[ip] = (None, None, None)
        return _geo_cache[ip]

    global _city_reader, _asn_reader

    country: str | None = None
    if _city_reader is None and os.path.exists(_GEOIP_CITY_PATH):
        try:
            _city_reader = _maxminddb.open_database(_GEOIP_CITY_PATH)
        except Exception:
            _city_reader = None
    if _city_reader is not None:
        try:
            record = _city_reader.get(ip)
            if record and "country" in record:
                country = record["country"].get("iso_code")
        except Exception:
            pass

    asn_number: int | None = None
    asn_org: str | None = None
    if _asn_reader is None and os.path.exists(_GEOIP_ASN_PATH):
        try:
            _asn_reader = _maxminddb.open_database(_GEOIP_ASN_PATH)
        except Exception:
            _asn_reader = None
    if _asn_reader is not None:
        try:
            record = _asn_reader.get(ip)
            if record:
                asn_number = record.get("autonomous_system_number")
                asn_org = record.get("autonomous_system_organization")
        except Exception:
            pass

    _geo_cache[ip] = (country, asn_number, asn_org)
    return _geo_cache[ip]


# ---------------------------------------------------------------------------
# Beat dispatcher — queries DB for configured orgs and fans out tasks
# ---------------------------------------------------------------------------

@celery_app.task(name="workers.tasks.process_logs.poll_all_clients")
def poll_all_clients() -> dict:
    """Dispatch one process_logs task per org with a configured S3 bucket.

    Item 11: an org whose trial has ended with no payment method on file
    (trial_ends_at in the past, billing_provider still pilot/null) is
    skipped here — no new scans, but existing data/dashboard access is
    untouched (that's an API-layer concern, not this dispatcher's).

    Item 40: an org whose owner has deleted their account (deleted_at set)
    is skipped too, for the whole 30-day grace window before hard delete.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        expired_unpaid = and_(
            Organization.trial_ends_at.isnot(None),
            Organization.trial_ends_at < now,
            or_(
                Organization.billing_provider.is_(None),
                Organization.billing_provider == "pilot",
            ),
        )
        orgs = (
            db.query(Organization)
            .filter(
                Organization.s3_bucket.isnot(None),
                Organization.log_format.isnot(None),
                Organization.deleted_at.is_(None),
                ~expired_unpaid,
            )
            .all()
        )
        dispatched = []
        for o in orgs:
            process_logs.delay(o.id)
            dispatched.append(o.id)

        logger.info("poll_all_clients: dispatched %d process_logs tasks", len(dispatched))
        return {"dispatched": len(dispatched)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Per-org pipeline task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="workers.tasks.process_logs.process_logs",
    bind=True,
    max_retries=3,
    default_retry_delay=60,  # 1 min between retries
)
def process_logs(self, org_id: str) -> dict:
    """
    Full pipeline for one org:
      1. Load org config from DB.
      2. Fetch new S3 objects since last_processed_key (or, on first
         connection, the last 7 days only — item 4).
      3. On first connection, sanity-check the configured log format against
         a sample of the most recent object — item 5.
      4. Parse log lines into record dicts.
      5. Pass A: run engine in mixed-IP 500-record window batches.
      6. Pass B: re-run a restricted agent set per IP with >=20 requests in
         this poll cycle (item 1's focus pass — catches attackers whose
         requests would otherwise be diluted across two Pass A windows).
      7. Persist verdicts, scan_runs, and ip_memory rows.
      8. Update last_processed_key (ONLY after all verdicts committed).
      9. Chain send_alerts for high/critical verdicts.

    Item 2: a per-org Redis lock guards the whole run so Beat firing again
    before a large first-connection backlog finishes doesn't double-process
    the same S3 objects from a second worker.
    """
    redis_conn = _get_redis()
    lock_key = f"clew:lock:process:{org_id}"
    if not redis_conn.set(lock_key, 1, ex=1200, nx=True):
        logger.info("process_logs: org %s already running — skipping", org_id)
        return {"status": "skipped", "reason": "already_running"}

    db = SessionLocal()
    try:
        org: Organization | None = db.query(Organization).filter(Organization.id == org_id).first()
        if org is None:
            logger.warning("process_logs: org %s not found — skipping", org_id)
            return {"status": "skipped", "reason": "org_not_found"}

        if not org.s3_bucket or not org.log_format:
            logger.debug("process_logs: org %s has no S3 config — skipping", org_id)
            return {"status": "skipped", "reason": "no_s3_config"}

        # Item 17: this is the primary "Clew is running" trust signal, set
        # in_progress before any work starts, success/error on every exit path.
        org.last_scan_status = "in_progress"
        db.commit()

        # ------------------------------------------------------------------
        # 1. List new S3 objects. First connection (no cursor yet) reads only
        #    the last 7 days (item 4) instead of the whole bucket history.
        # ------------------------------------------------------------------
        reader = S3Reader(
            bucket=org.s3_bucket,
            prefix=org.s3_prefix or "",
            aws_region=org.aws_region or "us-east-1",
            last_processed_key=org.last_processed_key,
        )
        is_first_connection = org.last_processed_key is None
        if is_first_connection:
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            objects = reader.list_objects_since(cutoff)
        else:
            objects = reader.list_new_objects()

        if not objects:
            logger.debug("process_logs: no new objects for org %s", org_id)
            _mark_scan_success(db, org)
            return {"status": "ok", "records": 0, "verdicts": 0}

        # ------------------------------------------------------------------
        # 2. Item 5: on first connection, sanity-check the configured log
        #    format against the most recent object before processing anything.
        # ------------------------------------------------------------------
        if is_first_connection:
            mismatch = _detect_format_mismatch(reader, objects[-1], org.log_format, org_id)
            if mismatch is not None:
                org.s3_status = "error"
                org.s3_status_message = mismatch
                _mark_scan_error(db, org, mismatch)
                logger.warning("process_logs: org %s log format mismatch: %s", org_id, mismatch)
                return {"status": "error", "reason": "log_format_mismatch"}

        new_last_key = objects[-1]["Key"]

        # ------------------------------------------------------------------
        # 3. Read lines, tagging each with a source_key (item 3) —
        #    "{s3_key}:{line_offset_within_that_key}", stable across re-runs
        #    of the same objects so it can dedup at the verdict level.
        # ------------------------------------------------------------------
        lines: list[str] = []
        keys: list[str] = []
        offsets: dict[str, int] = {}
        for key, line in reader.iter_lines(objects):
            idx = offsets.get(key, 0)
            offsets[key] = idx + 1
            lines.append(line)
            keys.append(f"{key}:{idx}")

        if not lines:
            _update_last_key(db, org, new_last_key)
            _mark_scan_success(db, org)
            return {"status": "ok", "records": 0, "verdicts": 0}

        # ------------------------------------------------------------------
        # 4. Parse lines once — shared by Pass A (window) and Pass B (focus)
        # ------------------------------------------------------------------
        records = parse_lines(lines, org.log_format, org_id, keys=keys)
        batches = chunk(records)

        if not batches:
            # Lines were present but all unparseable; advance key to avoid re-reading
            _update_last_key(db, org, new_last_key)
            _mark_scan_success(db, org)
            return {"status": "ok", "records": len(lines), "verdicts": 0, "note": "all_unparseable"}

        # ------------------------------------------------------------------
        # 5. Pass A — mixed-IP window batches (unchanged semantics, writes LTM)
        # ------------------------------------------------------------------
        verdicts_written: list[str] = []

        for batch in batches:
            verdict_dict = run_pipeline(batch, org_id, redis_conn, home_country=org.home_country or "")

            # Item 5e: only actual detections go into `verdicts`. Clean
            # batches write a ScanRun row instead (the "we scanned and found
            # nothing" evidence trail) rather than a severity="none" verdict.
            if verdict_dict.get("is_attack"):
                verdict_id = _persist_verdict(db, org_id, batch, verdict_dict)
                if verdict_id is not None:
                    verdicts_written.append(verdict_id)
            else:
                _persist_scan_run(db, org_id, batch, verdict_dict)

            # Update or insert IpMemory for the primary IP in this batch
            _upsert_ip_memory(db, org_id, batch, verdict_dict)

        # ------------------------------------------------------------------
        # 6. Pass B — per-IP focus pass (item 1). Reads LTM, never writes it.
        # These records were already counted in Pass A's ip_memory updates
        # above, so this pass only ever adds a detection Pass A's window
        # boundaries would otherwise have diluted — no scan_run/ip_memory
        # writes here. No source_key (item 3): focus groups span records from
        # multiple original batches/objects, so there's no single file to key on.
        # ------------------------------------------------------------------
        for ip, ip_records in group_by_ip(records, min_requests=20).items():
            focus_verdict = run_pipeline(
                ip_records, org_id, redis_conn,
                home_country=org.home_country or "", mode="focus",
            )
            if focus_verdict.get("is_attack"):
                verdict_id = _persist_verdict(db, org_id, ip_records, focus_verdict)
                if verdict_id is not None:
                    verdicts_written.append(verdict_id)

        # Commit everything before advancing the S3 cursor
        db.commit()

        # ------------------------------------------------------------------
        # 7. Advance S3 cursor — only after successful commit
        # ------------------------------------------------------------------
        _update_last_key(db, org, new_last_key)

        # ------------------------------------------------------------------
        # 8. Trigger alerts for every detection (async chain). Severity
        # filtering happens inside send_alert_email itself, based on
        # org.alert_severity_threshold (item 22) — enqueuing unconditionally
        # here so "All threats" can actually include medium/low, not just
        # whatever severities this trigger happens to hardcode.
        # ------------------------------------------------------------------
        for verdict_id in verdicts_written:
            v = db.query(Verdict).filter(Verdict.id == verdict_id).first()
            if v and org.alert_email:
                from workers.tasks.send_alerts import send_alert_email
                send_alert_email.delay(verdict_id, org_id)
            # Push block for high/critical on growth/pro tiers only — blocking
            # is a separate, more conservative gate than the alert threshold.
            if v and v.severity in ("high", "critical") and org.tier in ("growth", "pro"):
                from workers.tasks.push_blocks import push_block
                push_block.delay(verdict_id, org_id)

        total_records = sum(len(b) for b in batches)
        logger.info(
            "process_logs: org=%s records=%d batches=%d verdicts=%d",
            org_id, total_records, len(batches), len(verdicts_written),
        )
        _mark_scan_success(db, org)
        return {"status": "ok", "records": total_records, "verdicts": len(verdicts_written)}

    except Exception as exc:
        db.rollback()
        try:
            org = db.query(Organization).filter(Organization.id == org_id).first()
            if org is not None:
                _mark_scan_error(db, org, str(exc))
        except Exception:
            db.rollback()
        logger.exception("process_logs: error for org %s: %s", org_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()
        redis_conn.delete(lock_key)
        # Item 50 Layer 2: Cronitor beat heartbeat, must never fail the scan.
        cronitor_url = os.environ.get("CRONITOR_URL", "")
        if cronitor_url:
            try:
                httpx.get(cronitor_url, timeout=3)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Item 45 Gap A — one-off silent calibration pass
# ---------------------------------------------------------------------------

@celery_app.task(
    name="workers.tasks.process_logs.calibrate_client",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def calibrate_client(self, org_id: str) -> dict:
    """
    Run on first S3 connection (or reconnection to a new bucket/prefix — see
    api/routes/clients.py's PATCH /clients/me). Reads the last 24h of logs
    and runs them through the SAME pipeline code path as process_logs, in
    window mode, so VolumeAgent/PayloadAgent/TemporalAgent/GeoIPAgent's LTM
    (batch_stats, batch_count, baseline rates) is warmed before live
    detection starts.

    Differences from process_logs's real Pass A:
      - Reads by LastModified >= now-24h (S3Reader.list_objects_since),
        completely independent of last_processed_key — this must NOT
        advance the real ingestion cursor, so the same 24h of logs get
        properly re-processed for real verdicts afterward.
      - No verdict/scan_run/ip_memory rows are written — this warms
        thresholds, it does not produce verdicts (TODO item 45 Gap A).
      - No Pass B focus pass — focus-mode batches never call
        record_batch_stats() (by design, see item 1), so running it here
        would not contribute anything to calibration.
    """
    db = SessionLocal()
    try:
        org: Organization | None = db.query(Organization).filter(Organization.id == org_id).first()
        if org is None:
            logger.warning("calibrate_client: org %s not found — skipping", org_id)
            return {"status": "skipped", "reason": "org_not_found"}

        if not org.s3_bucket or not org.log_format:
            logger.debug("calibrate_client: org %s has no S3 config — skipping", org_id)
            return {"status": "skipped", "reason": "no_s3_config"}

        org.calibration_status = "running"
        db.commit()

        reader = S3Reader(
            bucket=org.s3_bucket,
            prefix=org.s3_prefix or "",
            aws_region=org.aws_region or "us-east-1",
        )
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        objects = reader.list_objects_since(cutoff)

        if not objects:
            org.calibration_status = "done"
            db.commit()
            logger.info("calibrate_client: org=%s no objects in last 24h", org_id)
            return {"status": "ok", "records": 0, "batches": 0}

        lines = [line for _key, line in reader.iter_lines(objects)]
        records = parse_lines(lines, org.log_format, org_id)
        batches = chunk(records)

        redis_conn = _get_redis()
        for batch in batches:
            # Window mode writes LTM exactly like Pass A does; the verdict
            # dict is discarded on purpose — no _persist_verdict/_persist_scan_run/
            # _upsert_ip_memory calls, and last_processed_key is never touched.
            run_pipeline(batch, org_id, redis_conn, home_country=org.home_country or "")

        org.calibration_status = "done"
        db.commit()

        logger.info(
            "calibrate_client: org=%s records=%d batches=%d",
            org_id, len(records), len(batches),
        )
        return {"status": "ok", "records": len(records), "batches": len(batches)}

    except Exception as exc:
        db.rollback()
        try:
            org = db.query(Organization).filter(Organization.id == org_id).first()
            if org is not None:
                org.calibration_status = "failed"
                db.commit()
        except Exception:
            db.rollback()
        logger.exception("calibrate_client: error for org %s: %s", org_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers — keep the task function readable
# ---------------------------------------------------------------------------

def _batch_timestamps(batch: list[dict]) -> list[datetime]:
    """Parse every valid timestamp in the batch (used for min/max, not batch[0])."""
    timestamps: list[datetime] = []
    for rec in batch:
        try:
            timestamps.append(
                datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00"))
            )
        except (KeyError, ValueError, AttributeError):
            pass
    return timestamps


def _detect_format_mismatch(
    reader: S3Reader, latest_object: dict, configured_format: str, org_id: str,
) -> str | None:
    """Item 5: sample the first 10 lines of the most recent S3 object and
    check the configured log format actually parses them. Returns a
    user-facing error message if the OTHER format parses cleanly and the
    configured one doesn't, else None (proceed normally).
    """
    from itertools import islice

    sample = [line for _key, line in islice(reader.iter_lines([latest_object]), 10)]
    if not sample:
        return None

    configured_rate = len(parse_lines(sample, configured_format, org_id)) / len(sample)
    if configured_rate >= 0.5:
        return None

    other_format = "alb" if configured_format == "apigw" else "apigw"
    other_rate = len(parse_lines(sample, other_format, org_id)) / len(sample)
    if other_rate < 0.5:
        return None  # neither format parses well — not a format mismatch, let it through

    configured_name = _FORMAT_DISPLAY_NAMES.get(configured_format, configured_format)
    other_name = _FORMAT_DISPLAY_NAMES.get(other_format, other_format)
    return (
        f"Log format mismatch: logs appear to be {other_name} format but you "
        f"selected {configured_name}. Update your log format in Settings."
    )


def _sample_logs(batch: list[dict], verdict_dict: dict) -> list[str]:
    """Item 19's "5 most suspicious requests" raw log sample.

    No per-record suspicion score exists anywhere in the engine, batches are
    scored as a whole, not line by line. Approximated instead: prefer lines
    matching the verdict's attributed ip/endpoint (the ones that actually
    drove this detection), padded with the batch's own first lines if fewer
    than 5 match. Each line truncated at 512 chars. Lines predating item 19
    (no `raw_line` key, e.g. re-processed old data) are skipped.
    """
    ip = verdict_dict.get("ip")
    endpoint = verdict_dict.get("endpoint")

    matching = [
        r["raw_line"] for r in batch
        if r.get("raw_line") and (r.get("ip") == ip or r.get("endpoint") == endpoint)
    ]
    fallback = [r["raw_line"] for r in batch if r.get("raw_line")]

    sample: list[str] = []
    for line in matching + fallback:
        if line in sample:
            continue
        sample.append(line)
        if len(sample) >= 5:
            break

    return [line[:512] for line in sample]


def _persist_verdict(
    db,
    org_id: str,
    batch: list[dict],
    verdict_dict: dict,
) -> str | None:
    """Insert a Verdict row and return its UUID, or None if skipped as a
    duplicate (item 3).

    ip/method/endpoint come from verdict_dict — the pipeline's own attribution
    of the dominant IP/method/endpoint for this batch — not batch[0], which is
    just whichever record happened to be parsed first and may be an unrelated
    benign request sharing a batch with the actual attacker.
    """
    timestamps = _batch_timestamps(batch)
    ts = max(timestamps) if timestamps else datetime.now(timezone.utc)

    # Item 3: dedup key is the first record's source_key (stable across
    # re-runs of the same objects in the same order — see process_logs's
    # offset-tagging comment). Pass B focus batches have no source_key
    # (spans multiple original files), so they're never deduped this way.
    source_key = batch[0].get("source_key") if batch else None
    if source_key is not None:
        existing = (
            db.query(Verdict)
            .filter(Verdict.org_id == org_id, Verdict.source_key == source_key)
            .first()
        )
        if existing is not None:
            logger.info(
                "process_logs: skipping duplicate verdict for org=%s source_key=%s",
                org_id, source_key,
            )
            return None

    v = Verdict(
        id=str(uuid.uuid4()),
        org_id=org_id,
        timestamp=ts,
        ip=verdict_dict.get("ip", ""),
        method=verdict_dict.get("method"),
        endpoint=verdict_dict.get("endpoint"),
        threat_type=verdict_dict.get("threat_type"),
        severity=verdict_dict.get("severity", "low"),
        confidence=float(verdict_dict.get("confidence", 0.0)),
        agents_triggered=verdict_dict.get("agents_triggered", []),
        explanation=verdict_dict.get("explanation"),
        blocked=False,
        cost_prevented=verdict_dict.get("cost_prevented"),
        source_key=source_key,
        sample_logs=_sample_logs(batch, verdict_dict),
        agent_scores=verdict_dict.get("agent_scores"),
    )
    if source_key is not None:
        # The SELECT above can't fully close the race two concurrent workers
        # create (item 2's lock failing open after a Redis restart) — wrap
        # the insert in its own savepoint so a duplicate only rolls back this
        # one row, not every verdict/scan_run/ip_memory change made so far in
        # this run's single end-of-task commit.
        try:
            with db.begin_nested():
                db.add(v)
                db.flush()
        except IntegrityError:
            # begin_nested()'s context manager already rolled back to the
            # savepoint on exception exit — do NOT call db.rollback() here,
            # that would discard the whole session's work, not just this row.
            logger.info(
                "process_logs: race-detected duplicate verdict for org=%s source_key=%s",
                org_id, source_key,
            )
            return None
    else:
        db.add(v)
    return v.id


def _persist_scan_run(
    db,
    org_id: str,
    batch: list[dict],
    verdict_dict: dict,
) -> str:
    """Insert a ScanRun row and return its UUID.

    Written for benign batches instead of a Verdict row — see item 5e.
    `verdicts` stays reserved for actual detections; this table is the
    "we scanned and found nothing" evidence trail item 16's last-scanned
    indicator reads from.
    """
    timestamps = _batch_timestamps(batch)
    ts = max(timestamps) if timestamps else datetime.now(timezone.utc)

    s = ScanRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        scanned_at=ts,
        record_count=len(batch),
    )
    db.add(s)
    return s.id


def _upsert_ip_memory(
    db,
    org_id: str,
    batch: list[dict],
    verdict_dict: dict,
) -> None:
    """Update IpMemory running totals for the primary IP in the batch.

    ip comes from verdict_dict (the pipeline's attribution), not batch[0] —
    see _persist_verdict for why batch[0] is unsafe to use for attribution.
    """
    if not batch:
        return

    ip = verdict_dict.get("ip", "")
    if not ip:
        return

    # Determine first_seen/last_seen from the earliest/latest timestamp in the batch
    timestamps = _batch_timestamps(batch)
    now = datetime.now(timezone.utc)
    first_seen = min(timestamps) if timestamps else now
    last_seen = max(timestamps) if timestamps else now

    is_threat = bool(verdict_dict.get("is_attack", False))
    confidence = float(verdict_dict.get("confidence", 0.0))

    existing: IpMemory | None = (
        db.query(IpMemory)
        .filter(IpMemory.org_id == org_id, IpMemory.ip == ip)
        .first()
    )

    if existing:
        existing.last_seen = last_seen
        existing.total_requests += len(batch)
        if is_threat:
            existing.threat_count += 1
        # Rolling average of risk_score (weighted toward recent score)
        existing.risk_score = round(existing.risk_score * 0.7 + confidence * 0.3, 4)
        # Item 32: (re)resolve geo/ASN on every update, cheap (cached) and
        # picks up a country/ASN this IP didn't have on first insert if the
        # .mmdb files weren't available yet at that time.
        country, asn_number, asn_org = _lookup_geo(ip)
        if country:
            existing.geo_country = country
        if asn_number is not None:
            existing.geo_asn_number = asn_number
        if asn_org:
            existing.geo_asn_org = asn_org
    else:
        country, asn_number, asn_org = _lookup_geo(ip)
        db.add(IpMemory(
            id=str(uuid.uuid4()),
            org_id=org_id,
            ip=ip,
            first_seen=first_seen,
            last_seen=last_seen,
            total_requests=len(batch),
            threat_count=1 if is_threat else 0,
            risk_score=round(confidence, 4),
            geo_country=country,
            geo_asn_number=asn_number,
            geo_asn_org=asn_org,
        ))


def _update_last_key(db, org: Organization, new_last_key: str | None) -> None:
    """Persist the new S3 cursor. Called only after verdicts are committed."""
    if new_last_key:
        org.last_processed_key = new_last_key
        db.commit()


def _mark_scan_success(db, org: Organization) -> None:
    """Item 17: record a clean run, even one that found nothing new."""
    org.last_scan_status = "success"
    org.last_scan_completed_at = datetime.now(timezone.utc)
    org.last_scan_error = None
    db.commit()


def _mark_scan_error(db, org: Organization, message: str) -> None:
    """Item 17: record a failed run without clobbering last_scan_completed_at
    (that stays the last time a scan actually succeeded)."""
    org.last_scan_status = "error"
    org.last_scan_error = message[:2000]
    db.commit()
