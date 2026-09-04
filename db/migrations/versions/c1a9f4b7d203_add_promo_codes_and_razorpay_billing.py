"""add_promo_codes_and_razorpay_billing

Revision ID: c1a9f4b7d203
Revises: b7d9e4a2f631
Create Date: 2026-08-11 12:00:00.000000

Phase 6 (items 26/29/29b). New table + new Organization columns only, no
data to migrate yet (never applied to a real DB).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'c1a9f4b7d203'
down_revision: Union[str, None] = 'b7d9e4a2f631'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Item 29: Razorpay subscription identifiers
    op.add_column('organizations', sa.Column('razorpay_customer_id', sa.String(length=255), nullable=True))
    op.add_column('organizations', sa.Column('razorpay_subscription_id', sa.String(length=255), nullable=True))
    op.create_unique_constraint('uq_organizations_razorpay_customer_id', 'organizations', ['razorpay_customer_id'])
    op.create_unique_constraint('uq_organizations_razorpay_subscription_id', 'organizations', ['razorpay_subscription_id'])

    # Item 29b: calendar-anchored billing / refund window anchor
    op.add_column('organizations', sa.Column('next_billing_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('organizations', sa.Column('first_charged_at', sa.DateTime(timezone=True), nullable=True))

    # Item 26: promo code table
    op.create_table(
        'promo_codes',
        sa.Column('id', UUID(as_uuid=False), primary_key=True),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('provider_coupon_id_stripe', sa.String(length=255), nullable=True),
        sa.Column('provider_offer_id_razorpay', sa.String(length=255), nullable=True),
        sa.Column('redeemed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('redeemed_by_org_id', UUID(as_uuid=False), sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint('uq_promo_codes_code', 'promo_codes', ['code'])
    op.create_index('ix_promo_codes_code', 'promo_codes', ['code'])


def downgrade() -> None:
    op.drop_index('ix_promo_codes_code', table_name='promo_codes')
    op.drop_constraint('uq_promo_codes_code', 'promo_codes', type_='unique')
    op.drop_table('promo_codes')

    op.drop_column('organizations', 'first_charged_at')
    op.drop_column('organizations', 'next_billing_date')

    op.drop_constraint('uq_organizations_razorpay_subscription_id', 'organizations', type_='unique')
    op.drop_constraint('uq_organizations_razorpay_customer_id', 'organizations', type_='unique')
    op.drop_column('organizations', 'razorpay_subscription_id')
    op.drop_column('organizations', 'razorpay_customer_id')
