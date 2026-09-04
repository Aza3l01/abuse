"""
scripts/generate_promo_codes.py: item 26, one-time launch batch of 100
single-use promo codes.

Codes look like CLEW-A3F9X (5 uppercase alphanumeric chars, ambiguous
characters 0/O/1/I excluded). Idempotent: only tops up up to --count total
codes, never regenerates or deletes existing rows.

provider_coupon_id_stripe / provider_offer_id_razorpay are left NULL:
linking each code to an actual Stripe coupon / Razorpay offer is a manual
follow-up in each provider's dashboard (not required at redemption time,
only at eventual checkout), and Stripe production keys aren't live yet
(item 29's MVP-scope note).

Usage:
  python scripts/generate_promo_codes.py [--count 100]
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from db.models import PromoCode
from db.session import SessionLocal

_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I


def _generate_code() -> str:
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(5))
    return f"CLEW-{suffix}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        existing = db.query(PromoCode).count()
        to_create = max(0, args.count - existing)
        if to_create == 0:
            print(f"Already have {existing} promo codes (target {args.count}). Nothing to do.")
            return

        existing_codes = {c for (c,) in db.query(PromoCode.code).all()}
        created = []
        while len(created) < to_create:
            code = _generate_code()
            if code in existing_codes:
                continue
            existing_codes.add(code)
            created.append(code)
            db.add(PromoCode(code=code))
        db.commit()

        print(f"Created {len(created)} promo codes (total now {existing + len(created)}):")
        for code in created:
            print(f"  {code}")
        print(
            "\nLink each code to a Stripe coupon and Razorpay offer manually "
            "when checkout goes live, then set provider_coupon_id_stripe / "
            "provider_offer_id_razorpay on the row."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
