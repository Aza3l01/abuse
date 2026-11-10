import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint,
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
    password_hash           = Column(Text, nullable=True)        # nullable in the schema; every current signup path sets it
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
    last_scan_status           = Column(String(20), nullable=True)  # success | error | in_progress | paused
    last_scan_error            = Column(Text, nullable=True)
    # Item 60: set whenever last_scan_status is set to in_progress, read by
    # the next poll's stale-scan sweep to detect a worker that died mid-scan
    # (OOM, PM2 restart, deploy) without ever reaching the except/finally block.
    last_scan_started_at       = Column(DateTime(timezone=True), nullable=True)

    # Tenant's expected home country (ISO 3166-1 alpha-2), used by GeoIPAgent
    # to tell foreign concentration apart from normal home-country traffic.
    home_country               = Column(String(2), nullable=True)

    # Blocking config
    waf_ip_set_id              = Column(String(255), nullable=True)
    cloudflare_zone_id         = Column(String(255), nullable=True)
    cloudflare_token           = Column(Text, nullable=True)
    blocking_tos_accepted_at   = Column(DateTime(timezone=True), nullable=True)
    # TODO.md priority item 2: explicit opt-in for the unattended
    # pipeline-triggered block, on top of AUTO_BLOCK_TIERS and
    # blocking_tos_accepted_at. Off by default for every org.
    auto_block_enabled         = Column(Boolean, nullable=False, default=False)
    # Phase 8: with auto_block_enabled on, log "would have blocked" on the
    # verdict instead of touching the customer's edge.
    auto_block_dry_run         = Column(Boolean, nullable=False, default=False, server_default="false")
    # Phase 8: Pro/Enterprise detection tuning (api/detection_config.py
    # validates the shape). NULL means engine defaults. Ignored, not deleted,
    # when the tier is not eligible.
    detection_config           = Column(JSON, nullable=True)

    # Phase 2: cross-account IAM role, replaces the shared long-lived
    # AWS credential. aws_external_id is generated by Clew at org creation
    # (secrets.token_urlsafe(32)), never chosen by the customer. Both are
    # nullable so orgs without a role fall back to the shared credential
    # (api/aws.py's aws_session_for_org).
    aws_role_arn                = Column(String(255), nullable=True)
    aws_external_id             = Column(String(64), nullable=True)

    # Phase 4 (section 4c): guided onboarding state. Two columns, not one,
    # dismissed means stop auto-opening the wizard, completed means stop
    # showing the prompt at all. Per-step progress is derived from live org
    # state (s3_bucket set, home_country set, etc.), never stored here.
    onboarding_completed_at     = Column(DateTime(timezone=True), nullable=True)
    onboarding_dismissed_at     = Column(DateTime(timezone=True), nullable=True)

    # Alerts
    alert_email                = Column(String(255), nullable=True)
    # Item 22: All threats | high_critical_only. Filters which severities send email.
    alert_severity_threshold   = Column(String(20), nullable=False, default="all")

    # Subscription tier
    tier                        = Column(String(20), nullable=False, default="starter")
    # starter (free) | basic | growth | pro | enterprise

    # Item 11: trial billing — set once at registration, never recalculated
    trial_source                 = Column(String(20), nullable=True)   # self_serve | manual_outreach
    trial_ends_at                = Column(DateTime(timezone=True), nullable=True)
    pilot_code_used               = Column(String(50), nullable=True)
    trial_reminder_5d_sent        = Column(Boolean, nullable=False, default=False)
    trial_reminder_2d_sent        = Column(Boolean, nullable=False, default=False)

    # TODO.md priority item 5: set when this org signed up using someone
    # else's referral code (never an admin pilot code). Phase 12: the org's
    # first generated bill is free and the referrer earns a credit (Credit).
    referred_by_promo_code_id     = Column(UUID(as_uuid=False), ForeignKey("promo_codes.id", ondelete="SET NULL"), nullable=True)

    # Billing
    billing_provider            = Column(String(20), nullable=True)   # stripe | razorpay | pilot
    stripe_customer_id          = Column(String(255), nullable=True, unique=True)
    stripe_subscription_id      = Column(String(255), nullable=True, unique=True)
    tier_expires_at              = Column(DateTime(timezone=True), nullable=True)
    pilot_tier                   = Column(String(20), nullable=True)
    payment_method_display       = Column(String(255), nullable=True)
    gstin                        = Column(String(20), nullable=True)

    # Item 29b: calendar-anchored billing. first_charged_at is set once, on
    # the first successful payment.captured/invoice.paid event, never
    # overwritten again: it anchors the 72hr refund remorse window.
    next_billing_date           = Column(DateTime(timezone=True), nullable=True)
    first_charged_at            = Column(DateTime(timezone=True), nullable=True)

    # Phase 3 (bill-then-pay with Razorpay Orders). next_billing_date now means
    # the next bill ISSUE date (an IST midnight instant, always the 1st of a
    # month); first_charged_at means the first captured payment. The
    # columns below are read and written only through
    # api/billing_rules.py and workers/tasks/billing_cycle.py.
    billing_period              = Column(String(10), nullable=True)   # monthly | annual
    cancel_at_period_end        = Column(Boolean, nullable=False, default=False)
    # A scheduled downgrade (lower tier or annual to monthly), applied when
    # the next bill is issued.
    pending_tier                = Column(String(20), nullable=True)
    pending_period              = Column(String(10), nullable=True)
    # Set only by a non-payment downgrade: open bills remain and Restore is
    # offered. Cleared by the Phase 4 restore.
    nonpayment_downgraded_at    = Column(DateTime(timezone=True), nullable=True)
    # 30 day retention grace after any downgrade: the old tier's retention
    # window keeps applying until retention_grace_until (effective_retention_tier).
    retention_grace_tier        = Column(String(20), nullable=True)
    retention_grace_until       = Column(DateTime(timezone=True), nullable=True)
    # Who receives billing emails: owner(s) | selected members | all members.
    billing_emails_mode         = Column(String(10), nullable=False, default="owner")
    # Routine emails (bill ready, due in 3 days) only. The cancel warning and
    # the cancelled notice always go out.
    billing_reminders_enabled   = Column(Boolean, nullable=False, default=True)
    billing_legal_name          = Column(String(255), nullable=True)
    billing_address             = Column(Text, nullable=True)
    # Phase 5 section C: the org's billing country (ISO 3166-1 alpha-2) and the
    # currency it implies (INR for IN, USD for everywhere else). Both are set
    # together, once, at the first checkout or on the billing details form,
    # and never change afterwards (a support action). billing_country is NULL
    # until then, which is how "not yet chosen" is told apart from the USD
    # default. Every bill and payment of the org is in this currency.
    billing_currency            = Column(String(3), nullable=False, default="USD")
    billing_country             = Column(String(2), nullable=True)

    # Usage tracking (populated starting Phase 4)
    monthly_requests_processed   = Column(Integer, nullable=False, default=0)
    # Phase 2: LLM calls attempted this month (cost guardrail, capped per
    # tier by api/tiers.py LLM_CALL_CAPS). Reset with the request counter.
    monthly_llm_calls            = Column(Integer, nullable=False, default=0)
    monthly_requests_reset_at    = Column(DateTime(timezone=True), nullable=True)
    # Item 30 (section 5): idempotency flags for the 80%/100% soft-limit
    # emails, cleared alongside monthly_requests_processed by
    # reset_monthly_counters so each billing month can re-trigger both once.
    quota_warning_sent_at        = Column(DateTime(timezone=True), nullable=True)
    quota_exceeded_sent_at       = Column(DateTime(timezone=True), nullable=True)

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
    # Phase 3: member selected to receive billing emails when the org's
    # billing_emails_mode is 'selected'.
    is_billing_contact = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    client       = relationship("Client",       back_populates="org_memberships")
    organization = relationship("Organization", back_populates="members")


