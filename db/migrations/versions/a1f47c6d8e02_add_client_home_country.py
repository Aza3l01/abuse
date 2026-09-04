"""add_client_home_country

Revision ID: a1f47c6d8e02
Revises: e3c1a7f920d4
Create Date: 2026-08-08 00:00:00.000000

Adds clients.home_country (ISO 3166-1 alpha-2, nullable). Used by GeoIPAgent
to exclude the tenant's own country from foreign-concentration scoring
instead of comparing against an always-empty string.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1f47c6d8e02'
down_revision: Union[str, None] = 'e3c1a7f920d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column('home_country', sa.String(length=2), nullable=True))


def downgrade() -> None:
    op.drop_column('clients', 'home_country')
