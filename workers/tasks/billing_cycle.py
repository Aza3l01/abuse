"""
workers/tasks/billing_cycle.py: Phase 3 daily billing engine.

Runs daily at 19:00 UTC (00:30 IST) via Beat. All calendar rules are IST, so
the Celery task computes "today" with today_ist(). The core
run_billing_cycle(db, today) takes the date as an argument so tests can
drive any day, and is safe to run twice or after a missed day: every step is
guarded by state (a bill's unique (org_id, period_start), the *_sent_at
columns, the org's tier), never by "this is the right weekday".

Order in one run (this order matters, enforcement must come before
generation so an org that missed a payment never gets a fresh bill):
  1. Enforce: an open bill whose cancel_on has arrived downgrades the org
     ("nonpayment"). The bill stays open (Restore pays it later).
  2. Voluntary cancel: an org with cancel_at_period_end whose
     next_billing_date has arrived is downgraded ("cancel"), no bill.
  3. Generate: a paid org whose next_billing_date has arrived gets a bill
     (a scheduled pending_tier / pending_period is applied first) and
     next_billing_date moves forward one period. At most one bill per org
     per run, so a long outage catches up one period per day. Phase 12:
     the bill is reduced by the org's referral credit (api/referrals.py),
     and a bill covered in full is issued already paid.
  4. Remind: notify "ready", "due_in_3" and "cancel_in_3" once per bill.

Phase 12 adds a vest step between 2 and 3: a pending referrer credit whose
referee's first payment has stood for the 72 hour refund window becomes
available, so it can reduce a bill generated in the same run.

downgrade_org is the one and only downgrade path (the nonpayment and cancel
steps above, and trial_reminders.py for an expired pilot trial). Pilot and
trial orgs have no next_billing_date, so this engine never bills them.

Module-level imports only: a lazy import inside a Celery task body can fail
intermittently in a forked worker child, so every import sits at the top.
"""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from api import analytics
from api.billing_notify import notify
from api.billing_rules import (
    RETENTION_GRACE_DAYS,
    cancel_on_for,
    cancel_reminder_date_for,
    due_date_for,
    due_reminder_date_for,
    ist_date,
    ist_midnight,
    next_bill_date_after_issue,
    today_ist,
)
from api.referrals import apply_credits_to_bill, pending_reward_ids, vest_one
from api.tiers import PAID_TIER_ORDER, PURCHASABLE_PLANS, plan_price
from db.models import Bill, BillingEvent, Organization
from db.session import SessionLocal
from workers.celery_app import celery_app
from workers.heartbeat import ping as ping_heartbeat

logger = logging.getLogger(__name__)

# downgrade_org reason -> BillingEvent.event
_DOWNGRADE_EVENTS = {
    "nonpayment": "nonpayment_downgrade",
    "cancel": "cancelled",
    "trial_end": "trial_end",
    "refund": "refunded",
}


def downgrade_org(
    org, db, reason: str, now: datetime | None = None, amount_paise: int | None = None
) -> bool:
    """Move `org` to the free tier. `reason` is 'nonpayment', 'cancel',
    'trial_end' or 'refund' (`amount_paise` is the refunded total, stored on
    the event). The one downgrade path, no parallel logic anywhere else.

    The old tier's retention keeps applying for 30 days (retention_grace_*),
    automatic blocking is switched off (existing blocks stay and can still be
    unblocked), and every billing schedule field is cleared. Only
    'nonpayment' sets nonpayment_downgraded_at, which is what makes Restore
    available. Open bills stay open. A BillingEvent row is added in the same
    transaction. Does not commit, the caller does.

    Returns False and changes nothing when the org is already on the free
    tier, so calling it twice is harmless.
    """
    if reason not in _DOWNGRADE_EVENTS:
        raise ValueError(f"unknown downgrade reason: {reason!r}")
    if org.tier == "starter":
        return False

    moment = now if now is not None else datetime.now(timezone.utc)
    old_tier = org.tier
    old_period = org.billing_period

    org.retention_grace_tier = old_tier
    org.retention_grace_until = moment + timedelta(days=RETENTION_GRACE_DAYS)
    org.tier = "starter"
    org.auto_block_enabled = False
    org.next_billing_date = None
    org.billing_period = None
    org.cancel_at_period_end = False
    org.pending_tier = None
    org.pending_period = None
    if reason == "nonpayment":
        org.nonpayment_downgraded_at = moment

    db.add(
        BillingEvent(
            org_id=org.id,
            event=_DOWNGRADE_EVENTS[reason],
            from_tier=old_tier,
            to_tier="starter",
            period=old_period,
            amount_paise=amount_paise,
            currency=org.billing_currency if amount_paise is not None else None,
            created_at=moment,
        )
    )
    if reason != "trial_end":
        # Phase 11: queued on the session, sent only after the caller commits.
        analytics.queue_org_event(
            db, org.id, "plan_cancelled",
            {"reason": reason, "from_tier": old_tier, "period": old_period},
        )
    return True