# ---------------------------------------------------------------------------
# PromoCode (item 26, extended by TODO.md priority item 5). Dual-purpose
# "code" concept, not two separate mechanisms: kind="admin" is the original
# 100 single-use launch codes, redeemed at registration (not at checkout),
# rows never deleted, only marked redeemed via redeemed_at/redeemed_by_org_id
# so usage can always be audited. kind="referral" is a code auto-generated
# for a regular org (owner_org_id set, no redemption cap) that any other org
# can redeem, tracked via the separate PromoCodeRedemption table below since
# a referral code is reused by up to max_redemptions different orgs, unlike
# an admin code's single redeemed_at/redeemed_by_org_id pair.
# ---------------------------------------------------------------------------

class PromoCode(Base):
    __tablename__ = "promo_codes"

    id                          = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    code                         = Column(String(50), nullable=False, unique=True, index=True)
    # "admin" (founder-generated pilot code) | "referral" (auto-generated,
    # one per org, shareable). Only admin codes ever use redeemed_at/
    # redeemed_by_org_id below; referral codes use PromoCodeRedemption.
    kind                         = Column(String(20), nullable=False, default="admin")
    # Set only for kind="referral": the org this code belongs to and shares.
    # NULL for kind="admin" (founder-owned, not tied to any one org). Phase 12:
    # SET NULL, not CASCADE, so purging a referrer keeps the code row and its
    # redemptions (the referees keep their attribution). A referral code whose
    # owner is NULL or deleted refuses new signups (api/referrals.py).
    owner_org_id                 = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    # 1 for admin codes (single-use). Phase 12: referral codes have no cap, the
    # column is only enforced for admin codes.
    max_redemptions              = Column(Integer, nullable=False, default=1)
    # Linked Stripe coupon / Razorpay offer, applied at eventual checkout so
    # the discount still lands on the org's first invoice. Filled in by the
    # launch script when the corresponding provider object exists; may stay
    # NULL until linked manually (not required at redemption time). Admin
    # codes only; referral discounts are computed in code, not via a linked
    # provider object.
    provider_coupon_id_stripe    = Column(String(255), nullable=True)
    provider_offer_id_razorpay   = Column(String(255), nullable=True)
    redeemed_at                  = Column(DateTime(timezone=True), nullable=True)
    redeemed_by_org_id           = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    created_at                   = Column(DateTime(timezone=True), nullable=False, default=_now)

    redemptions = relationship("PromoCodeRedemption", back_populates="promo_code", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# PromoCodeRedemption (TODO.md priority item 5). One row per org that
# redeemed a referral-kind PromoCode (an admin code's single redemption
# still goes through PromoCode.redeemed_at/redeemed_by_org_id above, not
# here). first_payment_confirmed_at is set only once the redeeming org's
# first payment is genuinely captured, never at redemption/signup time. It is
# the marker the referral credit ledger (Credit, api/referrals.py) keys on.
# ---------------------------------------------------------------------------

class PromoCodeRedemption(Base):
    __tablename__ = "promo_code_redemptions"
    __table_args__ = (
        UniqueConstraint("promo_code_id", "redeemed_by_org_id", name="uq_promo_code_redemption_org"),
    )

    id                          = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    promo_code_id               = Column(UUID(as_uuid=False), ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    redeemed_by_org_id          = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    redeemed_at                 = Column(DateTime(timezone=True), nullable=False, default=_now)
    first_payment_confirmed_at  = Column(DateTime(timezone=True), nullable=True)

    promo_code = relationship("PromoCode", back_populates="redemptions")


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
    # Phase 8 dry-run: set when auto-block would have fired but dry-run was on.
    would_have_blocked_at = Column(DateTime(timezone=True), nullable=True)
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


# ---------------------------------------------------------------------------
# ProcessedWebhookEvent: item 62's replay/idempotency guard for the Razorpay
# and Stripe webhooks. Not org-scoped (a webhook event id is unique per
# provider regardless of which org it concerns), purged after 30 days by
# the same daily task that purges deleted accounts.
# ---------------------------------------------------------------------------

class ProcessedWebhookEvent(Base):
    __tablename__ = "processed_webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_processed_webhook_events_provider_event_id"),
    )

    id         = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    provider   = Column(String(20), nullable=False)   # razorpay | stripe
    event_id   = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, index=True)


