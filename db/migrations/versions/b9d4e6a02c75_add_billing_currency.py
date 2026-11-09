"""add_billing_currency

Revision ID: b9d4e6a02c75
Revises: f3a8d2c71b94
Create Date: 2026-11-20 12:00:00.000000

Phase 5 section C (currency: USD default, INR regional). Organizations gain
billing_currency (NOT NULL, default USD) and billing_country (ISO alpha-2,
NULL until chosen). payments gain currency. bills already had a currency
column; its INR server default is dropped so a row can never silently fall
back to a currency nobody chose.

Everything that exists before this migration was created by the INR-only
flow, so existing payments are backfilled INR, and any organization that has
a payment, a bill or a first charge is backfilled INR with country IN. That
is what locks it to INR for good. Organizations that never paid keep the USD
default and a NULL country, so they pick a country at their first checkout.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b9d4e6a02c75'
down_revision: Union[str, None] = 'f3a8d2c71b94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('billing_currency', sa.String(length=3), nullable=False, server_default='USD'))
    op.add_column('organizations', sa.Column('billing_country', sa.String(length=2), nullable=True))

    # server_default INR backfills every existing payment, then is dropped so
    # new rows must state their currency explicitly.
    op.add_column('payments', sa.Column('currency', sa.String(length=3), nullable=False, server_default='INR'))
    op.alter_column('payments', 'currency', server_default=None)
    op.alter_column('bills', 'currency', server_default=None)

    op.execute(
        "UPDATE organizations SET billing_currency = 'INR', billing_country = 'IN' "
        "WHERE first_charged_at IS NOT NULL "
        "OR id IN (SELECT org_id FROM payments WHERE org_id IS NOT NULL) "
        "OR id IN (SELECT org_id FROM bills WHERE org_id IS NOT NULL)"
    )


def downgrade() -> None:
    op.alter_column('bills', 'currency', server_default='INR')
    op.drop_column('payments', 'currency')
    op.drop_column('organizations', 'billing_country')
    op.drop_column('organizations', 'billing_currency')
