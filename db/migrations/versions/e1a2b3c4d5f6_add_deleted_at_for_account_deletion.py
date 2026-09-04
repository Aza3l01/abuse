"""add_deleted_at_for_account_deletion

Revision ID: e1a2b3c4d5f6
Revises: c1a9f4b7d203
Create Date: 2026-08-11 15:00:00.000000

Phase 7 (item 40). New columns only, no data to migrate yet (never applied
to a real DB).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1a2b3c4d5f6'
down_revision: Union[str, None] = 'c1a9f4b7d203'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('organizations', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('organizations', 'deleted_at')
    op.drop_column('clients', 'deleted_at')
