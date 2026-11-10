"""rename_tiers_to_marketing_names

Revision ID: f4b9d2a6c718
Revises: e6c1a7d3f852
Create Date: 2026-11-24 10:00:00.000000

Internal tier codes now equal the marketing names: the free tier "free"
becomes "starter" and the first paid tier "starter" becomes "basic". One CASE
per column swaps both values in a single pass, so they never collide.
metrics_daily.paying_starter becomes paying_basic. Stored JSON line items on
old payments are not rewritten (no customers existed when this ran).
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'f4b9d2a6c718'
down_revision: Union[str, None] = 'e6c1a7d3f852'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ('organizations', 'tier'),
    ('organizations', 'pilot_tier'),
    ('organizations', 'pending_tier'),
    ('organizations', 'retention_grace_tier'),
    ('bills', 'tier'),
    ('credits', 'basis_tier'),
    ('billing_events', 'from_tier'),
    ('billing_events', 'to_tier'),
)


def _swap(table: str, column: str, old_free: str, old_paid: str, new_free: str, new_paid: str) -> None:
    op.execute(
        f"UPDATE {table} SET {column} = CASE {column} "
        f"WHEN '{old_paid}' THEN '{new_paid}' WHEN '{old_free}' THEN '{new_free}' "
        f"ELSE {column} END "
        f"WHERE {column} IN ('{old_free}', '{old_paid}')"
    )


def upgrade() -> None:
    for table, column in _COLUMNS:
        _swap(table, column, 'free', 'starter', 'starter', 'basic')
    op.alter_column('metrics_daily', 'paying_starter', new_column_name='paying_basic')


def downgrade() -> None:
    op.alter_column('metrics_daily', 'paying_basic', new_column_name='paying_starter')
    for table, column in _COLUMNS:
        _swap(table, column, 'starter', 'basic', 'free', 'starter')
