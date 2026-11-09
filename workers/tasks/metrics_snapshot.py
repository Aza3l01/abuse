"""workers/tasks/metrics_snapshot.py: daily business metrics snapshot (Phase 6).

Writes one metrics_daily row per currency from Postgres (api/metrics.py), so
the ops panel keeps a history. Scheduled at 19:30 UTC, 30 minutes after
billing_cycle (19:00 UTC, 00:30 IST), so the day's bill issuing and downgrades
are already in. Imports sit at module level on purpose: a lazy import inside a
task body can fail in a forked Celery worker child.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from api.metrics import compute_snapshot, store_snapshot
from db.session import SessionLocal
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def run_metrics_snapshot(db) -> list[dict]:
    """Compute and store today's rows (re-running the same day updates them)."""
    rows = compute_snapshot(db)
    store_snapshot(db, rows)
    db.commit()
    if rows and rows[0]["inr_per_usd"] is None:
        logger.warning("metrics_snapshot: METRICS_INR_PER_USD missing or invalid, combined INR figures not available")
    logger.info("metrics_snapshot: stored %d rows for %s", len(rows), rows[0]["snapshot_date"] if rows else "-")
    return rows


@celery_app.task(name="workers.tasks.metrics_snapshot.metrics_snapshot")
def metrics_snapshot() -> dict:
    db = SessionLocal()
    try:
        rows = run_metrics_snapshot(db)
        return {"rows": len(rows)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
