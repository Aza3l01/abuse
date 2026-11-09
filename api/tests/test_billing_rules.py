"""Phase 3: pure billing date and amount rules (api/billing_rules.py)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from api.billing_rules import (
    IST,
    add_months,
    anchor_for_payment,
    cancel_on_for,
    cancel_reminder_date_for,
    classify_change,
    due_date_for,
    due_reminder_date_for,
    effective_retention_tier,
    ist_date,
    ist_midnight,
    next_bill_date_after_issue,
    next_bill_date_after_payment,
    restore_amount_paise,
    today_ist,
    upgrade_amount_paise,
)
from api.tiers import plan_price


# --- today_ist and time zone helpers --------------------------------------

def test_today_ist_rolls_over_at_1830_utc():
    assert today_ist(datetime(2026, 11, 30, 18, 29, tzinfo=timezone.utc)) == date(2026, 11, 30)
    assert today_ist(datetime(2026, 11, 30, 18, 30, tzinfo=timezone.utc)) == date(2026, 12, 1)


def test_today_ist_at_the_beat_time_is_the_next_ist_day():
    # Beat fires at 19:00 UTC, which is 00:30 IST the next calendar day.
    assert today_ist(datetime(2026, 11, 30, 19, 0, tzinfo=timezone.utc)) == date(2026, 12, 1)


def test_ist_midnight_round_trips_through_utc_and_naive_storage():
    stored = ist_midnight(date(2026, 12, 1))
    assert stored.astimezone(timezone.utc) == datetime(2026, 11, 30, 18, 30, tzinfo=timezone.utc)
    assert ist_date(stored) == date(2026, 12, 1)
    assert ist_date(stored.astimezone(timezone.utc)) == date(2026, 12, 1)
    # SQLite hands back a naive wall-clock value, taken as UTC.
    assert ist_date(datetime(2026, 12, 1, 0, 0)) == date(2026, 12, 1)


def test_add_months_clamps_and_rolls_the_year():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
    assert add_months(date(2026, 11, 1), 14) == date(2028, 1, 1)


# --- anchor and next bill date --------------------------------------------

@pytest.mark.parametrize(
    "paid_on, expected",
    [
        (date(2026, 11, 1), date(2026, 12, 1)),
        (date(2026, 11, 4), date(2026, 12, 1)),
        (date(2026, 11, 15), date(2026, 12, 1)),   # day 15 is still the early bucket
        (date(2026, 11, 16), date(2027, 1, 1)),    # day 16 is the late bucket
        (date(2026, 11, 20), date(2027, 1, 1)),
        (date(2026, 11, 30), date(2027, 1, 1)),
    ],
)
def test_anchor_day_15_and_16_boundary(paid_on, expected):
    assert anchor_for_payment(paid_on) == expected


@pytest.mark.parametrize(
    "paid_on, expected",
    [
        (date(2026, 1, 31), date(2026, 3, 1)),    # 31-day month, late bucket
        (date(2026, 2, 15), date(2026, 3, 1)),    # 28-day month, early bucket
        (date(2026, 2, 28), date(2026, 4, 1)),    # last day of a 28-day February
        (date(2028, 2, 15), date(2028, 3, 1)),    # leap year
        (date(2028, 2, 29), date(2028, 4, 1)),    # 29-day February, last day
        (date(2026, 4, 30), date(2026, 6, 1)),    # 30-day month, last day
        (date(2026, 3, 1), date(2026, 4, 1)),
    ],
)
def test_anchor_across_month_lengths(paid_on, expected):
    assert anchor_for_payment(paid_on) == expected


@pytest.mark.parametrize(
    "paid_on, expected",
    [
        (date(2026, 12, 1), date(2027, 1, 1)),     # Dec to Jan rollover
        (date(2026, 12, 15), date(2027, 1, 1)),
        (date(2026, 12, 16), date(2027, 2, 1)),    # late Dec skips January
        (date(2026, 12, 31), date(2027, 2, 1)),
    ],
)
def test_anchor_december_rollover(paid_on, expected):
    assert anchor_for_payment(paid_on) == expected


def test_next_bill_date_after_payment_monthly():
    assert next_bill_date_after_payment(date(2026, 11, 4), "monthly") == date(2026, 12, 1)
    assert next_bill_date_after_payment(date(2026, 11, 20), "monthly") == date(2027, 1, 1)


def test_next_bill_date_after_payment_annual():
    # Nov 2026, day <= 15 gives 1 Dec 2027.
    assert next_bill_date_after_payment(date(2026, 11, 4), "annual") == date(2027, 12, 1)
    assert next_bill_date_after_payment(date(2026, 11, 15), "annual") == date(2027, 12, 1)
    assert next_bill_date_after_payment(date(2026, 11, 16), "annual") == date(2028, 1, 1)


def test_next_bill_date_after_payment_rejects_unknown_period():
    with pytest.raises(ValueError):
        next_bill_date_after_payment(date(2026, 11, 4), "weekly")


def test_next_bill_date_after_issue():
    assert next_bill_date_after_issue(date(2026, 12, 1), "monthly") == date(2027, 1, 1)
    assert next_bill_date_after_issue(date(2027, 12, 1), "annual") == date(2028, 12, 1)


# --- due, cancel and reminder dates ---------------------------------------

def test_due_date_is_the_20th_of_the_issue_month():
    assert due_date_for(date(2026, 12, 1)) == date(2026, 12, 20)
    assert due_date_for(date(2027, 2, 1)) == date(2027, 2, 20)


def test_cancel_on_is_the_first_of_the_next_month():
    assert cancel_on_for(date(2026, 11, 1)) == date(2026, 12, 1)
    assert cancel_on_for(date(2026, 12, 1)) == date(2027, 1, 1)   # Dec to Jan
    assert cancel_on_for(date(2027, 2, 1)) == date(2027, 3, 1)


def test_reminder_dates_in_a_normal_month():
    issue = date(2026, 11, 1)
    assert due_reminder_date_for(due_date_for(issue)) == date(2026, 11, 17)
    # 3.3's own example: cancel date 1 December, warning on 28 November.
    assert cancel_reminder_date_for(cancel_on_for(issue)) == date(2026, 11, 28)


def test_reminder_dates_in_february():
    issue = date(2027, 2, 1)   # 28-day February
    assert due_reminder_date_for(due_date_for(issue)) == date(2027, 2, 17)
    assert cancel_reminder_date_for(cancel_on_for(issue)) == date(2027, 2, 26)
    leap = date(2028, 2, 1)    # 29-day February
    assert due_reminder_date_for(due_date_for(leap)) == date(2028, 2, 17)
    assert cancel_reminder_date_for(cancel_on_for(leap)) == date(2028, 2, 27)


def test_cancel_reminder_for_a_january_cancel_is_29_december():
    # 1 January minus 3 days is 29 December (the rule, not 28 December).
    assert cancel_reminder_date_for(cancel_on_for(date(2026, 12, 1))) == date(2026, 12, 29)


# --- classify_change -------------------------------------------------------

@pytest.mark.parametrize(
    "old, new, expected",
    [
        (("starter", "monthly"), ("growth", "monthly"), "upgrade"),
        (("growth", "monthly"), ("pro", "monthly"), "upgrade"),
        (("starter", "monthly"), ("pro", "monthly"), "upgrade"),
        (("pro", "monthly"), ("growth", "monthly"), "downgrade"),
        (("growth", "monthly"), ("starter", "monthly"), "downgrade"),
        (("starter", "annual"), ("growth", "annual"), "upgrade"),
        (("pro", "annual"), ("starter", "annual"), "downgrade"),
        (("growth", "monthly"), ("growth", "annual"), "upgrade"),
        (("growth", "annual"), ("growth", "monthly"), "downgrade"),
        (("growth", "monthly"), ("growth", "monthly"), "same"),
        (("pro", "annual"), ("pro", "annual"), "same"),
    ],
)
def test_classify_change(old, new, expected):
    assert classify_change(old, new) == expected


@pytest.mark.parametrize(
    "old, new",
    [
        (("starter", "monthly"), ("growth", "annual")),    # tier and period at once
        (("pro", "annual"), ("starter", "monthly")),
        (("free", None), ("starter", "monthly")),          # not a change, a first purchase
        (("starter", "monthly"), ("enterprise", "monthly")),
        (("starter", "monthly"), ("free", None)),
        (("starter", "weekly"), ("growth", "weekly")),
    ],
)
def test_classify_change_unsupported(old, new):
    assert classify_change(old, new) == "unsupported"


# --- upgrade_amount_paise --------------------------------------------------

def test_tier_upgrade_pays_the_flat_difference():
    assert upgrade_amount_paise(("starter", "monthly"), ("growth", "monthly"), currency="INR") == 499900 - 199900
    assert upgrade_amount_paise(("growth", "monthly"), ("pro", "monthly"), currency="INR") == 999900 - 499900
    assert upgrade_amount_paise(("starter", "monthly"), ("pro", "monthly"), currency="INR") == 999900 - 199900


def test_tier_upgrade_in_usd_pays_the_flat_difference_in_cents():
    assert upgrade_amount_paise(("starter", "monthly"), ("growth", "monthly"), currency="USD") == 12900 - 4900
    assert upgrade_amount_paise(("starter", "monthly"), ("pro", "monthly"), currency="USD") == 24900 - 4900


def test_annual_tier_upgrade_pays_the_full_new_annual_price():
    assert upgrade_amount_paise(("growth", "annual"), ("pro", "annual"), currency="INR") == 5999400
    assert upgrade_amount_paise(("growth", "annual"), ("pro", "annual"), currency="USD") == 149400


def test_monthly_to_annual_pays_the_full_annual_price():
    for tier in ("starter", "growth", "pro"):
        for currency in ("INR", "USD"):
            assert (
                upgrade_amount_paise((tier, "monthly"), (tier, "annual"), currency=currency)
                == plan_price(currency, tier, "annual")
            )


@pytest.mark.parametrize(
    "old, new",
    [
        (("growth", "monthly"), ("starter", "monthly")),
        (("growth", "monthly"), ("growth", "monthly")),
        (("starter", "monthly"), ("growth", "annual")),
    ],
)
def test_upgrade_amount_rejects_non_upgrades(old, new):
    with pytest.raises(ValueError):
        upgrade_amount_paise(old, new, currency="INR")


def test_upgrade_amount_needs_a_known_currency():
    with pytest.raises(ValueError):
        upgrade_amount_paise(("starter", "monthly"), ("growth", "monthly"), currency="EUR")


# --- restore_amount_paise --------------------------------------------------

def _bill(amount, status="open", currency="INR"):
    return SimpleNamespace(amount_paise=amount, status=status, currency=currency)


def test_restore_is_open_bills_plus_a_new_period():
    # Basic with one missed month: 2x Basic.
    assert restore_amount_paise([_bill(199900)], "starter", "monthly", currency="INR") == 2 * 199900


def test_restore_in_usd():
    assert restore_amount_paise([_bill(4900, currency="USD")], "starter", "monthly", currency="USD") == 2 * 4900


def test_restore_rejects_a_mixed_currency_open_bill_set():
    with pytest.raises(ValueError):
        restore_amount_paise([_bill(199900), _bill(4900, currency="USD")], "starter", "monthly", currency="INR")


def test_restore_sums_several_open_bills_and_ignores_paid_ones():
    bills = [_bill(199900), _bill(199900), _bill(199900, "paid"), _bill(199900, "void")]
    assert restore_amount_paise(bills, "starter", "monthly", currency="INR") == 3 * 199900


def test_restore_can_choose_a_different_plan_for_the_new_period():
    assert restore_amount_paise([_bill(199900)], "growth", "annual", currency="INR") == 199900 + 2999400


def test_restore_with_no_open_bills_is_just_the_new_period():
    assert restore_amount_paise([], "pro", "monthly", currency="INR") == 999900


def test_restore_rejects_an_unpurchasable_plan():
    with pytest.raises(ValueError):
        restore_amount_paise([], "enterprise", "monthly", currency="INR")


# --- effective_retention_tier ---------------------------------------------

_NOW = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)


def _org(**kw):
    base = dict(tier="free", retention_grace_tier=None, retention_grace_until=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_grace_tier_applies_while_the_grace_is_in_the_future():
    org = _org(retention_grace_tier="starter", retention_grace_until=_NOW + timedelta(days=1))
    assert effective_retention_tier(org, _NOW) == "starter"


def test_current_tier_applies_once_the_grace_has_ended():
    org = _org(retention_grace_tier="starter", retention_grace_until=_NOW)
    assert effective_retention_tier(org, _NOW) == "free"
    org = _org(retention_grace_tier="starter", retention_grace_until=_NOW - timedelta(seconds=1))
    assert effective_retention_tier(org, _NOW) == "free"


def test_current_tier_applies_when_there_is_no_grace():
    assert effective_retention_tier(_org(tier="growth"), _NOW) == "growth"
    assert effective_retention_tier(_org(retention_grace_until=_NOW + timedelta(days=5)), _NOW) == "free"


def test_naive_grace_datetime_is_read_as_utc():
    org = _org(retention_grace_tier="pro", retention_grace_until=datetime(2026, 12, 2, 0, 0))
    assert effective_retention_tier(org, _NOW) == "pro"


def test_ist_constant_is_plus_0530():
    assert IST.utcoffset(None) == timedelta(hours=5, minutes=30)
