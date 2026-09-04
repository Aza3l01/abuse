"""add_source_key_and_s3_status

Revision ID: e91b6a3c8f45
Revises: d8a34f6b1c02
Create Date: 2026-08-10 09:00:00.000000

Phase 1 items 3 and 5:
  - verdicts.source_key + unique (client_id, source_key) — defense-in-depth
    dedup if the same S3 object is processed twice (item 2's lock failing
    open after a Redis restart). NULL allowed/repeatable for Pass B focus
    verdicts, which don't map to one source file.
  - clients.s3_status / s3_status_message — set when first-poll log format
    auto-detection finds a mismatch between the configured format and what
    the bucket actually contains.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e91b6a3c8f45'
down_revision: Union[str, None] = 'd8a34f6b1c02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('verdicts', sa.Column('source_key', sa.Text(), nullable=True))
    op.create_unique_constraint(
        'uq_verdicts_client_source_key', 'verdicts', ['client_id', 'source_key']
    )
    op.add_column('clients', sa.Column('s3_status', sa.String(20), nullable=True))
    op.add_column('clients', sa.Column('s3_status_message', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('clients', 's3_status_message')
    op.drop_column('clients', 's3_status')
    op.drop_constraint('uq_verdicts_client_source_key', 'verdicts', type_='unique')
    op.drop_column('verdicts', 'source_key')
