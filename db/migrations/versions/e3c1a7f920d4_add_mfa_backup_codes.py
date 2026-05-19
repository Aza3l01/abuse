"""add_mfa_backup_codes

Revision ID: e3c1a7f920d4
Revises: b4e8f2a1c953
Create Date: 2026-05-19 14:00:00.000000

Creates the mfa_backup_codes table for single-use TOTP recovery codes.
Each row is one of the 10 codes generated when a user activates MFA.
Codes are stored as SHA-256 hashes; the plaintext is shown once and discarded.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'e3c1a7f920d4'
down_revision: Union[str, None] = 'b4e8f2a1c953'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'mfa_backup_codes',
        sa.Column('id',         UUID(as_uuid=False),            nullable=False),
        sa.Column('client_id',  UUID(as_uuid=False),            nullable=False),
        sa.Column('code_hash',  sa.Text(),                      nullable=False),
        sa.Column('used',       sa.Boolean(),                   nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True),     nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_mfa_backup_codes_client_id', 'mfa_backup_codes', ['client_id'])


def downgrade() -> None:
    op.drop_index('ix_mfa_backup_codes_client_id', table_name='mfa_backup_codes')
    op.drop_table('mfa_backup_codes')
