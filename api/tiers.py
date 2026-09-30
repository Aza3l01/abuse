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
