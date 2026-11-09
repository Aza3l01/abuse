"""api/billing_rules.py: Phase 3 billing date and amount rules.

Every function here is pure: dates (or a `now`) are passed in, nothing reads
the clock or the database unless it is `today_ist()` called with no argument.
The daily engine (workers/tasks/billing_cycle.py) and the Phase 4 payment
flow both build on these, so a rule lives in exactly one place.

Rules (TODO.md section 3.3 and assumptions 1 to 5, 9):
  - All calendar rules are evaluated in IST (Asia/Kolkata, a fixed UTC+05:30
    offset with no daylight saving, so a plain offset is exact).
  - First purchase paid on day 1 to 15 of month M: next bill on the 1st of
    M+1. Paid on day 16 or later: the 1st of M+2. Annual adds 12 months.
  - A bill is issued on the 1st, due the 20th of the same month, and an
    unpaid bill cancels the plan on the 1st of the next month.
  - Reminders: "due in 3 days" on the 17th, "cancels in 3 days" on
    cancel_on minus 3 days.
  - Upgrade: pay the flat price difference now (same period type), or the
    full annual price when switching monthly to annual.
  - Restore: every open bill plus one new period.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from api.tiers import PAID_TIER_ORDER, PURCHASABLE_PLANS, plan_price

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

PERIODS = ("monthly", "annual")

# Bills are due on this day of the issue month.
DUE_DAY = 20
# A payment made on or before this day of the month anchors to the 1st of the
# next month, a later one to the 1st of the month after that.
ANCHOR_CUTOFF_DAY = 15
# Days before due_date / cancel_on that the reminders fire.
REMINDER_LEAD_DAYS = 3
# Length of the retention grace after a downgrade.
RETENTION_GRACE_DAYS = 30


# ---------------------------------------------------------------------------
# Dates and time zone helpers
# ---------------------------------------------------------------------------

def today_ist(now: datetime | None = None) -> date:
    """The current calendar date in IST. `now` is injectable for tests."""
    moment = now if now is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(IST).date()


def ist_midnight(d: date) -> datetime:
    """The instant a calendar date starts in IST, as an aware datetime. This
    is how a bill issue date is stored in Organization.next_billing_date."""
    return datetime(d.year, d.month, d.day, tzinfo=IST)


def ist_date(moment: datetime) -> date:
    """The IST calendar date of a stored instant. A naive datetime is taken as
    UTC (SQLite test databases return naive values; Postgres returns aware)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(IST).date()