# ---------------------------------------------------------------------------
# Phase 3 billing records. Bill, Payment and BillingEvent are financial
# records: they survive account deletion (org_id goes NULL via ON DELETE SET
# NULL, org_name_snapshot keeps who it was). No ORM relationship to
# Organization on purpose, so deleting an org never makes the ORM try to
# touch these rows; the database nulls org_id itself.
# ---------------------------------------------------------------------------

class Payment(Base):
    """One Razorpay order and, once captured, its payment. Created as
    status='created' before the checkout opens, moved to 'captured' only by
    apply_captured_payment (Phase 4).
    """
    __tablename__ = "payments"

    id                   = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    org_id               = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    org_name_snapshot    = Column(String(255), nullable=False)
    razorpay_order_id    = Column(String(255), nullable=False, unique=True)
    razorpay_payment_id  = Column(String(255), nullable=True, unique=True)
    amount_paise         = Column(Integer, nullable=False)   # minor units of `currency` (paise or cents)
    # No Python default on purpose: a payment must say which currency it is in.
    currency             = Column(String(3), nullable=False)   # INR | USD
    purpose              = Column(String(20), nullable=False)   # initial | upgrade | bill | restore
    status               = Column(String(20), nullable=False, default="created")  # created | captured | failed | refunded
    # What the amount pays for, for example the plan and the bill ids.
    line_items           = Column(JSON, nullable=True)
    tos_accepted         = Column(Boolean, nullable=False, default=False)
    # Billing details as they were at payment time, printed on the receipt.
    gstin_snapshot       = Column(String(20), nullable=True)
    legal_name_snapshot  = Column(String(255), nullable=True)
    address_snapshot     = Column(Text, nullable=True)
    created_at           = Column(DateTime(timezone=True), nullable=False, default=_now)
    captured_at          = Column(DateTime(timezone=True), nullable=True)
    refunded_at          = Column(DateTime(timezone=True), nullable=True)


