"""api/tiers.py: shared tier constants (item 55, extended by item 30/section 5).

Started as blocking-gate constants only (item 55): before this module
existed, "which tiers can block" was a plain ("growth", "pro") tuple
copy-pasted across four call sites (verdicts.py x3, process_logs.py) plus a
separate {"growth", "pro"} set in push_blocks.py and settings.py, none of
which knew about the "enterprise" tier. Import from here instead of
hardcoding a tier list.

  - MANUAL_BLOCK_TIERS: gates the dashboard's block/unblock button.
  - AUTO_BLOCK_TIERS: gates the unattended pipeline-triggered block.
  - CALL_VOLUME_CAPS: monthly call-volume cap per tier (section 5 metering).
  - RETENTION_DAYS: threat-data retention window per tier, in days (section 5).
  - LTM_TTL_DAYS: Redis TTL override for the engine's learned calibration
    memory, per tier (section 5's ProductSharedMemory decision).
"""
from __future__ import annotations

MANUAL_BLOCK_TIERS = frozenset({"starter", "growth", "pro", "enterprise"})
AUTO_BLOCK_TIERS = frozenset({"growth", "pro", "enterprise"})

# Phase 8: tiers that may tune detection (confidence thresholds, per-agent and
# per-endpoint minimums) and get cross-IP clustering. Pro's differentiator.
CUSTOM_THRESHOLD_TIERS = frozenset({"pro", "enterprise"})

# Item 30 (section 5): monthly call-volume cap per tier, used by
# process_logs.py's metering increment / soft-limit check and by the
# dashboard's usage banner. None means no fixed cap (enterprise is
# contract-negotiated per item 74). Matches the numbers already published
# on the pricing cards (frontend/src/lib/pricing.ts's `volume` strings).
CALL_VOLUME_CAPS: dict[str, int | None] = {
    "free": 2_000_000,
    "starter": 10_000_000,
    "growth": 50_000_000,
    "pro": 200_000_000,
    "enterprise": None,
}

# Item 30 (section 5): threat data retention window per tier, in days. None
# means unlimited (enterprise, carried forward from the old pricing table
# per section 5's own text). Used by the daily purge task.
RETENTION_DAYS: dict[str, int | None] = {
    "free": 7,
    "starter": 30,
    "growth": 90,   # "3 months"
    "pro": 365,     # "1 year"
    "enterprise": None,
}

# Item 30 (section 5), the ProductSharedMemory follow-up decision: a
# free-tier org's learned calibration state (Redis clew:ltm:{org_id}) is
# capped at the same 7-day window as its data retention, instead of the
# engine's normal 30-day default, so the memory can't outlive the org's own
# threat-history promise. Every other tier keeps the engine's default (not
# listed here, see detection/engine/memory/product_memory.py's
# _LTM_TTL_SECONDS). Only present here, not in RETENTION_DAYS, because this
# is a Redis TTL in days, not a Postgres purge-by-timestamp window.
LTM_TTL_DAYS: dict[str, int] = {
    "free": 7,
}

# Phase 3 (legacy item 33): tiers that get a real Groq-generated verdict
# explanation instead of the rule-based template string. Matches
# FEATURE_ROWS's "Threat explanations" row (Growth and above since
# 2026-09-19) and the verdict detail page's own gate.
LLM_EXPLANATION_TIERS = frozenset({"growth", "pro", "enterprise"})

# Phase 2: monthly ceiling on LLM calls per org, an internal cost guardrail
# (not published in pricing copy). The engine calls the LLM once per detected
# attack, only for LLM_EXPLANATION_TIERS. Over the ceiling a verdict keeps
# its rule-based explanation and scanning continues. None means unlimited
# (enterprise). Tiers absent here make no LLM calls at all. The numbers are
# founder-confirmed; the counter is Organization.monthly_llm_calls, reset
# monthly in reset_usage_counters.py.
LLM_CALL_CAPS: dict[str, int | None] = {
    "growth": 5_000,
    "pro": 25_000,
    "enterprise": None,
}

# Phase 3 + Phase 5 section C: the single price table the billing engine and
# the Razorpay order flow read, keyed by (currency, internal tier, period).
# Amounts are minor units of the currency: paise for INR (exclusive of GST),
# cents for USD. "starter" is the marketing name "Basic". Only purchasable
# tiers appear here: "free" is never bought and "enterprise" is contact-only.
# frontend/src/lib/pricing.ts is the display copy of these numbers;
# api/tests/test_plan_prices.py fails if the two drift apart.
PLAN_PRICES: dict[tuple[str, str, str], int] = {
    ("INR", "starter", "monthly"): 199_900,
    ("INR", "starter", "annual"): 1_199_400,
    ("INR", "growth", "monthly"): 499_900,
    ("INR", "growth", "annual"): 2_999_400,
    ("INR", "pro", "monthly"): 999_900,
    ("INR", "pro", "annual"): 5_999_400,
    ("USD", "starter", "monthly"): 4_900,
    ("USD", "starter", "annual"): 29_400,
    ("USD", "growth", "monthly"): 12_900,
    ("USD", "growth", "annual"): 77_400,
    ("USD", "pro", "monthly"): 24_900,
    ("USD", "pro", "annual"): 149_400,
}

# The currencies a Clew org can be billed in. USD is the default for every
# country except India (see currency_for_country).
CURRENCIES: tuple[str, ...] = ("USD", "INR")

# (tier, period) pairs that can be bought, in any currency.
PURCHASABLE_PLANS: frozenset[tuple[str, str]] = frozenset(
    (tier, period) for _currency, tier, period in PLAN_PRICES
)

# Smallest order Razorpay will take, per currency, in minor units (Rs 1 and
# 50 cents). Orders below it are a configuration error, never sent.
MIN_ORDER_MINOR: dict[str, int] = {"INR": 100, "USD": 50}


def plan_price(currency: str, tier: str, period: str) -> int:
    """The list price of a plan in `currency`, in minor units. Raises
    ValueError for an unknown currency or a plan that is not purchasable, so a
    caller can never get a price in a currency nobody chose."""
    try:
        return PLAN_PRICES[(currency, tier, period)]
    except KeyError:
        raise ValueError(f"no price for {currency} {tier} {period}") from None


def currency_for_country(country: str) -> str:
    """INR for India, USD for every other country."""
    return "INR" if country.upper() == "IN" else "USD"

# Purchasable tiers from cheapest to dearest, used to classify a plan change
# as an upgrade or a downgrade.
PAID_TIER_ORDER: tuple[str, ...] = ("starter", "growth", "pro")
