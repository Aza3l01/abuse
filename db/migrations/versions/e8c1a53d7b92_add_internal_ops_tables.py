"""add_internal_ops_tables

Revision ID: e8c1a53d7b92
Revises: c4a7e2b81d36
Create Date: 2026-11-08 12:00:00.000000

Phase 6 internal ops panel: staff_users (separate from clients), the staff
audit log, and the metrics_daily snapshot table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e8c1a53d7b92'
down_revision: Union[str, None] = 'c4a7e2b81d36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'staff_users',
        sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('totp_secret', sa.Text(), nullable=False),
        sa.Column('totp_active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('last_totp_step', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_staff_users_email', 'staff_users', ['email'], unique=True)

    op.create_table(
        'staff_audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column('staff_id', postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column('staff_email', sa.String(length=255), nullable=False),
        sa.Column('action', sa.String(length=60), nullable=False),
        sa.Column('org_id', postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column('org_name_snapshot', sa.String(length=255), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('details', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['staff_id'], ['staff_users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_staff_audit_log_staff_id', 'staff_audit_log', ['staff_id'])
    op.create_index('ix_staff_audit_log_action', 'staff_audit_log', ['action'])
    op.create_index('ix_staff_audit_log_org_id', 'staff_audit_log', ['org_id'])
    op.create_index('ix_staff_audit_log_created_at', 'staff_audit_log', ['created_at'])

    op.create_table(
        'metrics_daily',
        sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('users_total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('users_verified', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('orgs_total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active_pilots', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pilots_converted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pilots_expired_unpaid', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('paying_orgs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('paying_starter', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('paying_growth', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('paying_pro', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('mrr_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('arr_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('paying_orgs_start', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('mrr_start_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('new_mrr_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('expansion_mrr_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('contraction_mrr_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('churned_mrr_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('churned_orgs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('refunds_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('refunds_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('overdue_bills', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('overdue_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('snapshot_date', 'currency', name='uq_metrics_daily_date_currency'),
    )
    op.create_index('ix_metrics_daily_snapshot_date', 'metrics_daily', ['snapshot_date'])


def downgrade() -> None:
    op.drop_index('ix_metrics_daily_snapshot_date', table_name='metrics_daily')
    op.drop_table('metrics_daily')
    op.drop_index('ix_staff_audit_log_created_at', table_name='staff_audit_log')
    op.drop_index('ix_staff_audit_log_org_id', table_name='staff_audit_log')
    op.drop_index('ix_staff_audit_log_action', table_name='staff_audit_log')
    op.drop_index('ix_staff_audit_log_staff_id', table_name='staff_audit_log')
    op.drop_table('staff_audit_log')
    op.drop_index('ix_staff_users_email', table_name='staff_users')
    op.drop_table('staff_users')
