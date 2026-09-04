"""add_registration_and_trial_columns

Revision ID: a3f719d5c8b1
Revises: 5aecc2c086cc
Create Date: 2026-08-10 15:00:00.000000

Phase 3 item 10 (registration wizard) + item 11 (trial billing). No data
to migrate yet (never applied to a real DB) — clients.full_name is added
NOT NULL directly, matching the precedent set by the org/rekey migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f719d5c8b1'
down_revision: Union[str, None] = '5aecc2c086cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column('full_name', sa.String(length=255), nullable=False))
    op.add_column('clients', sa.Column('tos_accepted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clients', sa.Column('mfa_nudge_dismissed_at', sa.DateTime(timezone=True), nullable=True))

    op.add_column('organizations', sa.Column('trial_source', sa.String(length=20), nullable=True))
    op.add_column('organizations', sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('organizations', sa.Column('pilot_code_used', sa.String(length=50), nullable=True))
    op.add_column('organizations', sa.Column('trial_reminder_5d_sent', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('organizations', sa.Column('trial_reminder_2d_sent', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('organizations', 'trial_reminder_2d_sent')
    op.drop_column('organizations', 'trial_reminder_5d_sent')
    op.drop_column('organizations', 'pilot_code_used')
    op.drop_column('organizations', 'trial_ends_at')
    op.drop_column('organizations', 'trial_source')

    op.drop_column('clients', 'mfa_nudge_dismissed_at')
    op.drop_column('clients', 'tos_accepted_at')
    op.drop_column('clients', 'full_name')
