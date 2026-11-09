"""add_billing_foundation

Revision ID: f3a8d2c71b94
Revises: e5b2c8a14f97
Create Date: 2026-11-07 12:00:00.000000

Phase 3 (bill-then-pay with Razorpay Orders). New organizations billing
columns, organization_members.is_billing_contact, and the payments, bills and
billing_events tables. Existing next_billing_date, first_charged_at and gstin
columns are reused with the new meanings documented in db/models.py.

Non-null columns carry a server_default so every existing org and member gets
a value. bills, payments and billing_events reference organizations with ON
DELETE SET NULL: they are financial records that outlive account deletion.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = 'f3a8d2c71b94'
down_revision: Union[str, None] = 'e5b2c8a14f97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- organizations ---------------------------------------------------
    op.add_column('organizations', sa.Column('billing_period', sa.String(length=10), nullable=True))
    op.add_column('organizations', sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('organizations', sa.Column('pending_tier', sa.String(length=20), nullable=True))
    op.add_column('organizations', sa.Column('pending_period', sa.String(length=10), nullable=True))
    op.add_column('organizations', sa.Column('nonpayment_downgraded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('organizations', sa.Column('retention_grace_tier', sa.String(length=20), nullable=True))
    op.add_column('organizations', sa.Column('retention_grace_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('organizations', sa.Column('billing_emails_mode', sa.String(length=10), nullable=False, server_default='owner'))
    op.add_column('organizations', sa.Column('billing_reminders_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('organizations', sa.Column('billing_legal_name', sa.String(length=255), nullable=True))
    op.add_column('organizations', sa.Column('billing_address', sa.Text(), nullable=True))

    # --- organization_members --------------------------------------------
    op.add_column('organization_members', sa.Column('is_billing_contact', sa.Boolean(), nullable=False, server_default=sa.false()))

    # --- payments --------------------------------------------------------
    op.create_table(
        'payments',
        sa.Column('id', UUID(as_uuid=False), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=False), sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('org_name_snapshot', sa.String(length=255), nullable=False),
        sa.Column('razorpay_order_id', sa.String(length=255), nullable=False),
        sa.Column('razorpay_payment_id', sa.String(length=255), nullable=True),
        sa.Column('amount_paise', sa.Integer(), nullable=False),
        sa.Column('purpose', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='created'),
        sa.Column('line_items', JSON(), nullable=True),
        sa.Column('tos_accepted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('gstin_snapshot', sa.String(length=20), nullable=True),
        sa.Column('legal_name_snapshot', sa.String(length=255), nullable=True),
        sa.Column('address_snapshot', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('razorpay_order_id', name='uq_payments_razorpay_order_id'),
        sa.UniqueConstraint('razorpay_payment_id', name='uq_payments_razorpay_payment_id'),
    )
    op.create_index('ix_payments_org_id', 'payments', ['org_id'])

    # --- bills -----------------------------------------------------------
    op.create_table(
        'bills',
        sa.Column('id', UUID(as_uuid=False), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=False), sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('org_name_snapshot', sa.String(length=255), nullable=False),
        sa.Column('tier', sa.String(length=20), nullable=False),
        sa.Column('period', sa.String(length=10), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('amount_paise', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='INR'),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='open'),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('cancel_on', sa.Date(), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('payment_id', UUID(as_uuid=False), sa.ForeignKey('payments.id', ondelete='SET NULL'), nullable=True),
        sa.Column('ready_notified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('due_reminder_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_reminder_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('org_id', 'period_start', name='uq_bills_org_period_start'),
    )
    op.create_index('ix_bills_org_id', 'bills', ['org_id'])

    # --- billing_events --------------------------------------------------
    op.create_table(
        'billing_events',
        sa.Column('id', UUID(as_uuid=False), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=False), sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('event', sa.String(length=30), nullable=False),
        sa.Column('from_tier', sa.String(length=20), nullable=True),
        sa.Column('to_tier', sa.String(length=20), nullable=True),
        sa.Column('period', sa.String(length=10), nullable=True),
        sa.Column('amount_paise', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_billing_events_org_id', 'billing_events', ['org_id'])
    op.create_index('ix_billing_events_created_at', 'billing_events', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_billing_events_created_at', table_name='billing_events')
    op.drop_index('ix_billing_events_org_id', table_name='billing_events')
    op.drop_table('billing_events')

    op.drop_index('ix_bills_org_id', table_name='bills')
    op.drop_table('bills')

    op.drop_index('ix_payments_org_id', table_name='payments')
    op.drop_table('payments')

    op.drop_column('organization_members', 'is_billing_contact')

    op.drop_column('organizations', 'billing_address')
    op.drop_column('organizations', 'billing_legal_name')
    op.drop_column('organizations', 'billing_reminders_enabled')
    op.drop_column('organizations', 'billing_emails_mode')
    op.drop_column('organizations', 'retention_grace_until')
    op.drop_column('organizations', 'retention_grace_tier')
    op.drop_column('organizations', 'nonpayment_downgraded_at')
    op.drop_column('organizations', 'pending_period')
    op.drop_column('organizations', 'pending_tier')
    op.drop_column('organizations', 'cancel_at_period_end')
    op.drop_column('organizations', 'billing_period')
