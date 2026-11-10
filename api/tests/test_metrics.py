"""Phase 6 metrics: the daily snapshot is computed per currency from real rows.

The scenario below is small enough to total by hand. All times are fixed
(now = 2026-06-15 10:00 UTC = 15:30 IST), so the "this month" window is
2026-06-01 IST onward. Amounts are minor units from api.tiers.PLAN_PRICES.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from api.metrics import (
    COMBINED_CSV_COLUMNS, CSV_HEADER, MONEY_COLUMNS, SNAPSHOT_COLUMNS, _to_inr_minor, combine,
    combine_by_date, compute_snapshot, csv_row, derive, rate_text, reporting_rate, row_to_dict,
    store_snapshot,
)
from api.tests.billing_testkit import make_org
from api.tests.conftest import make_bill
from db.models import BillingEvent, Client, MetricsDaily

NOW = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
FIRST_CHARGE = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _utc(month: int, day: int) -> datetime:
    return datetime(2026, month, day, 12, 0, tzinfo=timezone.utc)


def _event(db, org, event, from_tier, to_tier, period, when, currency="INR"):
    db.add(BillingEvent(
        org_id=org.id, event=event, from_tier=from_tier, to_tier=to_tier,
        period=period, currency=currency, created_at=when,
    ))


def _paying(db, name, tier, period, currency="INR", **extra):
    return make_org(
        db, tier=tier, period=period, name=name, billing_currency=currency,
        billing_country="IN" if currency == "INR" else "US",
        first_charged_at=FIRST_CHARGE, **extra,
    )


def seed(db):
    # INR
    a = _paying(db, "A", "basic", "monthly")
    _event(db, a, "first_paid", None, "basic", "monthly", _utc(4, 10))
    b = _paying(db, "B", "growth", "annual")
    _event(db, b, "first_paid", None, "growth", "annual", _utc(6, 3))
    c = make_org(db, tier="starter", period=None, name="C", first_charged_at=FIRST_CHARGE)
    _event(db, c, "first_paid", None, "pro", "monthly", _utc(3, 5))
    _event(db, c, "cancelled", "pro", "starter", "monthly", _utc(6, 10))
    d = _paying(db, "D", "growth", "monthly", pilot_code_used="CLEW-DDDDD")
    _event(db, d, "first_paid", None, "basic", "monthly", _utc(4, 20))
    _event(db, d, "upgraded", "basic", "growth", "monthly", _utc(6, 5))
    f = _paying(db, "F", "basic", "monthly", deleted_at=_utc(6, 12))
    _event(db, f, "first_paid", None, "basic", "monthly", _utc(4, 15))
    # Pilots are never revenue.
    make_org(
        db, tier="growth", period=None, name="P", billing_provider="pilot",
        pilot_code_used="CLEW-PPPPP", trial_ends_at=NOW + timedelta(days=10),
    )
    make_org(
        db, tier="starter", period=None, name="E", billing_provider="pilot",
        pilot_code_used="CLEW-EEEEE", trial_ends_at=NOW - timedelta(days=3),
    )
    # USD
    g = _paying(db, "G", "pro", "monthly", currency="USD")
    _event(db, g, "first_paid", None, "pro", "monthly", _utc(5, 10), currency="USD")
    h = _paying(db, "H", "basic", "annual", currency="USD")
    _event(db, h, "first_paid", None, "basic", "annual", _utc(6, 2), currency="USD")

    # One overdue bill and one not yet due, both on A.
    make_bill(db, a, start=date(2026, 5, 25))
    make_bill(db, a, start=date(2026, 6, 1))

    db.add_all([
        Client(email="u1@x.test", full_name="U1", email_verified=True),
        Client(email="u2@x.test", full_name="U2", email_verified=True),
        Client(email="u3@x.test", full_name="U3", email_verified=False),
        Client(email="gone@x.test", full_name="Gone", deleted_at=_utc(6, 1)),
    ])
    db.commit()


def _by_currency(rows):
    return {row["currency"]: row for row in rows}


def test_inr_row_matches_hand_totals(db):
    seed(db)
    inr = _by_currency(compute_snapshot(db, NOW))["INR"]
    assert inr["snapshot_date"] == date(2026, 6, 15)
    assert (inr["users_total"], inr["users_verified"]) == (3, 2)
    assert inr["orgs_total"] == 8  # F is deleted
    assert (inr["active_pilots"], inr["pilots_converted"], inr["pilots_expired_unpaid"]) == (1, 1, 1)
    # Paying: A starter monthly, B growth annual, D growth monthly. The pilot is not revenue.
    assert inr["paying_orgs"] == 3
    assert (inr["paying_basic"], inr["paying_growth"], inr["paying_pro"]) == (1, 2, 0)
    assert inr["mrr_minor"] == 199_900 + 249_950 + 499_900
    assert inr["arr_minor"] == inr["mrr_minor"] * 12
    # Start of month: A, C, D and F were paying.
    assert inr["paying_orgs_start"] == 4
    assert inr["mrr_start_minor"] == 199_900 + 999_900 + 199_900 + 199_900
    assert inr["new_mrr_minor"] == 249_950
    assert inr["expansion_mrr_minor"] == 499_900 - 199_900
    assert inr["contraction_mrr_minor"] == 0
    # C cancelled and F was deleted: both churn.
    assert inr["churned_mrr_minor"] == 999_900 + 199_900
    assert inr["churned_orgs"] == 2
    assert (inr["overdue_bills"], inr["overdue_minor"]) == (1, 199_900)


def test_usd_is_its_own_row_and_never_summed_with_inr(db):
    seed(db)
    rows = compute_snapshot(db, NOW)
    assert [r["currency"] for r in rows] == ["USD", "INR"]
    usd = _by_currency(rows)["USD"]
    assert usd["paying_orgs"] == 2
    assert usd["mrr_minor"] == 24_900 + 2_450
    assert usd["paying_orgs_start"] == 1 and usd["mrr_start_minor"] == 24_900
    assert usd["new_mrr_minor"] == 2_450
    assert usd["churned_mrr_minor"] == 0 and usd["overdue_bills"] == 0


def test_every_row_reconciles(db):
    seed(db)
    for row in compute_snapshot(db, NOW):
        rebuilt = (
            row["mrr_start_minor"] + row["new_mrr_minor"] + row["expansion_mrr_minor"]
            - row["contraction_mrr_minor"] - row["churned_mrr_minor"]
        )
        assert rebuilt == row["mrr_minor"], row["currency"]


def test_derived_ratios(db):
    seed(db)
    inr = _by_currency(compute_snapshot(db, NOW))["INR"]
    out = derive(inr)
    assert out["logo_churn_pct"] == 50.0  # 2 of 4
    assert out["revenue_churn_pct"] == round(1_199_800 * 100 / 1_599_600, 2)
    assert out["arpa_minor"] == round(inr["mrr_minor"] / 3)
    assert out["trial_to_paid_pct"] == 50.0
    empty = derive({**inr, "paying_orgs": 0, "paying_orgs_start": 0, "mrr_start_minor": 0,
                    "pilots_converted": 0, "pilots_expired_unpaid": 0})
    assert empty == {"logo_churn_pct": None, "revenue_churn_pct": None, "arpa_minor": None,
                     "trial_to_paid_pct": None}


def test_empty_database_gives_two_zero_rows(db):
    rows = compute_snapshot(db, NOW)
    assert [r["currency"] for r in rows] == ["USD", "INR"]
    assert all(r[c] == 0 for r in rows for c in SNAPSHOT_COLUMNS)


def test_store_snapshot_is_idempotent_for_a_day(db):
    seed(db)
    store_snapshot(db, compute_snapshot(db, NOW))
    db.commit()
    make_org(db, name="late", tier="starter", period=None)
    store_snapshot(db, compute_snapshot(db, NOW))
    db.commit()
    rows = db.query(MetricsDaily).all()
    assert sorted(r.currency for r in rows) == ["INR", "USD"]
    assert {r.currency: r.orgs_total for r in rows}["INR"] == 9


def test_snapshot_task_stores_rows(db):
    from workers.tasks.metrics_snapshot import run_metrics_snapshot

    seed(db)
    out = run_metrics_snapshot(db)
    assert len(out) == 2
    assert db.query(MetricsDaily).count() == 2
    run_metrics_snapshot(db)
    assert db.query(MetricsDaily).count() == 2


def test_csv_header_has_a_column_per_value():
    assert CSV_HEADER[:2] == ("date", "currency")
    base = 2 + len(SNAPSHOT_COLUMNS) + 4
    # Existing columns keep their order; the rate and combined block come after.
    assert CSV_HEADER[base] == "inr_per_usd"
    assert CSV_HEADER[base + 1:] == COMBINED_CSV_COLUMNS
    assert len(CSV_HEADER) == base + 1 + len(COMBINED_CSV_COLUMNS)


# --- combined INR figures (Phase 7 C) -----------------------------------------------

@pytest.fixture
def rate88(monkeypatch):
    monkeypatch.setenv("METRICS_INR_PER_USD", "88")


@pytest.mark.parametrize("raw", [None, "", "  ", "abc", "0", "-5", "nan", "inf", "0.00001", "99999999"])
def test_rate_missing_or_invalid_is_none(monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv("METRICS_INR_PER_USD", raising=False)
    else:
        monkeypatch.setenv("METRICS_INR_PER_USD", raw)
    assert reporting_rate() is None


def test_rate_parses_to_four_places(monkeypatch):
    monkeypatch.setenv("METRICS_INR_PER_USD", " 88 ")
    assert reporting_rate() == Decimal("88.0000") and rate_text(reporting_rate()) == "88"
    monkeypatch.setenv("METRICS_INR_PER_USD", "83.12345")
    assert reporting_rate() == Decimal("83.1235") and rate_text(reporting_rate()) == "83.1235"
    assert rate_text(None) is None


def test_combined_matches_hand_totals_and_excludes_pilots(db, rate88):
    seed(db)
    rows = compute_snapshot(db, NOW)
    combined = combine(rows)
    inr, usd = (_by_currency(rows)[c] for c in ("INR", "USD"))
    assert combined["currency"] == "INR" and combined["inr_per_usd"] == Decimal("88")
    # INR paise + USD cents x 88.
    assert combined["mrr_minor"] == 949_750 + 27_350 * 88 == 3_356_550
    assert combined["arr_minor"] == combined["mrr_minor"] * 12
    assert combined["mrr_start_minor"] == 1_599_600 + 24_900 * 88
    assert combined["new_mrr_minor"] == 249_950 + 2_450 * 88
    assert combined["churned_mrr_minor"] == 1_199_800
    assert combined["overdue_minor"] == 199_900
    # Counts add; the two pilots are in neither.
    assert combined["paying_orgs"] == inr["paying_orgs"] + usd["paying_orgs"] == 5
    assert combined["paying_orgs_start"] == 5 and combined["churned_orgs"] == 2
    # Global figures are shown once, not doubled.
    assert combined["users_total"] == 3 and combined["active_pilots"] == 1
    ratios = derive(combined)
    assert ratios["arpa_minor"] == round(combined["mrr_minor"] / 5)
    assert ratios["logo_churn_pct"] == 40.0
    # The per-currency rows are untouched by combining.
    assert inr["mrr_minor"] == 949_750 and usd["mrr_minor"] == 27_350


def test_combined_reconciles_within_rounding(db, monkeypatch):
    monkeypatch.setenv("METRICS_INR_PER_USD", "83.3333")
    seed(db)
    c = combine(compute_snapshot(db, NOW))
    rebuilt = (
        c["mrr_start_minor"] + c["new_mrr_minor"] + c["expansion_mrr_minor"]
        - c["contraction_mrr_minor"] - c["churned_mrr_minor"]
    )
    assert abs(rebuilt - c["mrr_minor"]) <= 2


def test_conversion_rounds_once_half_up():
    assert _to_inr_minor(0, 1, Decimal("88.5")) == 89  # 88.5 paise
    assert _to_inr_minor(0, 1, Decimal("88.4999")) == 88
    # One rounding on the sum, not one per part: 1 + 249.9999 -> 251.
    assert _to_inr_minor(1, 3, Decimal("83.3333")) == 251
    assert _to_inr_minor(7, 0, Decimal("88")) == 7


def test_usd_only_and_inr_only_days(db, rate88):
    seed(db)
    rows = _by_currency(compute_snapshot(db, NOW))
    usd_only = combine([rows["USD"]])
    assert usd_only["mrr_minor"] == 27_350 * 88 and usd_only["paying_orgs"] == 2
    inr_only = combine([rows["INR"]])
    assert inr_only["mrr_minor"] == 949_750 and inr_only["paying_orgs"] == 3
    assert combine([]) is None


def test_missing_rate_leaves_per_currency_alone(db, monkeypatch):
    monkeypatch.delenv("METRICS_INR_PER_USD", raising=False)
    seed(db)
    rows = compute_snapshot(db, NOW)
    assert all(r["inr_per_usd"] is None for r in rows)
    assert combine(rows) is None
    assert _by_currency(rows)["INR"]["mrr_minor"] == 949_750
    store_snapshot(db, rows)
    db.commit()
    stored = [row_to_dict(r) for r in db.query(MetricsDaily).all()]
    assert all(r["inr_per_usd"] is None for r in stored)
    assert list(combine_by_date(stored).values()) == [None]


def test_rate_is_stored_per_row_and_past_days_keep_theirs(db, monkeypatch):
    seed(db)
    monkeypatch.setenv("METRICS_INR_PER_USD", "88")
    store_snapshot(db, compute_snapshot(db, NOW))
    db.commit()
    monkeypatch.setenv("METRICS_INR_PER_USD", "90")
    store_snapshot(db, compute_snapshot(db, NOW + timedelta(days=1)))
    db.commit()
    by_date = combine_by_date([row_to_dict(r) for r in db.query(MetricsDaily).all()])
    assert by_date[date(2026, 6, 15)]["inr_per_usd"] == Decimal("88")
    assert by_date[date(2026, 6, 16)]["inr_per_usd"] == Decimal("90")
    # Same USD figure, different stored rate: the old day did not move.
    assert by_date[date(2026, 6, 15)]["mrr_minor"] == 949_750 + 27_350 * 88
    assert by_date[date(2026, 6, 16)]["mrr_minor"] == 949_750 + 27_350 * 90
    # Re-running the same day with a new rate updates that day only.
    store_snapshot(db, compute_snapshot(db, NOW))
    db.commit()
    again = combine_by_date([row_to_dict(r) for r in db.query(MetricsDaily).all()])
    assert again[date(2026, 6, 15)]["inr_per_usd"] == Decimal("90")


def test_csv_row_carries_rate_and_combined_block(db, rate88):
    seed(db)
    rows = compute_snapshot(db, NOW)
    combined = combine(rows)
    inr = _by_currency(rows)["INR"]
    cells = csv_row(inr, combined)
    assert len(cells) == len(CSV_HEADER)
    assert cells[CSV_HEADER.index("mrr_minor")] == "9497.50"  # per-currency untouched
    assert cells[CSV_HEADER.index("inr_per_usd")] == "88"
    assert cells[CSV_HEADER.index("combined_mrr_minor")] == "33565.50"
    assert cells[CSV_HEADER.index("combined_paying_orgs")] == 5
    blank = csv_row(inr, None)
    assert len(blank) == len(CSV_HEADER)
    assert blank[CSV_HEADER.index("inr_per_usd")] == "88"
    assert all(c == "" for c in blank[CSV_HEADER.index("combined_mrr_minor"):])
    assert set(MONEY_COLUMNS) == {c[len("combined_"):] for c in COMBINED_CSV_COLUMNS[:len(MONEY_COLUMNS)]}
