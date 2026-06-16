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
"""
from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import redis as redis_lib

from workers.celery_app import celery_app

# ---------------------------------------------------------------------------
# Engine path — ensure `detection/` is importable even when Celery's cwd differs
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent.parent   # abuse/
_ENGINE_ROOT = _REPO_ROOT / "detection"
for _p in [str(_REPO_ROOT), str(_ENGINE_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from db.models import AlertSent, Client, IpMemory, Verdict
from db.session import SessionLocal

from engine.ingestion.s3_reader import S3Reader
from engine.ingestion.normalizer import normalize
from engine.pipeline.run import run_pipeline

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
# Beat dispatcher — queries DB for configured clients and fans out tasks
# ---------------------------------------------------------------------------

@celery_app.task(name="workers.tasks.process_logs.poll_all_clients")
def poll_all_clients() -> dict:
    """Dispatch one process_logs task per client with a configured S3 bucket."""
    db = SessionLocal()
    try:
        clients = (
            db.query(Client)
            .filter(
                Client.s3_bucket.isnot(None),
                Client.log_format.isnot(None),
            )
            .all()
        )
        dispatched = []
        for c in clients:
            process_logs.delay(c.id)
            dispatched.append(c.id)

        logger.info("poll_all_clients: dispatched %d process_logs tasks", len(dispatched))
        return {"dispatched": len(dispatched)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Per-client pipeline task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="workers.tasks.process_logs.process_logs",
    bind=True,
    max_retries=3,
    default_retry_delay=60,  # 1 min between retries
)
def process_logs(self, client_id: str) -> dict:
    """
    Full pipeline for one client:
      1. Load client config from DB.
      2. Fetch new S3 objects since last_processed_key.
      3. Parse + normalise log lines into record dicts.
      4. Run engine in 500-record batches.
      5. Persist verdicts and ip_memory rows.
      6. Update last_processed_key (ONLY after all verdicts committed).
      7. Chain send_alerts for high/critical verdicts.
    """
    db = SessionLocal()
    try:
        client: Client | None = db.query(Client).filter(Client.id == client_id).first()
        if client is None:
            logger.warning("process_logs: client %s not found — skipping", client_id)
            return {"status": "skipped", "reason": "client_not_found"}

        if not client.s3_bucket or not client.log_format:
            logger.debug("process_logs: client %s has no S3 config — skipping", client_id)
            return {"status": "skipped", "reason": "no_s3_config"}

        # ------------------------------------------------------------------
        # 1. Read new S3 objects
        # ------------------------------------------------------------------
        reader = S3Reader(
            bucket=client.s3_bucket,
            prefix=client.s3_prefix or "",
            aws_region=client.aws_region or "us-east-1",
            last_processed_key=client.last_processed_key,
        )
        lines, new_last_key = reader.read_all()

        if not lines:
            logger.debug("process_logs: no new lines for client %s", client_id)
            return {"status": "ok", "records": 0, "verdicts": 0}

        # ------------------------------------------------------------------
        # 2. Normalise lines into batches
        # ------------------------------------------------------------------
        batches = normalize(lines, client.log_format, client_id)

        if not batches:
            # Lines were present but all unparseable; advance key to avoid re-reading
            _update_last_key(db, client, new_last_key)
            return {"status": "ok", "records": len(lines), "verdicts": 0, "note": "all_unparseable"}

        # ------------------------------------------------------------------
        # 3. Process batches through the engine
        # ------------------------------------------------------------------
        redis_conn = _get_redis()
        verdicts_written: list[str] = []

        for batch in batches:
            verdict_dict = run_pipeline(batch, client_id, redis_conn)
            verdict_id = _persist_verdict(db, client_id, batch, verdict_dict)
            verdicts_written.append(verdict_id)

            # Update or insert IpMemory for the primary IP in this batch
            _upsert_ip_memory(db, client_id, batch, verdict_dict)

        # Commit everything before advancing the S3 cursor
        db.commit()

        # ------------------------------------------------------------------
        # 4. Advance S3 cursor — only after successful commit
        # ------------------------------------------------------------------
        _update_last_key(db, client, new_last_key)

        # ------------------------------------------------------------------
        # 5. Trigger alerts for high/critical verdicts (async chain)
        # ------------------------------------------------------------------
        for verdict_id in verdicts_written:
            v = db.query(Verdict).filter(Verdict.id == verdict_id).first()
            if v and v.severity in ("high", "critical") and client.alert_email:
                from workers.tasks.send_alerts import send_alert_email
                send_alert_email.delay(verdict_id, client_id)
            # Push block for high/critical on growth/pro tiers
            if v and v.severity in ("high", "critical") and client.tier in ("growth", "pro"):
                from workers.tasks.push_blocks import push_block
                push_block.delay(verdict_id, client_id)

        total_records = sum(len(b) for b in batches)
        logger.info(
            "process_logs: client=%s records=%d batches=%d verdicts=%d",
            client_id, total_records, len(batches), len(verdicts_written),
        )
        return {"status": "ok", "records": total_records, "verdicts": len(verdicts_written)}

    except Exception as exc:
        db.rollback()
        logger.exception("process_logs: error for client %s: %s", client_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers — keep the task function readable
# ---------------------------------------------------------------------------

def _persist_verdict(
    db,
    client_id: str,
    batch: list[dict],
    verdict_dict: dict,
) -> str:
    """Insert a Verdict row and return its UUID."""
    first = batch[0] if batch else {}

    # Parse timestamp safely
    ts_raw = first.get("timestamp", "")
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        ts = datetime.now(timezone.utc)

    v = Verdict(
        id=str(uuid.uuid4()),
        client_id=client_id,
        timestamp=ts,
        ip=first.get("ip", ""),
        method=first.get("method"),
        endpoint=first.get("endpoint"),
        threat_type=verdict_dict.get("threat_type"),
        severity=verdict_dict.get("severity", "low"),
        confidence=float(verdict_dict.get("confidence", 0.0)),
        agents_triggered=verdict_dict.get("agents_triggered", []),
        explanation=verdict_dict.get("explanation"),
        blocked=False,
        cost_prevented=verdict_dict.get("cost_prevented"),
    )
    db.add(v)
    return v.id


def _upsert_ip_memory(
    db,
    client_id: str,
    batch: list[dict],
    verdict_dict: dict,
) -> None:
    """Update IpMemory running totals for the primary IP in the batch."""
    if not batch:
        return

    ip = batch[0].get("ip", "")
    if not ip:
        return

    # Determine first_seen from the earliest timestamp in the batch
    timestamps: list[datetime] = []
    for rec in batch:
        try:
            timestamps.append(
                datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00"))
            )
        except (KeyError, ValueError):
            pass
    now = datetime.now(timezone.utc)
    first_seen = min(timestamps) if timestamps else now
    last_seen = max(timestamps) if timestamps else now

    is_threat = bool(verdict_dict.get("is_attack", False))
    confidence = float(verdict_dict.get("confidence", 0.0))

    existing: IpMemory | None = (
        db.query(IpMemory)
        .filter(IpMemory.client_id == client_id, IpMemory.ip == ip)
        .first()
    )

    if existing:
        existing.last_seen = last_seen
        existing.total_requests += len(batch)
        if is_threat:
            existing.threat_count += 1
        # Rolling average of risk_score (weighted toward recent score)
        existing.risk_score = round(existing.risk_score * 0.7 + confidence * 0.3, 4)
    else:
        db.add(IpMemory(
            id=str(uuid.uuid4()),
            client_id=client_id,
            ip=ip,
            first_seen=first_seen,
            last_seen=last_seen,
            total_requests=len(batch),
            threat_count=1 if is_threat else 0,
            risk_score=round(confidence, 4),
        ))


def _update_last_key(db, client: Client, new_last_key: str | None) -> None:
    """Persist the new S3 cursor. Called only after verdicts are committed."""
    if new_last_key:
        client.last_processed_key = new_last_key
        db.commit()
