"""phase12b_pause_and_signup_source

Revision ID: a8d4f1c6b293
Revises: f4b9d2a6c718
Create Date: 2026-11-24 12:00:00.000000

Phase 12b:
- organizations.scanning_paused_at / scanning_paused_by: a customer pause.
  NULL scanning_paused_at means scanning runs. scanning_paused_by is the
  client who paused (ON DELETE SET NULL, a purged login must not block a
  purge or lose the pause).
- organizations.scanning_resumed_at: set on resume, read once by the next
  scan so the backlog from the pause is skipped, then cleared.
- organizations.signup_source / signup_source_detail: the optional "how did
  you hear about us" answer. Existing orgs stay NULL ("not asked").
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'a8d4f1c6b293'
down_revision: Union[str, None] = 'f4b9d2a6c718'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('scanning_paused_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'organizations',
        sa.Column('scanning_paused_by', UUID(as_uuid=False), sa.ForeignKey('clients.id', ondelete='SET NULL'), nullable=True),
    )
    op.add_column('organizations', sa.Column('scanning_resumed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('organizations', sa.Column('signup_source', sa.String(length=30), nullable=True))
    op.add_column('organizations', sa.Column('signup_source_detail', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('organizations', 'signup_source_detail')
    op.drop_column('organizations', 'signup_source')
    op.drop_column('organizations', 'scanning_resumed_at')
    op.drop_column('organizations', 'scanning_paused_by')  # drops its foreign key with it
    op.drop_column('organizations', 'scanning_paused_at')