def as_utc(moment: datetime) -> datetime:
    """An aware UTC datetime, treating a naive value as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def add_months(d: date, months: int) -> date:
    """Calendar month arithmetic, clamping the day to the target month's
    length (31 Jan + 1 month = 28 or 29 Feb)."""
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _period_months(period: str) -> int:
    if period == "monthly":
        return 1
    if period == "annual":
        return 12
    raise ValueError(f"unknown billing period: {period!r}")


# ---------------------------------------------------------------------------
# Bill dates
# ---------------------------------------------------------------------------

def anchor_for_payment(paid_on: date) -> date:
    """The first monthly bill date after a first purchase: the 1st of the next
    month for a payment on day 1 to 15, the 1st of the month after for day 16
    or later."""
    first_of_month = paid_on.replace(day=1)
    months = 1 if paid_on.day <= ANCHOR_CUTOFF_DAY else 2
    return add_months(first_of_month, months)


def next_bill_date_after_payment(paid_on: date, period: str) -> date:
    """The next bill issue date after a purchase paid on `paid_on`. Annual is
    the monthly anchor plus 12 months (paid Nov 2026, day <= 15: 1 Dec 2027)."""
    anchor = anchor_for_payment(paid_on)
    if period == "monthly":
        return anchor
    if period == "annual":
        return add_months(anchor, 12)
    raise ValueError(f"unknown billing period: {period!r}")


def next_bill_date_after_issue(issue: date, period: str) -> date:
    """The bill date after the one issued on `issue`: +1 month, or +12 months
    for annual."""
    return add_months(issue, _period_months(period))


def due_date_for(issue: date) -> date:
    """A bill is due on the 20th of the month it is issued in."""
    return issue.replace(day=DUE_DAY)


def cancel_on_for(issue: date) -> date:
    """An unpaid bill cancels the plan on the 1st of the month after the one
    it was issued in (annual bills too, assumption 9)."""
    return add_months(issue.replace(day=1), 1)


def due_reminder_date_for(due: date) -> date:
    """The "due in 3 days" reminder date (the 17th for a bill due the 20th)."""
    return due - timedelta(days=REMINDER_LEAD_DAYS)


def cancel_reminder_date_for(cancel_on: date) -> date:
    """The "plan cancels in 3 days" reminder date (28 Nov for a 1 Dec cancel)."""
    return cancel_on - timedelta(days=REMINDER_LEAD_DAYS)


# ---------------------------------------------------------------------------
# Plan changes and amounts
# ---------------------------------------------------------------------------

Plan = tuple[str, str]  # (tier, period)


def classify_change(old: Plan, new: Plan) -> str:
    """Classify a change from `old` to `new` (each a (tier, period) pair) as
    'upgrade', 'downgrade', 'same' or 'unsupported'.

    Both tier and period changing at once is unsupported (assumption 2), and
    so is any plan that is not a purchasable (tier, period) pair. Within one
    period type a dearer tier is an upgrade. Monthly to annual on the same
    tier is an upgrade, annual to monthly a downgrade.
    """
    if old not in PURCHASABLE_PLANS or new not in PURCHASABLE_PLANS:
        return "unsupported"
    if old == new:
        return "same"
    old_tier, old_period = old
    new_tier, new_period = new
    if old_tier != new_tier and old_period != new_period:
        return "unsupported"
    if old_tier == new_tier:
        return "upgrade" if (old_period, new_period) == ("monthly", "annual") else "downgrade"
    old_rank = PAID_TIER_ORDER.index(old_tier)
    new_rank = PAID_TIER_ORDER.index(new_tier)
    return "upgrade" if new_rank > old_rank else "downgrade"


def upgrade_amount_paise(old: Plan, new: Plan, *, currency: str) -> int:
    """Amount to charge now for an upgrade from `old` to `new`, in the minor
    units (paise or cents) of `currency`. The currency is required: an amount
    is never computed without saying which currency it is in.

    - Tier upgrade on a monthly plan: the flat difference between the two
      plan prices (assumption 3). The next bill date does not move.
    - Any upgrade to an annual plan (monthly to annual on the same tier, or
      annual to a higher annual tier): the full price of the new annual plan
      now. Any remaining paid monthly time or remaining old year is forfeited
      and nothing is credited (assumption 4).

    An upgrade is only for a plan that has been paid for, so the caller must
    settle every open bill first (assumption 5); that check is not applied here.

    Raises ValueError when the change is not an upgrade.
    """
    kind = classify_change(old, new)
    if kind != "upgrade":
        raise ValueError(f"not an upgrade: {old} -> {new} is {kind}")
    if new[1] == "annual":
        return plan_price(currency, *new)
    return plan_price(currency, *new) - plan_price(currency, *old)


def restore_amount_paise(open_bills: Iterable, tier: str, period: str, *, currency: str) -> int:
    """Total for the restore checkout after a non-payment downgrade: every
    open bill plus one new period of the chosen plan, in `currency`.
    `open_bills` is any iterable of objects with `amount_paise`, `currency`
    and `status`; only those with status 'open' are counted, and an open bill
    in another currency raises ValueError (the two cannot be added)."""
    plan = (tier, period)
    if plan not in PURCHASABLE_PLANS:
        raise ValueError(f"not a purchasable plan: {plan}")
    open_only = [b for b in open_bills if b.status == "open"]
    if any(b.currency != currency for b in open_only):
        raise ValueError(f"open bills are not all in {currency}")
    owed = sum(b.amount_paise for b in open_only)
    return owed + plan_price(currency, tier, period)


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def effective_retention_tier(org, now: datetime | None = None) -> str:
    """The tier whose data retention applies to `org` right now: its
    `retention_grace_tier` while `retention_grace_until` is in the future,
    otherwise its current `tier`. Used by the purge task and the LTM TTL, so a
    downgraded org keeps its old retention window for the grace period."""
    moment = as_utc(now) if now is not None else datetime.now(timezone.utc)
    grace_tier = getattr(org, "retention_grace_tier", None)
    grace_until = getattr(org, "retention_grace_until", None)
    if grace_tier and grace_until is not None and as_utc(grace_until) > moment:
        return grace_tier
    return org.tier
