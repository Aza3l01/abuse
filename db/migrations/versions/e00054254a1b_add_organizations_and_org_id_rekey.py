"""add_organizations_and_org_id_rekey

Revision ID: e00054254a1b
Revises: e91b6a3c8f45
Create Date: 2026-08-10 12:00:00.000000

Phase 2, item 7 — organisation / multi-user refactor.

Adds `organizations`, `organization_members` (true many-to-many join,
Client <-> Organization with a role), and `org_invites`. Moves all
per-tenant config (S3, blocking, billing, alerts, home_country,
calibration_status, s3_status*) off `clients` onto `organizations`.
Rekeys `verdicts`, `ip_memory`, `alerts_sent`, `scan_runs` from
`client_id` to `org_id`.

Clean drop + recreate for the four rekeyed tables (per TODO.md's explicit
instruction) rather than ALTER/rename — there is no production data yet
(dev-only schema, never applied to a real DB this whole phase), so this
avoids having to guess Postgres's auto-generated constraint names for the
old client_id FKs/uniques.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e00054254a1b'
down_revision: Union[str, None] = 'e91b6a3c8f45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Drop the four tables being rekeyed (children first: alerts_sent
    # references verdicts).
    # ------------------------------------------------------------------
    op.drop_index(op.f('ix_alerts_sent_verdict_id'), table_name='alerts_sent')
    op.drop_index(op.f('ix_alerts_sent_client_id'), table_name='alerts_sent')
    op.drop_table('alerts_sent')

    op.drop_index(op.f('ix_verdicts_timestamp'), table_name='verdicts')
    op.drop_index(op.f('ix_verdicts_ip'), table_name='verdicts')
    op.drop_index(op.f('ix_verdicts_client_id'), table_name='verdicts')
    op.drop_table('verdicts')

    op.drop_index(op.f('ix_ip_memory_ip'), table_name='ip_memory')
    op.drop_index(op.f('ix_ip_memory_client_id'), table_name='ip_memory')
    op.drop_table('ip_memory')

    op.drop_index(op.f('ix_scan_runs_scanned_at'), table_name='scan_runs')
    op.drop_index(op.f('ix_scan_runs_client_id'), table_name='scan_runs')
    op.drop_table('scan_runs')

    # ------------------------------------------------------------------
    # Strip org-config columns off clients (moved to organizations below).
    # Dropping a column drops any constraint that lives only on it (the
    # stripe_*_id unique constraints), no CASCADE needed.
    # ------------------------------------------------------------------
    op.drop_column('clients', 'company_name')
    op.drop_column('clients', 's3_bucket')
    op.drop_column('clients', 's3_prefix')
    op.drop_column('clients', 'log_format')
    op.drop_column('clients', 'aws_region')
    op.drop_column('clients', 'last_processed_key')
    op.drop_column('clients', 's3_status')
    op.drop_column('clients', 's3_status_message')
    op.drop_column('clients', 'calibration_status')
    op.drop_column('clients', 'home_country')
    op.drop_column('clients', 'waf_ip_set_id')
    op.drop_column('clients', 'cloudflare_zone_id')
    op.drop_column('clients', 'cloudflare_token')
    op.drop_column('clients', 'alert_email')
    op.drop_column('clients', 'tier')
    op.drop_column('clients', 'stripe_customer_id')
    op.drop_column('clients', 'stripe_subscription_id')
    op.drop_column('clients', 'tier_expires_at')

    # ------------------------------------------------------------------
    # organizations
    # ------------------------------------------------------------------
    op.create_table(
        'organizations',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('company_name', sa.String(length=255), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=True),
        sa.Column('s3_bucket', sa.String(length=255), nullable=True),
        sa.Column('s3_prefix', sa.String(length=255), nullable=True),
        sa.Column('log_format', sa.String(length=50), nullable=True),
        sa.Column('aws_region', sa.String(length=50), nullable=True),
        sa.Column('last_processed_key', sa.Text(), nullable=True),
        sa.Column('s3_connected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('s3_status', sa.String(length=20), nullable=True),
        sa.Column('s3_status_message', sa.Text(), nullable=True),
        sa.Column('calibration_status', sa.String(length=20), nullable=True),
        sa.Column('last_scan_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_scan_status', sa.String(length=20), nullable=True),
        sa.Column('last_scan_error', sa.Text(), nullable=True),
        sa.Column('home_country', sa.String(length=2), nullable=True),
        sa.Column('waf_ip_set_id', sa.String(length=255), nullable=True),
        sa.Column('cloudflare_zone_id', sa.String(length=255), nullable=True),
        sa.Column('cloudflare_token', sa.Text(), nullable=True),
        sa.Column('blocking_tos_accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('alert_email', sa.String(length=255), nullable=True),
        sa.Column('tier', sa.String(length=20), nullable=False),
        sa.Column('billing_provider', sa.String(length=20), nullable=True),
        sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
        sa.Column('tier_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('pilot_tier', sa.String(length=20), nullable=True),
        sa.Column('payment_method_display', sa.String(length=255), nullable=True),
        sa.Column('gstin', sa.String(length=20), nullable=True),
        sa.Column('monthly_requests_processed', sa.Integer(), nullable=False),
        sa.Column('monthly_requests_reset_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_customer_id'),
        sa.UniqueConstraint('stripe_subscription_id'),
    )

    # ------------------------------------------------------------------
    # organization_members (many-to-many: Client <-> Organization + role)
    # ------------------------------------------------------------------
    op.create_table(
        'organization_members',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('client_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('org_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_id', 'org_id', name='uq_org_member_client_org'),
    )
    op.create_index(op.f('ix_organization_members_client_id'), 'organization_members', ['client_id'], unique=False)
    op.create_index(op.f('ix_organization_members_org_id'), 'organization_members', ['org_id'], unique=False)

    # ------------------------------------------------------------------
    # org_invites
    # ------------------------------------------------------------------
    op.create_table(
        'org_invites',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('org_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('invited_email', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('token_hash', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(op.f('ix_org_invites_org_id'), 'org_invites', ['org_id'], unique=False)
    op.create_index(op.f('ix_org_invites_invited_email'), 'org_invites', ['invited_email'], unique=False)

    # ------------------------------------------------------------------
    # Recreate verdicts / ip_memory / alerts_sent / scan_runs with org_id
    # ------------------------------------------------------------------
    op.create_table(
        'verdicts',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('org_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ip', sa.String(length=45), nullable=False),
        sa.Column('method', sa.String(length=10), nullable=True),
        sa.Column('endpoint', sa.Text(), nullable=True),
        sa.Column('threat_type', sa.String(length=100), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('agents_triggered', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('blocked', sa.Boolean(), nullable=False),
        sa.Column('cost_prevented', sa.Float(), nullable=True),
        sa.Column('source_key', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'source_key', name='uq_verdicts_org_source_key'),
    )
    op.create_index(op.f('ix_verdicts_org_id'), 'verdicts', ['org_id'], unique=False)
    op.create_index(op.f('ix_verdicts_ip'), 'verdicts', ['ip'], unique=False)
    op.create_index(op.f('ix_verdicts_timestamp'), 'verdicts', ['timestamp'], unique=False)

    op.create_table(
        'ip_memory',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('org_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('ip', sa.String(length=45), nullable=False),
        sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('total_requests', sa.Integer(), nullable=False),
        sa.Column('threat_count', sa.Integer(), nullable=False),
        sa.Column('risk_score', sa.Float(), nullable=False),
        sa.Column('geo_country', sa.String(length=10), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'ip', name='uq_ip_memory_org_ip'),
    )
    op.create_index(op.f('ix_ip_memory_org_id'), 'ip_memory', ['org_id'], unique=False)
    op.create_index(op.f('ix_ip_memory_ip'), 'ip_memory', ['ip'], unique=False)

    op.create_table(
        'alerts_sent',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('org_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('verdict_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('channel', sa.String(length=50), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['verdict_id'], ['verdicts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_alerts_sent_org_id'), 'alerts_sent', ['org_id'], unique=False)
    op.create_index(op.f('ix_alerts_sent_verdict_id'), 'alerts_sent', ['verdict_id'], unique=False)

    op.create_table(
        'scan_runs',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('org_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('scanned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('record_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_scan_runs_org_id'), 'scan_runs', ['org_id'], unique=False)
    op.create_index(op.f('ix_scan_runs_scanned_at'), 'scan_runs', ['scanned_at'], unique=False)


def downgrade() -> None:
    # Reverse of upgrade(), in reverse order. Drops all org-scoped data
    # (no attempt to migrate it back onto clients — this is a dev-only,
    # no-data-yet schema per upgrade()'s docstring).
    op.drop_index(op.f('ix_scan_runs_scanned_at'), table_name='scan_runs')
    op.drop_index(op.f('ix_scan_runs_org_id'), table_name='scan_runs')
    op.drop_table('scan_runs')

    op.drop_index(op.f('ix_alerts_sent_verdict_id'), table_name='alerts_sent')
    op.drop_index(op.f('ix_alerts_sent_org_id'), table_name='alerts_sent')
    op.drop_table('alerts_sent')

    op.drop_index(op.f('ix_ip_memory_ip'), table_name='ip_memory')
    op.drop_index(op.f('ix_ip_memory_org_id'), table_name='ip_memory')
    op.drop_table('ip_memory')

    op.drop_index(op.f('ix_verdicts_timestamp'), table_name='verdicts')
    op.drop_index(op.f('ix_verdicts_ip'), table_name='verdicts')
    op.drop_index(op.f('ix_verdicts_org_id'), table_name='verdicts')
    op.drop_table('verdicts')

    op.drop_index(op.f('ix_org_invites_invited_email'), table_name='org_invites')
    op.drop_index(op.f('ix_org_invites_org_id'), table_name='org_invites')
    op.drop_table('org_invites')

    op.drop_index(op.f('ix_organization_members_org_id'), table_name='organization_members')
    op.drop_index(op.f('ix_organization_members_client_id'), table_name='organization_members')
    op.drop_table('organization_members')

    op.drop_table('organizations')

    op.add_column('clients', sa.Column('tier_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clients', sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True))
    op.add_column('clients', sa.Column('stripe_customer_id', sa.String(length=255), nullable=True))
    op.create_unique_constraint(None, 'clients', ['stripe_subscription_id'])
    op.create_unique_constraint(None, 'clients', ['stripe_customer_id'])
    op.add_column('clients', sa.Column('tier', sa.String(length=20), nullable=False, server_default='free'))
    op.add_column('clients', sa.Column('alert_email', sa.String(length=255), nullable=True))
    op.add_column('clients', sa.Column('cloudflare_token', sa.Text(), nullable=True))
    op.add_column('clients', sa.Column('cloudflare_zone_id', sa.String(length=255), nullable=True))
    op.add_column('clients', sa.Column('waf_ip_set_id', sa.String(length=255), nullable=True))
    op.add_column('clients', sa.Column('home_country', sa.String(length=2), nullable=True))
    op.add_column('clients', sa.Column('calibration_status', sa.String(length=20), nullable=True))
    op.add_column('clients', sa.Column('s3_status_message', sa.Text(), nullable=True))
    op.add_column('clients', sa.Column('s3_status', sa.String(length=20), nullable=True))
    op.add_column('clients', sa.Column('last_processed_key', sa.Text(), nullable=True))
    op.add_column('clients', sa.Column('aws_region', sa.String(length=50), nullable=True))
    op.add_column('clients', sa.Column('log_format', sa.String(length=50), nullable=True))
    op.add_column('clients', sa.Column('s3_prefix', sa.String(length=255), nullable=True))
    op.add_column('clients', sa.Column('s3_bucket', sa.String(length=255), nullable=True))
    op.add_column('clients', sa.Column('company_name', sa.String(length=255), nullable=False, server_default=''))

    op.create_table(
        'ip_memory',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('client_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('ip', sa.String(length=45), nullable=False),
        sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('total_requests', sa.Integer(), nullable=False),
        sa.Column('threat_count', sa.Integer(), nullable=False),
        sa.Column('risk_score', sa.Float(), nullable=False),
        sa.Column('geo_country', sa.String(length=10), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_id', 'ip', name='uq_ip_memory_client_ip'),
    )
    op.create_index(op.f('ix_ip_memory_client_id'), 'ip_memory', ['client_id'], unique=False)
    op.create_index(op.f('ix_ip_memory_ip'), 'ip_memory', ['ip'], unique=False)

    op.create_table(
        'verdicts',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('client_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ip', sa.String(length=45), nullable=False),
        sa.Column('method', sa.String(length=10), nullable=True),
        sa.Column('endpoint', sa.Text(), nullable=True),
        sa.Column('threat_type', sa.String(length=100), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('agents_triggered', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('blocked', sa.Boolean(), nullable=False),
        sa.Column('cost_prevented', sa.Float(), nullable=True),
        sa.Column('source_key', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_id', 'source_key', name='uq_verdicts_client_source_key'),
    )
    op.create_index(op.f('ix_verdicts_client_id'), 'verdicts', ['client_id'], unique=False)
    op.create_index(op.f('ix_verdicts_ip'), 'verdicts', ['ip'], unique=False)
    op.create_index(op.f('ix_verdicts_timestamp'), 'verdicts', ['timestamp'], unique=False)

    op.create_table(
        'alerts_sent',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('client_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('verdict_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('channel', sa.String(length=50), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['verdict_id'], ['verdicts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_alerts_sent_client_id'), 'alerts_sent', ['client_id'], unique=False)
    op.create_index(op.f('ix_alerts_sent_verdict_id'), 'alerts_sent', ['verdict_id'], unique=False)

    op.create_table(
        'scan_runs',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('client_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('scanned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('record_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_scan_runs_client_id'), 'scan_runs', ['client_id'], unique=False)
    op.create_index(op.f('ix_scan_runs_scanned_at'), 'scan_runs', ['scanned_at'], unique=False)
