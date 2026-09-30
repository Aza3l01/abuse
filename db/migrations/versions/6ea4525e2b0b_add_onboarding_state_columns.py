"""add_onboarding_state_columns

Revision ID: 6ea4525e2b0b
Revises: bd5777cfff12
Create Date: 2026-09-30 00:00:00.000000

Phase 4 (section 4c): organizations.onboarding_completed_at and
organizations.onboarding_dismissed_at, both nullable. Two columns because
dismissed (stop auto-opening the wizard) and completed (stop showing the
prompt at all) are different states, not one boolean.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '6ea4525e2b0b'
down_revision: Union[str, None] = 'bd5777cfff12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'organizations',
        sa.Column('onboarding_completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'organizations',
        sa.Column('onboarding_dismissed_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('organizations', 'onboarding_dismissed_at')
    op.drop_column('organizations', 'onboarding_completed_at')
