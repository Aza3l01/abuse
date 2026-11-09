"""add_billing_event_currency

Revision ID: c4a7e2b81d36
Revises: b9d4e6a02c75
Create Date: 2026-11-21 12:00:00.000000

billing_events.amount_paise is in the minor units of a currency that the row
did not record. Phase 6 revenue views must not add rupees to dollars, so the
row now carries its currency. It stays NULL when the event has no amount.
Every amount written before this migration came from the INR-only flow, so
those rows are backfilled INR.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c4a7e2b81d36'
down_revision: Union[str, None] = 'b9d4e6a02c75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('billing_events', sa.Column('currency', sa.String(length=3), nullable=True))
    op.execute("UPDATE billing_events SET currency = 'INR' WHERE amount_paise IS NOT NULL")


def downgrade() -> None:
    op.drop_column('billing_events', 'currency')
