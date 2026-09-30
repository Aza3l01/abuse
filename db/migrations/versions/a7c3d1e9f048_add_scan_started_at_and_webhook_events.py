"""add_scan_started_at_and_webhook_events

Revision ID: a7c3d1e9f048
Revises: f2c8a5e7b164
Create Date: 2026-09-20 00:00:00.000000

Item 60: organizations.last_scan_started_at, set whenever last_scan_status
is set to in_progress, read by process_logs's stale-scan sweep to detect a
worker that died mid-scan without reaching the except/finally block.

Item 62: processed_webhook_events, a replay/idempotency guard for the
Razorpay and Stripe webhooks (unique on provider + event_id).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'a7c3d1e9f048'
down_revision: Union[str, None] = 'f2c8a5e7b164'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'organizations',
        sa.Column('last_scan_started_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'processed_webhook_events',
        sa.Column('id', UUID(as_uuid=False), primary_key=True),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('provider', 'event_id', name='uq_processed_webhook_events_provider_event_id'),
    )
    op.create_index(
        'ix_processed_webhook_events_created_at',
        'processed_webhook_events',
        ['created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_processed_webhook_events_created_at', table_name='processed_webhook_events')
    op.drop_table('processed_webhook_events')
    op.drop_column('organizations', 'last_scan_started_at')
