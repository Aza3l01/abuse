"""api/metrics.py: Phase 6 business metrics, computed from Postgres only.

Definitions (TODO.md assumption 11, confirmed by the founder):
  - Paying org: tier basic, growth or pro, billed through Razorpay, with a
    billing_period and a first captured payment, not deleted. Pilots, starter
    (free) and
    enterprise orgs are not paying.
  - MRR: monthly plans at list price, annual plans at list price / 12, excluding
    GST, from PLAN_PRICES in the org's billing currency. ARR = MRR x 12.
  - The month is the IST calendar month containing `now`, to date.
  - Movement comes from BillingEvent: new = first_paid + restored; expansion
    and contraction = upgraded and downgraded (by MRR change); churned =
    cancelled + nonpayment_downgrade + refunded, plus paying orgs whose account
    was deleted in the month. trial_end is not churn (it never paid).
  - Logo churn = paying orgs at month start that were lost in the month /
    paying orgs at month start. Revenue churn = churned MRR / MRR at month
    start. ARPA = MRR / paying orgs. A refunded first payment is churn.
  - Trial to paid = pilots that paid / (pilots that paid + pilots that expired
    unpaid), cumulative.
  - Every money figure is per currency and the per-currency figures are never
    altered. A separate combined block (INR headline) adds USD to INR at a
    fixed reporting rate, METRICS_INR_PER_USD (INR per 1 USD), which is stored
    on every metrics_daily row so a past day keeps the rate it was computed
    with. It is a reporting figure, not accounting. USD minor units (cents)
    convert to INR minor units (paise) as cents x rate, with ONE rounding step
    (half up) per figure at the end. Because of that single rounding, a
    combined movement can differ from the combined MRR by a paisa or two.
    Missing, non-numeric or non-positive rate: no combined figures, the
    per-currency figures are unaffected. Pilots are excluded, as everywhere.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from api.billing_rules import as_utc, ist_midnight, today_ist
from api.tiers import CURRENCIES, PAID_TIER_ORDER, PLAN_PRICES
from db.models import Bill, BillingEvent, Client, MetricsDaily, Organization

_CHURN_EVENTS = {"cancelled", "nonpayment_downgrade", "refunded"}
_PLAN_EVENTS = {"first_paid", "restored", "upgraded", "downgraded"}

MONEY_COLUMNS = (
    "mrr_minor", "arr_minor", "mrr_start_minor", "new_mrr_minor", "expansion_mrr_minor",
    "contraction_mrr_minor", "churned_mrr_minor", "refunds_minor", "overdue_minor",
)

SNAPSHOT_COLUMNS = (
    "users_total", "users_verified", "orgs_total", "active_pilots", "pilots_converted",
    "pilots_expired_unpaid", "paying_orgs", "paying_basic", "paying_growth", "paying_pro",
    "mrr_minor", "arr_minor", "paying_orgs_start", "mrr_start_minor", "new_mrr_minor",
    "expansion_mrr_minor", "contraction_mrr_minor", "churned_mrr_minor", "churned_orgs",
    "refunds_count", "refunds_minor", "overdue_bills", "overdue_minor",
)


HEADLINE_CURRENCY = "INR"

# Counts that add across currencies (an org belongs to exactly one currency).
_SUMMED_COUNTS = (
    "paying_orgs", "paying_basic", "paying_growth", "paying_pro", "paying_orgs_start",
    "churned_orgs", "refunds_count", "overdue_bills",
)

_RATE_QUANTUM = Decimal("0.0001")
_RATE_MAX = Decimal("1000000")


def reporting_rate() -> Decimal | None:
    """INR per 1 USD from METRICS_INR_PER_USD, to 4 decimal places. None when the
    variable is missing, not a number, or not a positive finite number."""
    return parse_rate(os.environ.get("METRICS_INR_PER_USD", ""))


def parse_rate(raw: str | None) -> Decimal | None:
    """A rate as text to a 4 decimal place Decimal. None when empty, not a number,
    or not a positive finite number."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        rate = Decimal(raw)
    except InvalidOperation:
        return None
    if not rate.is_finite() or rate <= 0 or rate >= _RATE_MAX:
        return None
    rate = rate.quantize(_RATE_QUANTUM, rounding=ROUND_HALF_UP)
    return rate if rate > 0 else None