class Bill(Base):
    """One bill per org per billing period. period_start is the issue date
    (the 1st), period_end is exclusive (the next bill date), due_date is the
    20th of the issue month, cancel_on is the 1st of the following month, when
    an unpaid bill downgrades the org. Dates are IST calendar dates.
    """
    __tablename__ = "bills"
    __table_args__ = (
        UniqueConstraint("org_id", "period_start", name="uq_bills_org_period_start"),
    )

    id                       = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    org_id                   = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    org_name_snapshot        = Column(String(255), nullable=False)
    tier                     = Column(String(20), nullable=False)
    period                   = Column(String(10), nullable=False)   # monthly | annual
    period_start             = Column(Date, nullable=False)
    period_end               = Column(Date, nullable=False)
    # What the customer owes: the plan price minus credit_applied_paise.
    amount_paise             = Column(Integer, nullable=False)
    # Phase 12: referral credit applied when the bill was issued. The plan
    # price is amount_paise + credit_applied_paise.
    credit_applied_paise     = Column(Integer, nullable=False, default=0, server_default="0")
    currency                 = Column(String(3), nullable=False)   # INR | USD, always the org's billing_currency
    status                   = Column(String(10), nullable=False, default="open")  # open | paid | void
    issued_at                = Column(DateTime(timezone=True), nullable=False, default=_now)
    due_date                 = Column(Date, nullable=False)
    cancel_on                = Column(Date, nullable=False)
    paid_at                  = Column(DateTime(timezone=True), nullable=True)
    payment_id               = Column(UUID(as_uuid=False), ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)
    # Idempotency markers for the three reminder emails (billing_cycle step 4).
    ready_notified_at        = Column(DateTime(timezone=True), nullable=True)
    due_reminder_sent_at     = Column(DateTime(timezone=True), nullable=True)
    cancel_reminder_sent_at  = Column(DateTime(timezone=True), nullable=True)


class Credit(Base):
    """Phase 12 referral credit ledger. A credit only ever reduces the earning
    org's own bills, it is never paid out. Rows are append-only apart from the
    status moves below and the split of a partly used credit.

    kind referrer_reward: earned by the referrer when the referee first pays.
    Starts pending, vests when the referee has paid a third period for real
    (held when the referrer vests too fast, until staff approves), then
    available until a bill uses it.
    kind referee_free_bill: the referee's free first bill. Written directly as
    applied, in the same transaction that issues the bill.

    status: pending | held | available | applied | revoked. amount_paise is in
    minor units of currency. A partly used credit is split: the used part
    becomes the applied row, the rest a new available row.
    """
    __tablename__ = "credits"

    id              = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    org_id          = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    kind            = Column(String(20), nullable=False)
    status          = Column(String(10), nullable=False, default="pending", index=True)
    amount_paise    = Column(Integer, nullable=False)
    currency        = Column(String(3), nullable=False)
    # The referee's plan, so the credit can be re-valued at list price in
    # another currency (no FX rate is ever used).
    basis_tier      = Column(String(20), nullable=True)
    basis_period    = Column(String(10), nullable=True)
    # The referee org behind a referrer_reward. SET NULL so a purge keeps the ledger.
    source_org_id   = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    redemption_id   = Column(UUID(as_uuid=False), ForeignKey("promo_code_redemptions.id", ondelete="SET NULL"), nullable=True)
    earned_at       = Column(DateTime(timezone=True), nullable=False, default=_now)
    vests_at        = Column(DateTime(timezone=True), nullable=True)
    held_reason     = Column(String(200), nullable=True)
    applied_at      = Column(DateTime(timezone=True), nullable=True)
    applied_bill_id = Column(UUID(as_uuid=False), ForeignKey("bills.id", ondelete="SET NULL"), nullable=True)
    revoked_at      = Column(DateTime(timezone=True), nullable=True)
    revoked_reason  = Column(String(200), nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, default=_now)


