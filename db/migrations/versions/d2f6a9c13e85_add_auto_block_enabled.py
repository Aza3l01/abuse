"""add_auto_block_enabled

Revision ID: d2f6a9c13e85
Revises: 6ea4525e2b0b
Create Date: 2026-11-01 00:00:00.000000

TODO.md priority item 2: organizations.auto_block_enabled, an explicit
opt-in toggle for the unattended pipeline-triggered block, separate from
AUTO_BLOCK_TIERS (which only gates which tiers are eligible at all).
Defaults to false for every existing and future org, so no org's blocking
behavior changes the moment this migration runs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd2f6a9c13e85'
down_revision: Union[str, None] = '6ea4525e2b0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'organizations',
        sa.Column('auto_block_enabled', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('organizations', 'auto_block_enabled')
