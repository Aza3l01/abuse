"""add_phase4_dashboard_columns

Revision ID: b7d9e4a2f631
Revises: a3f719d5c8b1
Create Date: 2026-08-11 09:00:00.000000

Phase 4 (items 18/19/20/21/22/32). No data to migrate yet (never applied to
a real DB). New columns only, items 15/16/17's Organization columns
(s3_connected_at, s3_status, s3_status_message, calibration_status,
last_scan_completed_at/status/error) already exist from Phase 1/2, not
touched here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


revision: str = 'b7d9e4a2f631'
down_revision: Union[str, None] = 'a3f719d5c8b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Item 22: alert email severity threshold
    op.add_column('organizations', sa.Column('alert_severity_threshold', sa.String(length=20), nullable=False, server_default='all'))

    # Item 19: raw log sample + per-agent score table
    op.add_column('verdicts', sa.Column('sample_logs', JSON(), nullable=True))
    op.add_column('verdicts', sa.Column('agent_scores', JSON(), nullable=True))

    # Item 32: GeoLite2-ASN
    op.add_column('ip_memory', sa.Column('geo_asn_number', sa.Integer(), nullable=True))
    op.add_column('ip_memory', sa.Column('geo_asn_org', sa.String(length=255), nullable=True))

    # Item 21: independent WAF/Cloudflare block state
    op.add_column('ip_memory', sa.Column('waf_blocked', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('ip_memory', sa.Column('cloudflare_blocked', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('ip_memory', sa.Column('waf_block_error', sa.Text(), nullable=True))
    op.add_column('ip_memory', sa.Column('cloudflare_block_error', sa.Text(), nullable=True))

    # Item 20: delivery failure detail (delivery_status is the pre-existing `status` column)
    op.add_column('alerts_sent', sa.Column('delivery_error', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('alerts_sent', 'delivery_error')

    op.drop_column('ip_memory', 'cloudflare_block_error')
    op.drop_column('ip_memory', 'waf_block_error')
    op.drop_column('ip_memory', 'cloudflare_blocked')
    op.drop_column('ip_memory', 'waf_blocked')
    op.drop_column('ip_memory', 'geo_asn_org')
    op.drop_column('ip_memory', 'geo_asn_number')

    op.drop_column('verdicts', 'agent_scores')
    op.drop_column('verdicts', 'sample_logs')

    op.drop_column('organizations', 'alert_severity_threshold')