def _enforce(db, today: date, now: datetime, stats: dict) -> None:
    """Step 1: downgrade every org holding an open bill past its cancel_on."""
    bills = (
        db.query(Bill)
        .filter(Bill.status == "open", Bill.cancel_on <= today, Bill.org_id.isnot(None))
        .order_by(Bill.cancel_on)
        .all()
    )
    for bill in bills:
        try:
            org = db.get(Organization, bill.org_id)
            if org is None or org.deleted_at is not None:
                continue
            if downgrade_org(org, db, "nonpayment", now):
                db.commit()
                stats["nonpayment_downgrades"] += 1
                notify("cancelled", org, bill)
        except Exception:
            db.rollback()
            stats["errors"] += 1
            logger.exception("billing_cycle: enforce failed for bill %s", bill.id)


def _voluntary_cancel(db, today: date, now: datetime, stats: dict) -> None:
    """Step 2: end the plan of every org that asked to cancel at period end."""
    orgs = (
        db.query(Organization)
        .filter(
            Organization.cancel_at_period_end.is_(True),
            Organization.tier != "starter",
            Organization.next_billing_date.isnot(None),
            Organization.deleted_at.is_(None),
        )
        .all()
    )
    for org in orgs:
        try:
            if ist_date(org.next_billing_date) > today:
                continue
            if downgrade_org(org, db, "cancel", now):
                db.commit()
                stats["cancellations"] += 1
                notify("cancelled", org, None)
        except Exception:
            db.rollback()
            stats["errors"] += 1
            logger.exception("billing_cycle: cancel failed for org %s", org.id)


def _apply_pending(org, db, now: datetime) -> None:
    """Apply a scheduled downgrade (lower tier or annual to monthly) at bill
    issue. An unpurchasable combination is dropped with a warning rather than
    billed."""
    new_tier = org.pending_tier or org.tier
    new_period = org.pending_period or org.billing_period
    old_tier = org.tier
    if (new_tier, new_period) not in PURCHASABLE_PLANS:
        logger.warning(
            "billing_cycle: dropping invalid pending change for org %s: %s/%s",
            org.id, new_tier, new_period,
        )
    elif (new_tier, new_period) != (old_tier, org.billing_period):
        db.add(
            BillingEvent(
                org_id=org.id,
                event="downgraded",
                from_tier=old_tier,
                to_tier=new_tier,
                period=new_period,
                created_at=now,
            )
        )
        org.tier = new_tier
        org.billing_period = new_period
    org.pending_tier = None
    org.pending_period = None


def _vest_credits(db, now: datetime, stats: dict) -> None:
    """Phase 12: vest every pending referrer credit whose referee's first
    payment has cleared the 72 hour refund window. One credit per
    transaction, so a bad row cannot block the others. Idempotent: a vested
    or held credit is no longer pending."""
    for credit_id in pending_reward_ids(db):
        try:
            outcome = vest_one(db, credit_id, now)
            db.commit()
            if outcome == "vested":
                stats["credits_vested"] += 1
            elif outcome == "held":
                stats["credits_held"] += 1
        except Exception:
            db.rollback()
            stats["errors"] += 1
            logger.exception("billing_cycle: vest failed for credit %s", credit_id)


def _generate(db, today: date, now: datetime, stats: dict) -> None:
    """Step 3: issue the bill for every paid org whose bill date has arrived."""
    orgs = (
        db.query(Organization)
        .filter(
            Organization.tier.in_(PAID_TIER_ORDER),
            Organization.next_billing_date.isnot(None),
            Organization.cancel_at_period_end.is_(False),
            Organization.deleted_at.is_(None),
        )
        .all()
    )
    for org in orgs:
        try:
            issue = ist_date(org.next_billing_date)
            if issue > today:
                continue
            if (org.tier, org.billing_period) not in PURCHASABLE_PLANS:
                # No billing_period: an org that never went through the new
                # checkout (legacy subscription data). Not billable here.
                logger.warning(
                    "billing_cycle: org %s has tier=%s billing_period=%s, skipping",
                    org.id, org.tier, org.billing_period,
                )
                stats["skipped_unbillable"] += 1
                continue
            if org.billing_country is None:
                # A paid org always has its currency locked by its first
                # checkout. One without is bad data: never bill it in a
                # currency nobody chose.
                logger.warning(
                    "billing_cycle: org %s is on a paid plan with no billing country, skipping",
                    org.id,
                )
                stats["skipped_unbillable"] += 1
                continue

            if org.pending_tier or org.pending_period:
                _apply_pending(org, db, now)

            next_issue = next_bill_date_after_issue(issue, org.billing_period)
            exists = (
                db.query(Bill.id)
                .filter(Bill.org_id == org.id, Bill.period_start == issue)
                .first()
            )
            if exists is None:
                bill = Bill(
                    org_id=org.id,
                    org_name_snapshot=org.company_name,
                    tier=org.tier,
                    period=org.billing_period,
                    period_start=issue,
                    period_end=next_issue,
                    amount_paise=plan_price(org.billing_currency, org.tier, org.billing_period),
                    currency=org.billing_currency,
                    status="open",
                    issued_at=now,
                    due_date=due_date_for(issue),
                    cancel_on=cancel_on_for(issue),
                )
                db.add(bill)
                db.flush()
                if apply_credits_to_bill(db, org, bill, now) > 0:
                    stats["credits_applied"] += 1
                stats["bills_issued"] += 1
            else:
                logger.warning(
                    "billing_cycle: bill for org %s period %s already exists, advancing date only",
                    org.id, issue,
                )
            org.next_billing_date = ist_midnight(next_issue)
            db.commit()
        except Exception:
            db.rollback()
            stats["errors"] += 1
            logger.exception("billing_cycle: generate failed for org %s", org.id)


