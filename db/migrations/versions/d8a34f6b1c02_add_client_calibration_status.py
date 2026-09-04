"""add_client_calibration_status

Revision ID: d8a34f6b1c02
Revises: f6a2b9d34e17
Create Date: 2026-05-19 12:30:00.000000

Item 45 Gap A: adds a calibration_status column to clients, tracking the
one-off "silent calibration pass over the last 24h of logs" that runs on
first S3 connection (or reconnection to a new bucket). Values:
  NULL       — no S3 config yet, or calibration has never been triggered
  'running'  — calibration task is currently in flight
  'done'     — calibration completed, live detection proceeds normally
  'failed'   — calibration task raised after exhausting retries

This column is read-only from the API today; it exists so a future
dashboard "Calibrating..." banner (deferred, not part of this change) has
something to read without another migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd8a34f6b1c02'
down_revision: Union[str, None] = 'f6a2b9d34e17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column('calibration_status', sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column('clients', 'calibration_status')
