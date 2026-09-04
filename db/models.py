import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship

from db.session import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Client — one row per paying customer
# ---------------------------------------------------------------------------

class Client(Base):
    """A login identity. Holds NO org/tenant config — that all lives on
    Organization now (Phase 2). One Client can belong to multiple
    Organizations via OrganizationMember.
    """
    __tablename__ = "clients"

    id                      = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email                   = Column(String(255), unique=True, nullable=False, index=True)
    password_hash           = Column(Text, nullable=True)        # NULL for OAuth-only accounts
    full_name                = Column(String(255), nullable=False)

    # Item 12: registration ToS+Privacy checkbox acceptance timestamp
    tos_accepted_at          = Column(DateTime(timezone=True), nullable=True)

    # Item 10 Step 3: MFA setup nudge banner, dismissed once so it doesn't repeat
    mfa_nudge_dismissed_at   = Column(DateTime(timezone=True), nullable=True)

    # Auth state
    email_verified          = Column(Boolean, nullable=False, default=False)
    mfa_enabled             = Column(Boolean, nullable=False, default=False)
    mfa_secret              = Column(Text, nullable=True)        # AES-encrypted TOTP seed

    # Email verification OTP (hashed)
    verify_token            = Column(Text, nullable=True)
    verify_token_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Password-reset OTP (hashed)
    reset_token_hash        = Column(Text, nullable=True)
    reset_token_expires_at  = Column(DateTime(timezone=True), nullable=True)

    # Item 40: DPDP account deletion. Soft-delete marker; email is anonymized
    # to deleted-{id}@deleted.clew at the same time this is set. A daily Beat
    # task hard-deletes rows where this is older than 30 days.
    deleted_at               = Column(DateTime(timezone=True), nullable=True)

    created_at              = Column(DateTime(timezone=True), nullable=False, default=_now)

    # Relationships
    refresh_tokens   = relationship("RefreshToken",   back_populates="client", cascade="all, delete-orphan")
    mfa_backup_codes = relationship("MfaBackupCode",  back_populates="client", cascade="all, delete-orphan")
    org_memberships  = relationship("OrganizationMember", back_populates="client", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Organization — one row per tenant. Holds all S3/blocking/billing config
# and detection data ownership (Phase 2 org/multi-user refactor).
# ---------------------------------------------------------------------------

class Organization(Base):
    __tablename__ = "organizations"

    id                         = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    company_name               = Column(String(255), nullable=False)
    # Extracted from the owner's email at registration (e.g. "acme.com");
    # used for domain-based invite role ceiling checks. Editable by the owner.
    domain                     = Column(String(255), nullable=True)

    # S3 ingestion config
    s3_bucket                  = Column(String(255), nullable=True)
    s3_prefix                  = Column(String(255), nullable=True)
    log_format                 = Column(String(50), nullable=True)  # 'apigw' | 'alb'
    aws_region                 = Column(String(50), nullable=True)
    last_processed_key         = Column(Text, nullable=True)        # S3 key of last read object
    s3_connected_at            = Column(DateTime(timezone=True), nullable=True)  # first successful S3 config save

    # Item 5: set when first-poll log format auto-detection finds a mismatch
    # (org selected apigw/alb but the bucket holds the other format).
    # NULL | 'error'. s3_status_message is the user-facing explanation.
    s3_status                  = Column(String(20), nullable=True)
    s3_status_message          = Column(Text, nullable=True)

    # Item 45 Gap A: status of the one-off silent calibration pass over the
    # last 24h of logs, run on first S3 connection to seed LTM thresholds
    # before live detection starts. NULL | 'running' | 'done' | 'failed'.
    calibration_status         = Column(String(20), nullable=True)

    # Item 16's "last scanned at" indicator (populated starting Phase 4).
    last_scan_completed_at     = Column(DateTime(timezone=True), nullable=True)
    last_scan_status           = Column(String(20), nullable=True)  # success | error | in_progress
    last_scan_error            = Column(Text, nullable=True)

    # Tenant's expected home country (ISO 3166-1 alpha-2), used by GeoIPAgent
    # to tell foreign concentration apart from normal home-country traffic.
    home_country               = Column(String(2), nullable=True)

    # Blocking config
    waf_ip_set_id              = Column(String(255), nullable=True)
    cloudflare_zone_id         = Column(String(255), nullable=True)
    cloudflare_token           = Column(Text, nullable=True)
    blocking_tos_accepted_at   = Column(DateTime(timezone=True), nullable=True)

    # Alerts
    alert_email                = Column(String(255), nullable=True)
    # Item 22: All threats | high_critical_only. Filters which severities send email.
    alert_severity_threshold   = Column(String(20), nullable=False, default="all")

    # Subscription tier
    tier                        = Column(String(20), nullable=False, default="free")
    # free | starter | growth | pro

    # Item 11: trial billing — set once at registration, never recalculated
    trial_source                 = Column(String(20), nullable=True)   # self_serve | manual_outreach
    trial_ends_at                = Column(DateTime(timezone=True), nullable=True)
    pilot_code_used               = Column(String(50), nullable=True)
    trial_reminder_5d_sent        = Column(Boolean, nullable=False, default=False)
    trial_reminder_2d_sent        = Column(Boolean, nullable=False, default=False)

    # Billing
    billing_provider            = Column(String(20), nullable=True)   # stripe | razorpay | pilot
    stripe_customer_id          = Column(String(255), nullable=True, unique=True)
    stripe_subscription_id      = Column(String(255), nullable=True, unique=True)
    tier_expires_at              = Column(DateTime(timezone=True), nullable=True)
    pilot_tier                   = Column(String(20), nullable=True)
    payment_method_display       = Column(String(255), nullable=True)
    gstin                        = Column(String(20), nullable=True)

    # Item 29: Razorpay (INR) subscription identifiers
    razorpay_customer_id        = Column(String(255), nullable=True, unique=True)
    razorpay_subscription_id    = Column(String(255), nullable=True, unique=True)

    # Item 29b: calendar-anchored billing. first_charged_at is set once, on
    # the first successful payment.captured/invoice.paid event, never
    # overwritten again: it anchors the 72hr refund remorse window.
    next_billing_date           = Column(DateTime(timezone=True), nullable=True)
    first_charged_at            = Column(DateTime(timezone=True), nullable=True)

    # Usage tracking (populated starting Phase 4)
    monthly_requests_processed   = Column(Integer, nullable=False, default=0)
    monthly_requests_reset_at    = Column(DateTime(timezone=True), nullable=True)

    # Item 40: set when the org's owner deletes their account. The whole org
    # (and every member's access to it) goes away with the owner, since there
    # is no ownership-transfer feature to avoid this. Hard-deleted after 30
    # days alongside the Client, same as deleted_at on Client.
    deleted_at                   = Column(DateTime(timezone=True), nullable=True)

    created_at                   = Column(DateTime(timezone=True), nullable=False, default=_now)

    # Relationships
    members     = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")
    invites     = relationship("OrgInvite",           back_populates="organization", cascade="all, delete-orphan")
    verdicts    = relationship("Verdict",              back_populates="organization", cascade="all, delete-orphan")
    ip_memories = relationship("IpMemory",             back_populates="organization", cascade="all, delete-orphan")
    alerts_sent = relationship("AlertSent",            back_populates="organization", cascade="all, delete-orphan")
    scan_runs   = relationship("ScanRun",              back_populates="organization", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# OrganizationMember — many-to-many join: a Client's role within an Organization
# ---------------------------------------------------------------------------

class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("client_id", "org_id", name="uq_org_member_client_org"),
    )

    id         = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    client_id  = Column(UUID(as_uuid=False), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id     = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    role       = Column(String(20), nullable=False, default="owner")  # owner | admin | viewer
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    client       = relationship("Client",       back_populates="org_memberships")
    organization = relationship("Organization", back_populates="members")


# ---------------------------------------------------------------------------
# PromoCode (item 26). 100 single-use launch codes, redeemed at registration
# (not at checkout). Rows are never deleted, only marked redeemed, so usage
# can always be audited by who/when.
# ---------------------------------------------------------------------------

class PromoCode(Base):
    __tablename__ = "promo_codes"

    id                          = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    code                         = Column(String(50), nullable=False, unique=True, index=True)
    # Linked Stripe coupon / Razorpay offer, applied at eventual checkout so
    # the discount still lands on the org's first invoice. Filled in by the
    # launch script when the corresponding provider object exists; may stay
    # NULL until linked manually (not required at redemption time).
    provider_coupon_id_stripe    = Column(String(255), nullable=True)
    provider_offer_id_razorpay   = Column(String(255), nullable=True)
    redeemed_at                  = Column(DateTime(timezone=True), nullable=True)
    redeemed_by_org_id           = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    created_at                   = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# OrgInvite — single-use, directed invite token (no shareable public links)
# ---------------------------------------------------------------------------

class OrgInvite(Base):
    __tablename__ = "org_invites"

    id            = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    org_id        = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    invited_email = Column(String(255), nullable=False, index=True)
    role          = Column(String(20), nullable=False)   # admin | viewer
    token_hash    = Column(Text, nullable=False, unique=True)
    expires_at    = Column(DateTime(timezone=True), nullable=False)
    accepted_at   = Column(DateTime(timezone=True), nullable=True)
    created_at    = Column(DateTime(timezone=True), nullable=False, default=_now)

    organization = relationship("Organization", back_populates="invites")


# ---------------------------------------------------------------------------
# MfaBackupCode — one row per single-use recovery code
# ---------------------------------------------------------------------------

class MfaBackupCode(Base):
    __tablename__ = "mfa_backup_codes"

    id          = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    client_id   = Column(UUID(as_uuid=False), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash   = Column(Text, nullable=False)           # SHA-256 of the raw code
    used        = Column(Boolean, nullable=False, default=False)
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)

    client = relationship("Client", back_populates="mfa_backup_codes")


# ---------------------------------------------------------------------------
# RefreshToken — one row per active session, enables per-device revocation
# ---------------------------------------------------------------------------

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id          = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    client_id   = Column(UUID(as_uuid=False), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash  = Column(Text, nullable=False, unique=True)  # SHA-256 of the raw token
    issued_at   = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at  = Column(DateTime(timezone=True), nullable=False)
    revoked     = Column(Boolean, nullable=False, default=False)
    user_agent  = Column(Text, nullable=True)
    ip          = Column(String(45), nullable=True)  # IPv4 or IPv6

    client = relationship("Client", back_populates="refresh_tokens")


# ---------------------------------------------------------------------------
# Verdict — one detection result per analysed log entry
# ---------------------------------------------------------------------------

class Verdict(Base):
    __tablename__ = "verdicts"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "source_key",
            name="uq_verdicts_org_source_key",
        ),
    )

    id               = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    org_id           = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp        = Column(DateTime(timezone=True), nullable=False, index=True)
    ip               = Column(String(45), nullable=False, index=True)
    method           = Column(String(10), nullable=True)
    endpoint         = Column(Text, nullable=True)
    threat_type      = Column(String(100), nullable=True)
    severity         = Column(String(20), nullable=False)   # low | medium | high | critical
    confidence       = Column(Float, nullable=False)        # 0.0 – 1.0
    agents_triggered = Column(JSON, nullable=True)          # list of agent names
    explanation      = Column(Text, nullable=True)
    blocked          = Column(Boolean, nullable=False, default=False)
    cost_prevented   = Column(Float, nullable=True)         # estimated USD
    # Item 3: S3 object key that produced this verdict (Pass A only — Pass B's
    # focus verdicts span records from multiple objects, left NULL). Defense in
    # depth against reprocessing the same file twice (e.g. after a Redis outage
    # defeats item 2's lock): re-derived deterministically as "{key}:{offset}"
    # of the batch's first record, so re-running the same objects in the same
    # order reproduces the same key and the unique constraint blocks the dupe.
    source_key       = Column(Text, nullable=True)
    # Item 19: up to 5 raw log lines from this batch (JSON array), truncated
    # at 512 chars each. No true per-record suspicion score exists in the
    # engine, approximated by preferring lines matching this verdict's ip/
    # endpoint, padded with the batch's first lines. Documented limitation.
    sample_logs      = Column(JSON, nullable=True)
    # Item 19: per-agent score table: [{agent_name, score, triggered}, ...],
    # all 6 active agents (KnowledgeAgent is passive, excluded), including
    # ones that didn't fire (score 0). `agents_triggered` only ever held the
    # triggered subset, not a full per-agent score breakdown.
    agent_scores     = Column(JSON, nullable=True)
    created_at       = Column(DateTime(timezone=True), nullable=False, default=_now)

    organization = relationship("Organization", back_populates="verdicts")
    alerts_sent  = relationship("AlertSent", back_populates="verdict", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# IpMemory — running profile of each IP seen per client (LTM)
# ---------------------------------------------------------------------------

class IpMemory(Base):
    __tablename__ = "ip_memory"
    __table_args__ = (
        UniqueConstraint("org_id", "ip", name="uq_ip_memory_org_ip"),
    )

    id             = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    org_id         = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    ip             = Column(String(45), nullable=False, index=True)
    first_seen     = Column(DateTime(timezone=True), nullable=False)
    last_seen      = Column(DateTime(timezone=True), nullable=False)
    total_requests = Column(Integer, nullable=False, default=0)
    threat_count   = Column(Integer, nullable=False, default=0)
    risk_score     = Column(Float, nullable=False, default=0.0)  # 0.0 – 1.0
    geo_country    = Column(String(10), nullable=True)           # ISO 3166-1 alpha-2
    # Item 32: GeoLite2-ASN, provider/network owner of this IP.
    geo_asn_number = Column(Integer, nullable=True)
    geo_asn_org    = Column(String(255), nullable=True)          # e.g. "DigitalOcean, LLC"
    notes          = Column(Text, nullable=True)

    # Item 21: WAF/Cloudflare are updated independently, one can succeed
    # while the other fails, so blocked state is never a single bool.
    waf_blocked           = Column(Boolean, nullable=False, default=False)
    cloudflare_blocked     = Column(Boolean, nullable=False, default=False)
    waf_block_error        = Column(Text, nullable=True)
    cloudflare_block_error = Column(Text, nullable=True)

    organization = relationship("Organization", back_populates="ip_memories")


# ---------------------------------------------------------------------------
# AlertSent — record of every notification dispatched
# ---------------------------------------------------------------------------

class AlertSent(Base):
    __tablename__ = "alerts_sent"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    org_id     = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    verdict_id = Column(UUID(as_uuid=False), ForeignKey("verdicts.id", ondelete="CASCADE"), nullable=False, index=True)
    channel    = Column(String(50), nullable=False)   # 'email' | 'slack'
    sent_at    = Column(DateTime(timezone=True), nullable=False, default=_now)
    status     = Column(String(50), nullable=False)   # 'sent' | 'failed' | 'bounced' (item 20's delivery_status)
    # Item 20: populated when status='failed'. 'bounced' is a fast-follow via
    # Resend's webhook (item 25), not wired up yet, column exists for it.
    delivery_error = Column(Text, nullable=True)

    organization = relationship("Organization", back_populates="alerts_sent")
    verdict      = relationship("Verdict",      back_populates="alerts_sent")


# ---------------------------------------------------------------------------
# ScanRun — evidence that a batch was scanned and found clean (item 5e).
#
# Benign batches used to write a Verdict row with severity="none", which is
# undocumented, unfilterable via the severity column, and shows up in the
# alerts feed as a clean scan. This table is the "we scanned and found
# nothing" evidence trail instead — `verdicts` stays reserved for actual
# detections. Used by item 16's "last scanned at" indicator.
# ---------------------------------------------------------------------------

class ScanRun(Base):
    __tablename__ = "scan_runs"

    id           = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    org_id       = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    scanned_at   = Column(DateTime(timezone=True), nullable=False, index=True)  # window's own timestamp, not wall-clock
    record_count = Column(Integer, nullable=False, default=0)
    created_at   = Column(DateTime(timezone=True), nullable=False, default=_now)

    organization = relationship("Organization", back_populates="scan_runs")
