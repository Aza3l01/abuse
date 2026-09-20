"""encrypt_cloudflare_token_at_rest

Revision ID: f2c8a5e7b164
Revises: e1a2b3c4d5f6
Create Date: 2026-09-20 00:00:00.000000

Item 57. Organizations.cloudflare_token was written and read as plaintext.
Application code now encrypts it with the same Fernet key used for TOTP
secrets (api.auth_utils.encrypt_secret/decrypt_secret). This migration
encrypts any existing plaintext value in place so the column matches what
the application now expects.

Requires TOTP_ENCRYPTION_KEY to be set in the environment this migration
runs in, same key the application uses. Idempotent: a value that already
decrypts cleanly with that key is left alone (already encrypted), so
running this twice, or against a table with no rows yet, is a no-op.
"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'f2c8a5e7b164'
down_revision: Union[str, None] = 'e1a2b3c4d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_organizations = sa.table(
    'organizations',
    sa.column('id', UUID(as_uuid=False)),
    sa.column('cloudflare_token', sa.Text),
)


def upgrade() -> None:
    key = os.environ.get('TOTP_ENCRYPTION_KEY', '')
    if not key:
        raise RuntimeError(
            'TOTP_ENCRYPTION_KEY must be set to run this migration, item 57 '
            'encrypts organizations.cloudflare_token in place using this key.'
        )
    fernet = Fernet(key.encode())
    conn = op.get_bind()

    rows = conn.execute(
        sa.select(_organizations.c.id, _organizations.c.cloudflare_token).where(
            _organizations.c.cloudflare_token.isnot(None)
        )
    ).fetchall()

    for row in rows:
        value = row.cloudflare_token
        if not value:
            continue
        try:
            fernet.decrypt(value.encode())
            continue  # already a valid Fernet token, already encrypted
        except InvalidToken:
            pass
        encrypted = fernet.encrypt(value.encode()).decode()
        conn.execute(
            _organizations.update()
            .where(_organizations.c.id == row.id)
            .values(cloudflare_token=encrypted)
        )


def downgrade() -> None:
    # Deliberately irreversible: decrypting back to plaintext on downgrade
    # would recreate the exact exposure this migration exists to close.
    pass
