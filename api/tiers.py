"""api/tiers.py: shared tier constants for blocking gates (item 55).

Before this module existed, "which tiers can block" was a plain
("growth", "pro") tuple copy-pasted across four call sites (verdicts.py x3,
process_logs.py) plus a separate {"growth", "pro"} set in push_blocks.py and
settings.py, none of which knew about the "enterprise" tier. An Enterprise
customer paying for custom pricing was silently treated as ineligible for
blocking everywhere. Import from here instead of hardcoding a tier list.

Two constants, not one, per item 73's decision that Basic (the "starter"
tier code) gets manual blocking only, not automatic:
  - MANUAL_BLOCK_TIERS: gates the dashboard's block/unblock button.
  - AUTO_BLOCK_TIERS: gates the unattended pipeline-triggered block.
"""
from __future__ import annotations

MANUAL_BLOCK_TIERS = frozenset({"starter", "growth", "pro", "enterprise"})
AUTO_BLOCK_TIERS = frozenset({"growth", "pro", "enterprise"})
