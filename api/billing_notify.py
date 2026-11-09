"""api/billing_notify.py: billing notification hook.

The daily billing engine and the payment routes call notify() at each point
that needs an email. notify() validates the kind and queues the Celery task
in workers/tasks/billing_emails.py, which sends the real email (recipients
per the org's billing_emails_mode, see api/billing_emails.py). Callers must
call it AFTER their database commit, so the task only ever sees committed
rows and a rolled back change never emails anyone.

A failure to queue is logged, never raised: an email problem must not break
the billing cycle or a payment confirmation.

Kinds:
  ready             a bill was issued (due the 20th)
  due_in_3          the bill is due in 3 days (the 17th)
  cancel_in_3       the plan cancels in 3 days for an unpaid bill
  cancelled         the org was downgraded (non-payment or voluntary cancel)
  payment_received  a payment was captured
"""
from __future__ import annotations

import logging

from workers.tasks.billing_emails import send_billing_email

logger = logging.getLogger(__name__)

NOTIFY_KINDS = frozenset({"ready", "due_in_3", "cancel_in_3", "cancelled", "payment_received"})


def _enqueue(kind: str, org_id: str, bill_id: str | None, payment_id: str | None) -> None:
    send_billing_email.delay(kind, org_id, bill_id, payment_id)


def notify(kind: str, org, bill=None, payment=None) -> None:
    """Queue a billing email. `bill` is None for kinds that have no bill (a
    voluntary cancel), `payment` is only for payment_received. Raises
    ValueError for an unknown kind so a typo in a caller fails loudly instead
    of silently dropping a notice."""
    if kind not in NOTIFY_KINDS:
        raise ValueError(f"unknown billing notification kind: {kind!r}")
    org_id = getattr(org, "id", None)
    bill_id = getattr(bill, "id", None)
    payment_id = getattr(payment, "id", None)
    logger.info(
        "billing notify: kind=%s org_id=%s bill_id=%s payment_id=%s",
        kind, org_id, bill_id, payment_id,
    )
    try:
        _enqueue(kind, org_id, bill_id, payment_id)
    except Exception:
        logger.exception("billing notify: could not queue %s for org %s", kind, org_id)
