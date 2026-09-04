"""add_scan_runs_table

Revision ID: f6a2b9d34e17
Revises: a1f47c6d8e02
Create Date: 2026-08-08 00:00:00.000000

Item 5e: benign batches used to write a Verdict row with severity="none",
which is undocumented, unfilterable via the severity column, and shows up
in the alerts feed as a clean scan. This adds a separate lightweight
scan_runs table to hold that "we scanned and found nothing" evidence
instead, keeping `verdicts` reserved for actual detections.

Note for Phase 2: this table is keyed on client_id like everything else in
Phase 1. When Phase 2's item 7 rekeys Verdict/IpMemory/AlertSent from
client_id to org_id, scan_runs needs the same rekey.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a2b9d34e17'
down_revision: Union[str, None] = 'a1f47c6d8e02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scan_runs',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('client_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('scanned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('record_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_scan_runs_client_id'), 'scan_runs', ['client_id'], unique=False)
    op.create_index(op.f('ix_scan_runs_scanned_at'), 'scan_runs', ['scanned_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_scan_runs_scanned_at'), table_name='scan_runs')
    op.drop_index(op.f('ix_scan_runs_client_id'), table_name='scan_runs')
    op.drop_table('scan_runs')