def with_rate(rows: list[dict], rate: Decimal) -> list[dict]:
    """Copies of the rows with one rate on all of them (a rate entered by staff
    replaces the stored one for the view; nothing is written to the database)."""
    return [{**row, "inr_per_usd": rate} for row in rows]


def rate_text(rate: Decimal | None) -> str | None:
    """The rate as a plain decimal string without trailing zeros (88.0000 -> '88')."""
    return None if rate is None else format(rate.normalize(), "f")


def plan_mrr(currency: str, tier: str | None, period: str | None) -> int:
    """MRR of one org on a plan, in minor units. 0 for a plan with no price."""
    price = PLAN_PRICES.get((currency, tier, period))
    if price is None:
        return 0
    return round(price / 12) if period == "annual" else price


def _old_period(event: BillingEvent) -> str | None:
    """The period before an upgraded or downgraded event. A change never moves
    tier and period together, so a same-tier change is the monthly/annual switch
    (upgrade: monthly to annual, scheduled downgrade: annual to monthly)."""
    if event.from_tier == event.to_tier:
        return "monthly" if event.event == "upgraded" else "annual"
    return event.period


def compute_snapshot(db, now: datetime | None = None) -> list[dict]:
    """One dict per currency in CURRENCIES, keyed by the MetricsDaily columns."""
    moment = as_utc(now) if now is not None else datetime.now(timezone.utc)
    today = today_ist(moment)
    month_start = ist_midnight(today.replace(day=1))
    rate = reporting_rate()

    orgs = db.query(Organization).all()
    live = [o for o in orgs if o.deleted_at is None]
    currency_of = {o.id: o.billing_currency for o in orgs}
    deleted_at = {o.id: as_utc(o.deleted_at) for o in orgs if o.deleted_at is not None}

    clients = db.query(Client).filter(Client.deleted_at.is_(None)).all()
    users_total = len(clients)
    users_verified = sum(1 for c in clients if c.email_verified)

    active_pilots = sum(
        1 for o in live
        if o.billing_provider == "pilot" and o.trial_ends_at is not None and as_utc(o.trial_ends_at) > moment
    )
    pilots_converted = sum(1 for o in live if o.pilot_code_used and o.first_charged_at is not None)
    pilots_expired_unpaid = sum(
        1 for o in live
        if o.pilot_code_used and o.first_charged_at is None
        and o.trial_ends_at is not None and as_utc(o.trial_ends_at) <= moment
    )

    events = (
        db.query(BillingEvent)
        .filter(BillingEvent.org_id.isnot(None))
        .order_by(BillingEvent.created_at, BillingEvent.id)
        .all()
    )

    # Plan each org was paying for, or None, as the events replay in time order.
    state: dict[str, tuple[str, str] | None] = {}

    def apply(event: BillingEvent) -> None:
        if event.event in _PLAN_EVENTS:
            state[event.org_id] = (event.to_tier, event.period)
        elif event.event in _CHURN_EVENTS or event.event == "trial_end":
            state[event.org_id] = None

    before = [e for e in events if as_utc(e.created_at) < month_start]
    during = [e for e in events if as_utc(e.created_at) >= month_start]
    for event in before:
        apply(event)
    start_state = {
        org_id: plan for org_id, plan in state.items()
        if plan is not None and not (org_id in deleted_at and deleted_at[org_id] < month_start)
    }

    rows = {
        currency: {
            "new": 0, "expansion": 0, "contraction": 0, "churned": 0,
            "refunds_count": 0, "refunds_minor": 0, "lost": set(),
        }
        for currency in CURRENCIES
    }

    for event in during:
        currency = currency_of.get(event.org_id)
        if currency not in rows:
            continue
        bucket = rows[currency]
        if event.event in ("first_paid", "restored"):
            bucket["new"] += plan_mrr(currency, event.to_tier, event.period)
        elif event.event in ("upgraded", "downgraded"):
            delta = plan_mrr(currency, event.to_tier, event.period) - plan_mrr(
                currency, event.from_tier, _old_period(event)
            )
            if delta > 0:
                bucket["expansion"] += delta
            else:
                bucket["contraction"] += -delta
        elif event.event in _CHURN_EVENTS:
            bucket["churned"] += plan_mrr(currency, event.from_tier, event.period)
            if event.org_id in start_state:
                bucket["lost"].add(event.org_id)
            if event.event == "refunded":
                bucket["refunds_count"] += 1
                bucket["refunds_minor"] += event.amount_paise or 0
        apply(event)

    # A paying org whose account was deleted in the month is churn too, at its
    # MRR when it went (the delete itself writes no BillingEvent).
    for org_id, plan in state.items():
        if plan is None or org_id not in deleted_at or deleted_at[org_id] < month_start:
            continue
        currency = currency_of.get(org_id)
        if currency not in rows:
            continue
        rows[currency]["churned"] += plan_mrr(currency, *plan)
        if org_id in start_state:
            rows[currency]["lost"].add(org_id)

    overdue = (
        db.query(Bill)
        .filter(Bill.status == "open", Bill.due_date < today)
        .all()
    )

    out: list[dict] = []
    for currency in CURRENCIES:
        paying = [
            o for o in live
            if o.billing_currency == currency
            and o.tier in PAID_TIER_ORDER
            and o.billing_provider == "razorpay"
            and o.billing_period is not None
            and o.first_charged_at is not None
        ]
        mrr = sum(plan_mrr(currency, o.tier, o.billing_period) for o in paying)
        start_here = {oid: plan for oid, plan in start_state.items() if currency_of.get(oid) == currency}
        bucket = rows[currency]
        late = [b for b in overdue if b.currency == currency]
        out.append({
            "snapshot_date": today,
            "currency": currency,
            "users_total": users_total,
            "users_verified": users_verified,
            "orgs_total": len(live),
            "active_pilots": active_pilots,
            "pilots_converted": pilots_converted,
            "pilots_expired_unpaid": pilots_expired_unpaid,
            "paying_orgs": len(paying),
            "paying_basic": sum(1 for o in paying if o.tier == "basic"),
            "paying_growth": sum(1 for o in paying if o.tier == "growth"),
            "paying_pro": sum(1 for o in paying if o.tier == "pro"),
            "mrr_minor": mrr,
            "arr_minor": mrr * 12,
            "paying_orgs_start": len(start_here),
            "mrr_start_minor": sum(plan_mrr(currency, *plan) for plan in start_here.values()),
            "new_mrr_minor": bucket["new"],
            "expansion_mrr_minor": bucket["expansion"],
            "contraction_mrr_minor": bucket["contraction"],
            "churned_mrr_minor": bucket["churned"],
            "churned_orgs": len(bucket["lost"]),
            "refunds_count": bucket["refunds_count"],
            "refunds_minor": bucket["refunds_minor"],
            "overdue_bills": len(late),
            "overdue_minor": sum(b.amount_paise for b in late),
            "inr_per_usd": rate,
        })
    return out


