"""add_referral_system

Revision ID: a9f3c6d281be
Revises: d2f6a9c13e85
Create Date: 2026-11-01 00:00:00.000000

TODO.md priority item 5: converts promo_codes into a dual-purpose code
concept (admin pilot codes keep their existing single-redemption behavior
unchanged) rather than replacing it. Adds promo_codes.kind/owner_org_id/
max_redemptions, a new promo_code_redemptions table (multi-redemption
tracking, since a referral code can be used by up to 5 different orgs,
unlike the existing single redeemed_at/redeemed_by_org_id columns which
stay exactly as-is for the admin single-use case), and
organizations.referred_by_promo_code_id (set when an org signed up using
someone else's referral code). Backfills every existing organization with
its own referral code so no pre-existing org is left without one to share,
mirroring bd5777cfff12's aws_external_id backfill precedent.
"""
import uuid
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'a9f3c6d281be'
down_revision: Union[str, None] = 'd2f6a9c13e85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I, same alphabet as the ops panel pilot codes (api/staff_ops.py)


def upgrade() -> None:
    op.add_column('promo_codes', sa.Column('kind', sa.String(length=20), nullable=False, server_default='admin'))
    op.add_column('promo_codes', sa.Column('owner_org_id', UUID(as_uuid=False), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True))
    op.create_index('ix_promo_codes_owner_org_id', 'promo_codes', ['owner_org_id'])
    op.add_column('promo_codes', sa.Column('max_redemptions', sa.Integer(), nullable=False, server_default='1'))

    op.create_table(
        'promo_code_redemptions',
        sa.Column('id', UUID(as_uuid=False), primary_key=True),
        sa.Column('promo_code_id', UUID(as_uuid=False), sa.ForeignKey('promo_codes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('redeemed_by_org_id', UUID(as_uuid=False), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('redeemed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('first_payment_confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('promo_code_id', 'redeemed_by_org_id', name='uq_promo_code_redemption_org'),
    )
    op.create_index('ix_promo_code_redemptions_promo_code_id', 'promo_code_redemptions', ['promo_code_id'])
    op.create_index('ix_promo_code_redemptions_redeemed_by_org_id', 'promo_code_redemptions', ['redeemed_by_org_id'])

    op.add_column(
        'organizations',
        sa.Column('referred_by_promo_code_id', UUID(as_uuid=False), sa.ForeignKey('promo_codes.id', ondelete='SET NULL'), nullable=True),
    )

    # Backfill: every existing org gets its own shareable referral code,
    # same reasoning as bd5777cfff12's aws_external_id backfill, rather than
    # leaving pre-existing orgs with no code to share until they happen to
    # load a page that lazily creates one.
    conn = op.get_bind()
    orgs = conn.execute(sa.text('SELECT id FROM organizations')).fetchall()
    existing_codes = {c for (c,) in conn.execute(sa.text('SELECT code FROM promo_codes')).fetchall()}
    for (org_id,) in orgs:
        while True:
            code = "REF-" + "".join(secrets.choice(_ALPHABET) for _ in range(5))
            if code not in existing_codes:
                existing_codes.add(code)
                break
        conn.execute(
            sa.text(
                "INSERT INTO promo_codes (id, code, kind, owner_org_id, max_redemptions, created_at) "
                "VALUES (:id, :code, 'referral', :org_id, 5, now())"
            ),
            {"id": str(uuid.uuid4()), "code": code, "org_id": org_id},
        )


def downgrade() -> None:
    op.drop_column('organizations', 'referred_by_promo_code_id')
    op.drop_index('ix_promo_code_redemptions_redeemed_by_org_id', table_name='promo_code_redemptions')
    op.drop_index('ix_promo_code_redemptions_promo_code_id', table_name='promo_code_redemptions')
    op.drop_table('promo_code_redemptions')
    op.drop_column('promo_codes', 'max_redemptions')
    op.drop_index('ix_promo_codes_owner_org_id', table_name='promo_codes')
    op.drop_column('promo_codes', 'owner_org_id')
    op.drop_column('promo_codes', 'kind')
