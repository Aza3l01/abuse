"""drop_oauth_accounts

Revision ID: 5aecc2c086cc
Revises: e00054254a1b
Create Date: 2026-08-10 13:00:00.000000

OAuth/social sign-in (Google/GitHub/Microsoft) is not a wanted product
feature — confirmed explicitly, drops the table this was built for.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5aecc2c086cc'
down_revision: Union[str, None] = 'e00054254a1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_oauth_accounts_client_id', table_name='oauth_accounts')
    op.drop_table('oauth_accounts')


def downgrade() -> None:
    op.create_table(
        'oauth_accounts',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('client_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('provider_id', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_id', name='uq_oauth_provider_id'),
    )
    op.create_index('ix_oauth_accounts_client_id', 'oauth_accounts', ['client_id'], unique=False)