def _pct(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100 / denominator, 2) if denominator else None


def derive(row: dict) -> dict:
    """Ratios derived from a snapshot row's counts. None when the denominator is 0."""
    converted = row["pilots_converted"]
    return {
        "logo_churn_pct": _pct(row["churned_orgs"], row["paying_orgs_start"]),
        "revenue_churn_pct": _pct(row["churned_mrr_minor"], row["mrr_start_minor"]),
        "arpa_minor": round(row["mrr_minor"] / row["paying_orgs"]) if row["paying_orgs"] else None,
        "trial_to_paid_pct": _pct(converted, converted + row["pilots_expired_unpaid"]),
    }


def store_snapshot(db, rows: list[dict]) -> None:
    """Insert or update the day's rows (one per currency). Does not commit."""
    for data in rows:
        existing = (
            db.query(MetricsDaily)
            .filter(MetricsDaily.snapshot_date == data["snapshot_date"], MetricsDaily.currency == data["currency"])
            .first()
        )
        if existing is None:
            db.add(MetricsDaily(**data))
        else:
            for column in SNAPSHOT_COLUMNS:
                setattr(existing, column, data[column])
            existing.inr_per_usd = data["inr_per_usd"]


def row_to_dict(row: MetricsDaily) -> dict:
    data = {"snapshot_date": row.snapshot_date, "currency": row.currency}
    data.update({column: getattr(row, column) for column in SNAPSHOT_COLUMNS})
    rate = row.inr_per_usd
    data["inr_per_usd"] = None if rate is None else Decimal(str(rate)).quantize(_RATE_QUANTUM)
    return data