def _remind(db, today: date, now: datetime, stats: dict) -> None:
    """Step 4: send each reminder once per bill, guarded by its *_sent_at.
    The emails are queued only after the *_sent_at columns are committed, so a
    rolled back bill never leaves an email behind and never sends twice."""
    bills = (
        db.query(Bill)
        .filter(Bill.status == "open", Bill.cancel_on > today, Bill.org_id.isnot(None))
        .all()
    )
    for bill in bills:
        try:
            org = db.get(Organization, bill.org_id)
            if org is None or org.deleted_at is not None or org.tier == "starter":
                continue
            routine = bool(org.billing_reminders_enabled)
            to_send: list[str] = []

            if routine and bill.ready_notified_at is None:
                to_send.append("ready")
                bill.ready_notified_at = now
                stats["ready_notices"] += 1

            if (
                routine
                and bill.due_reminder_sent_at is None
                and due_reminder_date_for(bill.due_date) <= today < bill.due_date
            ):
                to_send.append("due_in_3")
                bill.due_reminder_sent_at = now
                stats["due_reminders"] += 1

            if (
                bill.cancel_reminder_sent_at is None
                and cancel_reminder_date_for(bill.cancel_on) <= today
            ):
                to_send.append("cancel_in_3")
                bill.cancel_reminder_sent_at = now
                stats["cancel_reminders"] += 1

            db.commit()
            for kind in to_send:
                notify(kind, org, bill)
        except Exception:
            db.rollback()
            stats["errors"] += 1
            logger.exception("billing_cycle: reminders failed for bill %s", bill.id)


def _announce_overdue(db, today: date) -> None:
    """Step 5 (Phase 11): tell PostHog once per bill when it is past its due
    date and still unpaid. Reads state only and never changes a bill, so a
    failure here is logged and ignored."""
    if not analytics.enabled():
        return
    bills = (
        db.query(Bill)
        .filter(Bill.status == "open", Bill.due_date < today, Bill.org_id.isnot(None))
        .all()
    )
    for bill in bills:
        try:
            org = db.get(Organization, bill.org_id)
            if org is None or org.deleted_at is not None or org.tier == "starter":
                continue
            analytics.capture_org_event_once(
                db, org.id, "bill_overdue", f"bill_overdue:{bill.id}",
                {
                    "tier": bill.tier,
                    "period": bill.period,
                    "amount": analytics.major_units(bill.amount_paise),
                    "currency": bill.currency,
                    "due_date": bill.due_date.isoformat(),
                    "cancel_on": bill.cancel_on.isoformat(),
                },
            )
        except Exception:
            logger.exception("billing_cycle: overdue event failed for bill %s", bill.id)


def run_billing_cycle(db, today: date, now: datetime | None = None) -> dict:
    """Run one daily billing pass as of the IST date `today`. `now` is the
    wall-clock instant used for timestamps (defaults to the current time).
    Returns a dict of counters."""
    moment = now if now is not None else datetime.now(timezone.utc)
    stats = {
        "nonpayment_downgrades": 0,
        "cancellations": 0,
        "bills_issued": 0,
        "skipped_unbillable": 0,
        "ready_notices": 0,
        "due_reminders": 0,
        "cancel_reminders": 0,
        "credits_vested": 0,
        "credits_held": 0,
        "credits_applied": 0,
        "errors": 0,
    }
    _enforce(db, today, moment, stats)
    _voluntary_cancel(db, today, moment, stats)
    _vest_credits(db, moment, stats)
    _generate(db, today, moment, stats)
    _remind(db, today, moment, stats)
    _announce_overdue(db, today)
    logger.info("billing_cycle %s: %s", today, stats)
    return stats


@celery_app.task(name="workers.tasks.billing_cycle.billing_cycle")
def billing_cycle() -> dict:
    db = SessionLocal()
    try:
        stats = run_billing_cycle(db, today_ist())
    except Exception:
        ping_heartbeat("BILLING_HEARTBEAT_URL", failed=True)
        raise
    finally:
        db.close()
    # Better Stack heartbeat: a green ping only when the whole pass ran clean,
    # a /fail ping when any org errored. Never fails the task.
    ping_heartbeat("BILLING_HEARTBEAT_URL", failed=stats["errors"] > 0)
    return stats
