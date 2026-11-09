"""drop_dead_razorpay_org_columns

Revision ID: d5b8c3e1a742
Revises: c4a9e2d7f831
Create Date: 2026-11-22 10:00:00.000000

Phase 10: organizations.razorpay_customer_id and razorpay_subscription_id were
written by the old Razorpay Subscriptions flow and have not been read or
written since Phase 3 (bill-then-pay with Orders). Nothing in api, workers,
scripts, db or the frontend references them. next_billing_date is kept.

Run the Phase 15 pre-deploy check on the production database before this
migration: it must report that no row has either column set, or the values
are lost. The downgrade restores the columns and their unique constraints
empty, it cannot restore the dropped values.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd5b8c3e1a742'
down_revision: Union[str, None] = 'c4a9e2d7f831'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('uq_organizations_razorpay_subscription_id', 'organizations', type_='unique')
    op.drop_constraint('uq_organizations_razorpay_customer_id', 'organizations', type_='unique')
    op.drop_column('organizations', 'razorpay_subscription_id')
    op.drop_column('organizations', 'razorpay_customer_id')


def downgrade() -> None:
    op.add_column('organizations', sa.Column('razorpay_customer_id', sa.String(length=255), nullable=True))
    op.add_column('organizations', sa.Column('razorpay_subscription_id', sa.String(length=255), nullable=True))
    op.create_unique_constraint('uq_organizations_razorpay_customer_id', 'organizations', ['razorpay_customer_id'])
    op.create_unique_constraint('uq_organizations_razorpay_subscription_id', 'organizations', ['razorpay_subscription_id'])