# ---------------------------------------------------------------------------
# Combined (INR headline) figures
# ---------------------------------------------------------------------------

def _to_inr_minor(inr_minor: int, usd_minor: int, rate: Decimal) -> int:
    """INR paise + USD cents x rate, rounded half up once, at the end."""
    total = Decimal(inr_minor) + Decimal(usd_minor) * rate
    return int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def combine(rows: list[dict]) -> dict | None:
    """Combined INR row from the per-currency rows of ONE date (the live rows or
    one stored date). None when there is no usable rate on those rows. A currency
    with no row counts as zero. Global figures (users, pilots) are taken as they
    are, counts are summed, money is converted at the rate stored on the rows."""
    if not rows:
        return None
    rate = rows[0].get("inr_per_usd")
    if rate is None or any(r.get("inr_per_usd") != rate for r in rows):
        return None
    by_currency = {r["currency"]: r for r in rows}
    inr = by_currency.get(HEADLINE_CURRENCY, {})
    usd = by_currency.get("USD", {})
    out = dict(rows[0])
    out["currency"] = HEADLINE_CURRENCY
    for column in _SUMMED_COUNTS:
        out[column] = inr.get(column, 0) + usd.get(column, 0)
    for column in MONEY_COLUMNS:
        out[column] = _to_inr_minor(inr.get(column, 0), usd.get(column, 0), rate)
    return out


def combine_by_date(rows: list[dict]) -> dict:
    """{snapshot_date: combined row or None} for a list of per-currency rows."""
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row["snapshot_date"], []).append(row)
    return {day: combine(group) for day, group in grouped.items()}


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def _major(minor: int) -> str:
    """Minor units as a plain decimal in major units (199900 -> '1999.00')."""
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), 100)
    return f"{sign}{whole}.{frac:02d}"


# The columns after trial_to_paid_pct are the combined INR block. They repeat on
# both currency rows of a date (like users_total) and are blank when the rate
# was not set for that date. Money is in INR major units, like the other money
# columns it is named *_minor for continuity.
COMBINED_CSV_COLUMNS = (
    tuple(f"combined_{c}" for c in MONEY_COLUMNS)
    + ("combined_paying_orgs", "combined_arpa", "combined_logo_churn_pct", "combined_revenue_churn_pct")
)

CSV_HEADER = (
    ("date", "currency")
    + SNAPSHOT_COLUMNS
    + ("logo_churn_pct", "revenue_churn_pct", "arpa", "trial_to_paid_pct")
    + ("inr_per_usd",)
    + COMBINED_CSV_COLUMNS
)


def csv_row(data: dict, combined: dict | None = None) -> list:
    """One CSV row. Money columns are in major units, ratios blank when undefined.
    `combined` is the date's combine() result, None when the rate was not set."""
    ratios = derive(data)
    cells: list = [data["snapshot_date"].isoformat(), data["currency"]]
    for column in SNAPSHOT_COLUMNS:
        value = data[column]
        cells.append(_major(value) if column in MONEY_COLUMNS else value)
    cells.append("" if ratios["logo_churn_pct"] is None else ratios["logo_churn_pct"])
    cells.append("" if ratios["revenue_churn_pct"] is None else ratios["revenue_churn_pct"])
    cells.append("" if ratios["arpa_minor"] is None else _major(ratios["arpa_minor"]))
    cells.append("" if ratios["trial_to_paid_pct"] is None else ratios["trial_to_paid_pct"])
    cells.append(rate_text(data.get("inr_per_usd")) or "")
    if combined is None:
        cells.extend([""] * len(COMBINED_CSV_COLUMNS))
        return cells
    cross = derive(combined)
    cells.extend(_major(combined[column]) for column in MONEY_COLUMNS)
    cells.append(combined["paying_orgs"])
    cells.append("" if cross["arpa_minor"] is None else _major(cross["arpa_minor"]))
    cells.append("" if cross["logo_churn_pct"] is None else cross["logo_churn_pct"])
    cells.append("" if cross["revenue_churn_pct"] is None else cross["revenue_churn_pct"])
    return cells
