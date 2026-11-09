"""add_monthly_llm_calls

Revision ID: e5b2c8a14f97
Revises: a9f3c6d281be
Create Date: 2026-11-07 00:00:00.000000

Phase 2 LLM guardrail: organizations.monthly_llm_calls counts the LLM calls
an org's scans attempted this month, so process_logs can cap them per tier
(api/tiers.py LLM_CALL_CAPS). Reset monthly with monthly_requests_processed.
server_default '0' backfills every existing org.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e5b2c8a14f97'
down_revision: Union[str, None] = 'a9f3c6d281be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'organizations',
        sa.Column('monthly_llm_calls', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('organizations', 'monthly_llm_calls')
