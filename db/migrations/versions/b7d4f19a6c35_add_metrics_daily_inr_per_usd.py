"""add_metrics_daily_inr_per_usd

Revision ID: b7d4f19a6c35
Revises: e8c1a53d7b92
Create Date: 2026-11-20 12:00:00.000000

Phase 7 section C: the ops panel gets a combined INR figure next to the
per-currency ones. The fixed reporting rate (INR per 1 USD, env
METRICS_INR_PER_USD) is stored on every metrics_daily row, so a past day keeps
the rate it was computed with.

Backfill: rows that already exist (written before this column) are set to the
rate in METRICS_INR_PER_USD at the moment this migration runs. That is an
approximation by design (they were never computed with any rate), and it keeps
old days showing a combined figure. If the variable is missing or invalid when
the migration runs, old rows stay NULL and show no combined figure.
"""
import os
from decimal import Decimal, InvalidOperation
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7d4f19a6c35'
down_revision: Union[str, None] = 'e8c1a53d7b92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _env_rate() -> Decimal | None:
    raw = os.environ.get('METRICS_INR_PER_USD', '').strip()
    try:
        rate = Decimal(raw)
    except InvalidOperation:
        return None
    if not rate.is_finite() or rate <= 0 or rate >= Decimal('1000000'):
        return None
    rate = rate.quantize(Decimal('0.0001'))
    return rate if rate > 0 else None


def upgrade() -> None:
    op.add_column('metrics_daily', sa.Column('inr_per_usd', sa.Numeric(precision=12, scale=4), nullable=True))
    rate = _env_rate()
    if rate is not None:
        op.get_bind().execute(
            sa.text('UPDATE metrics_daily SET inr_per_usd = :rate WHERE inr_per_usd IS NULL'),
            {'rate': rate},
        )


def downgrade() -> None:
    op.drop_column('metrics_daily', 'inr_per_usd')