class BillingEvent(Base):
    """Append-only billing history. Churn and upgrades cannot be rebuilt from
    current state later, so every tier change writes a row here in the same
    transaction as the change. Phase 6 reads this for the metrics page.
    """
    __tablename__ = "billing_events"

    id          = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    org_id      = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    # first_paid | upgraded | downgraded | cancelled | nonpayment_downgrade |
    # trial_end | restored | refunded
    event       = Column(String(30), nullable=False)
    from_tier   = Column(String(20), nullable=True)
    to_tier     = Column(String(20), nullable=True)
    period      = Column(String(10), nullable=True)
    amount_paise = Column(Integer, nullable=True)
    # Currency of amount_paise; NULL when the event has no amount.
    currency    = Column(String(3), nullable=True)
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now, index=True)


# ---------------------------------------------------------------------------
# Phase 6 internal ops panel. StaffUser is a separate table from Client on
# purpose: a customer account can never become staff. Rows are created only by
# scripts/create_staff_user.py, never through an API endpoint.
# ---------------------------------------------------------------------------

class StaffUser(Base):
    __tablename__ = "staff_users"

    id            = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email         = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(Text, nullable=False)
    totp_secret   = Column(Text, nullable=False)   # Fernet-encrypted base32 seed
    # False until the CLI has seen one valid code, so a half-finished
    # enrolment can never log in.
    totp_active   = Column(Boolean, nullable=False, default=False)
    # Time step of the last accepted code: a code cannot be used twice.
    last_totp_step = Column(Integer, nullable=True)
    is_active     = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class StaffAuditLog(Base):
    """Append-only record of staff logins, raw data views and every write.
    The staff email and org name are copied onto the row so it stays readable
    after either is deleted."""
    __tablename__ = "staff_audit_log"

    id                = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    staff_id          = Column(UUID(as_uuid=False), ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True, index=True)
    staff_email       = Column(String(255), nullable=False)
    action            = Column(String(60), nullable=False, index=True)
    org_id            = Column(UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    org_name_snapshot = Column(String(255), nullable=True)
    reason            = Column(Text, nullable=True)
    details           = Column(JSON, nullable=True)
    ip                = Column(String(45), nullable=True)
    created_at        = Column(DateTime(timezone=True), nullable=False, default=_now, index=True)


class MetricsDaily(Base):
    """One snapshot row per (IST date, currency), written by the
    metrics_snapshot task. The global counts (users, orgs, pilots) are
    repeated on each currency row. Money columns are minor units of `currency`
    and are never altered. Ratios are not stored: they are derived from these
    counts (api/metrics.py). inr_per_usd is the fixed reporting rate (INR per
    1 USD) the row was written with, NULL when no valid rate was set; the
    combined INR figures are derived from the per-currency columns and this
    rate, so a past day keeps the rate it was computed with."""
    __tablename__ = "metrics_daily"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "currency", name="uq_metrics_daily_date_currency"),
    )

    id             = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    snapshot_date  = Column(Date, nullable=False, index=True)
    currency       = Column(String(3), nullable=False)

    users_total           = Column(Integer, nullable=False, default=0)
    users_verified        = Column(Integer, nullable=False, default=0)
    orgs_total            = Column(Integer, nullable=False, default=0)
    active_pilots         = Column(Integer, nullable=False, default=0)
    pilots_converted      = Column(Integer, nullable=False, default=0)
    pilots_expired_unpaid = Column(Integer, nullable=False, default=0)

    paying_orgs           = Column(Integer, nullable=False, default=0)
    paying_basic          = Column(Integer, nullable=False, default=0)
    paying_growth         = Column(Integer, nullable=False, default=0)
    paying_pro            = Column(Integer, nullable=False, default=0)
    mrr_minor             = Column(BigInteger, nullable=False, default=0)
    arr_minor             = Column(BigInteger, nullable=False, default=0)
    paying_orgs_start     = Column(Integer, nullable=False, default=0)
    mrr_start_minor       = Column(BigInteger, nullable=False, default=0)
    new_mrr_minor         = Column(BigInteger, nullable=False, default=0)
    expansion_mrr_minor   = Column(BigInteger, nullable=False, default=0)
    contraction_mrr_minor = Column(BigInteger, nullable=False, default=0)
    churned_mrr_minor     = Column(BigInteger, nullable=False, default=0)
    churned_orgs          = Column(Integer, nullable=False, default=0)
    refunds_count         = Column(Integer, nullable=False, default=0)
    refunds_minor         = Column(BigInteger, nullable=False, default=0)
    overdue_bills         = Column(Integer, nullable=False, default=0)
    overdue_minor         = Column(BigInteger, nullable=False, default=0)
    inr_per_usd           = Column(Numeric(12, 4), nullable=True)

    created_at     = Column(DateTime(timezone=True), nullable=False, default=_now)
