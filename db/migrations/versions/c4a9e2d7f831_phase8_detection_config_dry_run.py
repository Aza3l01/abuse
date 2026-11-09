"""phase8_detection_config_dry_run

Revision ID: c4a9e2d7f831
Revises: b7d4f19a6c35
Create Date: 2026-11-21 10:00:00.000000

Phase 8: organizations.detection_config (Pro/Enterprise threshold tuning),
organizations.auto_block_dry_run, verdicts.would_have_blocked_at.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c4a9e2d7f831'
down_revision: Union[str, None] = 'b7d4f19a6c35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('detection_config', sa.JSON(), nullable=True))
    op.add_column(
        'organizations',
        sa.Column('auto_block_dry_run', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'verdicts',
        sa.Column('would_have_blocked_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('verdicts', 'would_have_blocked_at')
    op.drop_column('organizations', 'auto_block_dry_run')
    op.drop_column('organizations', 'detection_config')
