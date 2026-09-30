"""add_quota_warning_columns

Revision ID: d4b1f8a2e6c9
Revises: a7c3d1e9f048
Create Date: 2026-09-20 00:00:00.000000

Item 30 (section 5): organizations.quota_warning_sent_at and
quota_exceeded_sent_at, idempotency flags for the 80%/100% monthly
call-volume soft-limit emails. Cleared alongside
monthly_requests_processed by reset_monthly_counters each billing month.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4b1f8a2e6c9'
down_revision: Union[str, None] = 'a7c3d1e9f048'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'organizations',
        sa.Column('quota_warning_sent_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'organizations',
        sa.Column('quota_exceeded_sent_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('organizations', 'quota_exceeded_sent_at')
    op.drop_column('organizations', 'quota_warning_sent_at')
