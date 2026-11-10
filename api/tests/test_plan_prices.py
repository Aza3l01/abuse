"""PLAN_PRICES must match the prices shown by the frontend, in both currencies.

frontend/src/lib/pricing.ts is the display copy of the price table. This test
parses it and fails if any monthly or annual number, in INR or USD, drifts
from api/tiers.py's PLAN_PRICES, so the page can never advertise a price the
billing engine does not charge.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from api.tiers import CURRENCIES, PLAN_PRICES, currency_for_country, plan_price

PRICING_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "pricing.ts"

SYMBOLS = {"INR": "₹", "USD": "$"}

# One block per tier inside PRICING_TIERS, from its `tier: "x"` line up to the
# next `tier:` line (or the end of the array).
_BLOCK_RE = re.compile(r'tier:\s*"(?P<tier>\w+)",(?P<body>.*?)(?=\n  \},|\Z)', re.S)
_FIELD_RE = r'{name}:\s*"([^"]*)"'


def _amount(text: str, symbol: str) -> int:
    match = re.search(re.escape(symbol) + r"\s*([\d,]+)", text)
    assert match, f"no {symbol} amount in {text!r}"
    return int(match.group(1).replace(",", ""))


def _parse_pricing_ts(currency: str) -> dict[str, dict[str, int]]:
    symbol = SYMBOLS[currency]
    source = PRICING_TS.read_text(encoding="utf-8")
    array = source.split("export const PRICING_TIERS", 1)[1].split("export interface FeatureRow", 1)[0]
    prices: dict[str, dict[str, int]] = {}
    for block in _BLOCK_RE.finditer(array):
        body = block.group("body")
        monthly = re.search(_FIELD_RE.format(name=f"monthly{currency}"), body)
        annual_note = re.search(_FIELD_RE.format(name=f"annualNote{currency}"), body)
        annual_per_month = re.search(_FIELD_RE.format(name=f"annual{currency}"), body)
        if not monthly or not monthly.group(1).startswith(symbol):
            continue  # free and enterprise carry no price
        assert annual_note and annual_per_month, f"{block.group('tier')} has no annual price"
        prices[block.group("tier")] = {
            "monthly": _amount(monthly.group(1), symbol),
            "annual": _amount(annual_note.group(1), symbol),
            "annual_per_month": _amount(annual_per_month.group(1), symbol),
        }
    return prices


@pytest.mark.parametrize("currency", CURRENCIES)
def test_pricing_ts_parses_the_three_paid_tiers(currency):
    assert set(_parse_pricing_ts(currency)) == {"basic", "growth", "pro"}


@pytest.mark.parametrize("currency", CURRENCIES)
def test_plan_prices_match_pricing_ts_exactly(currency):
    for tier, shown in _parse_pricing_ts(currency).items():
        assert plan_price(currency, tier, "monthly") == shown["monthly"] * 100, (currency, tier)
        assert plan_price(currency, tier, "annual") == shown["annual"] * 100, (currency, tier)


def test_plan_prices_cover_every_currency_tier_and_period():
    expected = {(c, t, p) for c in CURRENCIES for t in ("basic", "growth", "pro") for p in ("monthly", "annual")}
    assert set(PLAN_PRICES) == expected


@pytest.mark.parametrize("currency", CURRENCIES)
def test_annual_per_month_display_is_the_annual_price_over_twelve(currency):
    # The cards show "₹1,000/mo" for an 11,994 annual plan (999.5 rounded up).
    for tier, shown in _parse_pricing_ts(currency).items():
        assert abs(shown["annual_per_month"] - shown["annual"] / 12) <= 1, (currency, tier)


def test_annual_is_half_of_twelve_months_in_both_currencies():
    for currency in CURRENCIES:
        for tier in ("basic", "growth", "pro"):
            assert plan_price(currency, tier, "annual") * 2 == plan_price(currency, tier, "monthly") * 12


def test_the_published_inr_paise_values():
    assert {k[1:]: v for k, v in PLAN_PRICES.items() if k[0] == "INR"} == {
        ("basic", "monthly"): 199900,
        ("growth", "monthly"): 499900,
        ("pro", "monthly"): 999900,
        ("basic", "annual"): 1199400,
        ("growth", "annual"): 2999400,
        ("pro", "annual"): 5999400,
    }


def test_the_published_usd_cent_values():
    assert {k[1:]: v for k, v in PLAN_PRICES.items() if k[0] == "USD"} == {
        ("basic", "monthly"): 4900,
        ("growth", "monthly"): 12900,
        ("pro", "monthly"): 24900,
        ("basic", "annual"): 29400,
        ("growth", "annual"): 77400,
        ("pro", "annual"): 149400,
    }


def test_plan_price_rejects_an_unknown_currency_or_plan():
    with pytest.raises(ValueError):
        plan_price("EUR", "basic", "monthly")
    with pytest.raises(ValueError):
        plan_price("USD", "enterprise", "monthly")


def test_only_india_is_billed_in_inr():
    assert currency_for_country("IN") == "INR"
    assert currency_for_country("in") == "INR"
    for country in ("US", "GB", "AE", "SG", "DE", "PK"):
        assert currency_for_country(country) == "USD"
