"""add_aws_cross_account_role

Revision ID: bd5777cfff12
Revises: d4b1f8a2e6c9
Create Date: 2026-09-30 00:00:00.000000

Phase 2: organizations.aws_role_arn and organizations.aws_external_id, for
sts:AssumeRole cross-account AWS access (replaces the shared long-lived
credential path, which stays as a fallback for any org without a role
configured). Backfills every existing org with a fresh External ID so the
value is stable and visible in the UI immediately, rather than generating
one lazily at first read.
"""
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'bd5777cfff12'
down_revision: Union[str, None] = 'd4b1f8a2e6c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'organizations',
        sa.Column('aws_role_arn', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'organizations',
        sa.Column('aws_external_id', sa.String(length=64), nullable=True),
    )

    conn = op.get_bind()
    orgs = conn.execute(sa.text('SELECT id FROM organizations')).fetchall()
    for (org_id,) in orgs:
        conn.execute(
            sa.text('UPDATE organizations SET aws_external_id = :ext_id WHERE id = :org_id'),
            {"ext_id": secrets.token_urlsafe(32), "org_id": org_id},
        )


def downgrade() -> None:
    op.drop_column('organizations', 'aws_external_id')
    op.drop_column('organizations', 'aws_role_arn')
