"""add_referral_credit_ledger

Revision ID: e6c1a7d3f852
Revises: d5b8c3e1a742
Create Date: 2026-11-23 10:00:00.000000

Phase 12 (Referrals v2 on a credit ledger):
- credits: the ledger. A credit only reduces the earning org's own bills.
- bills.credit_applied_paise: credit used when the bill was issued. The
  existing amount_paise stays what the customer owes.
- promo_codes.owner_org_id: ON DELETE CASCADE becomes SET NULL, so purging a
  referrer no longer deletes their code and the referees' redemptions.
- Referral codes have no redemption cap now. The old max_redemptions of 5 on
  existing referral rows is left alone and ignored for kind 'referral'.

The old referral slot discount was never applied at checkout, so there is no
data to migrate.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'e6c1a7d3f852'
down_revision: Union[str, None] = 'd5b8c3e1a742'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'credits',
        sa.Column('id', UUID(as_uuid=False), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=False), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('amount_paise', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('basis_tier', sa.String(length=20), nullable=True),
        sa.Column('basis_period', sa.String(length=10), nullable=True),
        sa.Column('source_org_id', UUID(as_uuid=False), sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('redemption_id', UUID(as_uuid=False), sa.ForeignKey('promo_code_redemptions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('earned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('vests_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('held_reason', sa.String(length=200), nullable=True),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('applied_bill_id', UUID(as_uuid=False), sa.ForeignKey('bills.id', ondelete='SET NULL'), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_reason', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_credits_org_id', 'credits', ['org_id'])
    op.create_index('ix_credits_status', 'credits', ['status'])
    op.create_index('ix_credits_source_org_id', 'credits', ['source_org_id'])

    op.add_column('bills', sa.Column('credit_applied_paise', sa.Integer(), nullable=False, server_default='0'))

    op.drop_constraint('promo_codes_owner_org_id_fkey', 'promo_codes', type_='foreignkey')
    op.create_foreign_key(
        'promo_codes_owner_org_id_fkey', 'promo_codes', 'organizations',
        ['owner_org_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('promo_codes_owner_org_id_fkey', 'promo_codes', type_='foreignkey')
    op.create_foreign_key(
        'promo_codes_owner_org_id_fkey', 'promo_codes', 'organizations',
        ['owner_org_id'], ['id'], ondelete='CASCADE',
    )
    op.drop_column('bills', 'credit_applied_paise')
    op.drop_index('ix_credits_source_org_id', table_name='credits')
    op.drop_index('ix_credits_status', table_name='credits')
    op.drop_index('ix_credits_org_id', table_name='credits')
    op.drop_table('credits')
