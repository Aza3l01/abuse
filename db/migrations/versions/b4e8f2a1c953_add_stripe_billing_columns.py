"""add_stripe_billing_columns

Revision ID: b4e8f2a1c953
Revises: c957d12130b9
Create Date: 2026-05-19 12:00:00.000000

Adds three billing columns to the clients table:
  stripe_customer_id      — Stripe Customer object ID (reused across subscriptions)
  stripe_subscription_id  — active Stripe Subscription ID (NULL when on free tier)
  tier_expires_at         — set when cancelling at period end (future use)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4e8f2a1c953'
down_revision: Union[str, None] = 'c957d12130b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column('stripe_customer_id',     sa.String(255), nullable=True))
    op.add_column('clients', sa.Column('stripe_subscription_id', sa.String(255), nullable=True))
    op.add_column('clients', sa.Column('tier_expires_at',        sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint('uq_clients_stripe_customer_id',     'clients', ['stripe_customer_id'])
    op.create_unique_constraint('uq_clients_stripe_subscription_id', 'clients', ['stripe_subscription_id'])


def downgrade() -> None:
    op.drop_constraint('uq_clients_stripe_subscription_id', 'clients', type_='unique')
    op.drop_constraint('uq_clients_stripe_customer_id',     'clients', type_='unique')
    op.drop_column('clients', 'tier_expires_at')
    op.drop_column('clients', 'stripe_subscription_id')
    op.drop_column('clients', 'stripe_customer_id')
