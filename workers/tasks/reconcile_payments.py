"""
workers/tasks/reconcile_payments.py: Phase 10 daily payment reconciliation.

Compares what Razorpay says it captured in the last 48 hours with the local
`payments` rows and reports every difference. The usual cause is a webhook
that never arrived (or arrived and failed) for a customer who also closed the
browser before the verify-payment call: Razorpay has the money, the org still
sits on its old plan.

Report only: nothing is applied or refunded here. Staff decide in the ops
panel (system health page), which reads the result this task stores in Redis
through workers.task_runs.save_reconciliation.

Discrepancy kinds:
  missed_webhook     Razorpay captured it, the local row is still created/failed.
  unknown_order      Razorpay captured it, there is no local row for its order.
  amount_mismatch    Local amount or currency differs from Razorpay's.
  not_on_razorpay    Locally captured in the window, Razorpay has no such payment.

Payments newer than GRACE are skipped: the webhook may simply be on its way.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from db.models import Payment
from db.session import SessionLocal
from workers.celery_app import celery_app
from workers.task_runs import save_reconciliation

logger = logging.getLogger(__name__)

WINDOW = timedelta(hours=48)
GRACE = timedelta(minutes=15)
PAGE_SIZE = 100
MAX_PAGES = 50
# Razorpay statuses that mean the money was taken (a refunded payment was
# captured first).
PAID_STATUSES = ("captured", "refunded")


def _razorpay_client():
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not (key_id and key_secret):
        return None
    import razorpay

    return razorpay.Client(auth=(key_id, key_secret))


def fetch_remote_payments(client, start: datetime, end: datetime) -> list[dict]:
    """Every Razorpay payment created in [start, end]."""
    items: list[dict] = []
    for page in range(MAX_PAGES):
        batch = client.payment.all(
            {"from": int(start.timestamp()), "to": int(end.timestamp()), "count": PAGE_SIZE, "skip": page * PAGE_SIZE}
        ).get("items", [])
        items.extend(batch)
        if len(batch) < PAGE_SIZE:
            return items
    logger.error("reconcile_payments: more than %d Razorpay payments in the window, result is partial", MAX_PAGES * PAGE_SIZE)
    return items


def reconcile(remote: list[dict], db, now: datetime) -> dict:
    """Compare Razorpay payments `remote` with local Payment rows. Only reads `db`."""
    window_start = now - WINDOW
    cutoff = now - GRACE
    paid = [p for p in remote if p.get("status") in PAID_STATUSES]
    order_ids = [p["order_id"] for p in paid if p.get("order_id")]
    local_by_order = (
        {
            row.razorpay_order_id: row
            for row in db.query(Payment).filter(Payment.razorpay_order_id.in_(order_ids)).all()
        }
        if order_ids
        else {}
    )

    discrepancies: list[dict] = []

    def add(kind: str, detail: str, remote_p: dict | None, local: Payment | None) -> None:
        discrepancies.append({
            "kind": kind,
            "detail": detail,
            "razorpay_payment_id": remote_p.get("id") if remote_p else local.razorpay_payment_id,
            "razorpay_order_id": remote_p.get("order_id") if remote_p else local.razorpay_order_id,
            "local_payment_id": local.id if local else None,
            "org_name": local.org_name_snapshot if local else None,
            "amount_paise": remote_p.get("amount") if remote_p else local.amount_paise,
            "currency": remote_p.get("currency") if remote_p else local.currency,
        })

    checked = 0
    for p in paid:
        created = datetime.fromtimestamp(p.get("created_at", 0), tz=timezone.utc)
        if created > cutoff:
            continue
        checked += 1
        local = local_by_order.get(p.get("order_id"))
        if local is None:
            add("unknown_order", "Razorpay captured a payment with no local row for its order.", p, None)
        elif local.status in ("created", "failed"):
            add("missed_webhook", f"Razorpay captured it but the local payment is still {local.status}.", p, local)
        elif local.amount_paise != p.get("amount") or local.currency != p.get("currency"):
            add(
                "amount_mismatch",
                f"Local {local.amount_paise} {local.currency}, Razorpay {p.get('amount')} {p.get('currency')}.",
                p, local,
            )

    remote_ids = {p.get("id") for p in paid}
    local_captured = (
        db.query(Payment)
        .filter(Payment.status == "captured", Payment.captured_at >= window_start, Payment.captured_at <= cutoff)
        .all()
    )
    for local in local_captured:
        if local.razorpay_payment_id not in remote_ids:
            add("not_on_razorpay", "Captured locally but Razorpay returned no such captured payment.", None, local)

    return {
        "ran_at": now.isoformat(),
        "window_start": window_start.isoformat(),
        "checked": checked,
        "discrepancies": discrepancies,
    }


@celery_app.task(name="workers.tasks.reconcile_payments.reconcile_payments")
def reconcile_payments() -> dict:
    client = _razorpay_client()
    if client is None:
        logger.warning("reconcile_payments: Razorpay keys are not set, skipped")
        return {"status": "skipped", "reason": "razorpay_not_configured"}

    now = datetime.now(timezone.utc)
    remote = fetch_remote_payments(client, now - WINDOW, now)
    db = SessionLocal()
    try:
        result = reconcile(remote, db, now)
    finally:
        db.close()

    if result["discrepancies"]:
        logger.error(
            "reconcile_payments: %d discrepancies in %d payments: %s",
            len(result["discrepancies"]), result["checked"],
            [(d["kind"], d["razorpay_payment_id"]) for d in result["discrepancies"]],
        )
    else:
        logger.info("reconcile_payments: %d payments checked, no discrepancies", result["checked"])
    save_reconciliation(result)
    return {"status": "ok", "checked": result["checked"], "discrepancies": len(result["discrepancies"])}
