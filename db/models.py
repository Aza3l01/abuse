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
    __tablename__ = "clients"

    id                      = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email                   = Column(String(255), unique=True, nullable=False, index=True)
    password_hash           = Column(Text, nullable=True)        # NULL for OAuth-only accounts
    company_name            = Column(String(255), nullable=False)

    # S3 ingestion config
    s3_bucket               = Column(String(255), nullable=True)
    s3_prefix               = Column(String(255), nullable=True)
    log_format              = Column(String(50), nullable=True)  # 'apigw' | 'alb'
    aws_region              = Column(String(50), nullable=True)
    last_processed_key      = Column(Text, nullable=True)        # S3 key of last read object

    # Blocking config
    waf_ip_set_id           = Column(String(255), nullable=True)
    cloudflare_zone_id      = Column(String(255), nullable=True)
    cloudflare_token        = Column(Text, nullable=True)

    # Alerts
    alert_email             = Column(String(255), nullable=True)

    # Subscription tier
    tier                    = Column(String(20), nullable=False, default="free")
    # free | starter | growth | pro

    # Billing (Stripe)
    stripe_customer_id      = Column(String(255), nullable=True, unique=True)
    stripe_subscription_id  = Column(String(255), nullable=True, unique=True)
    tier_expires_at         = Column(DateTime(timezone=True), nullable=True)

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

    created_at              = Column(DateTime(timezone=True), nullable=False, default=_now)

    # Relationships
    oauth_accounts   = relationship("OAuthAccount",   back_populates="client", cascade="all, delete-orphan")
    refresh_tokens   = relationship("RefreshToken",   back_populates="client", cascade="all, delete-orphan")
    verdicts         = relationship("Verdict",         back_populates="client", cascade="all, delete-orphan")
    ip_memories      = relationship("IpMemory",        back_populates="client", cascade="all, delete-orphan")
    alerts_sent      = relationship("AlertSent",       back_populates="client", cascade="all, delete-orphan")
    mfa_backup_codes = relationship("MfaBackupCode",  back_populates="client", cascade="all, delete-orphan")


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
# OAuthAccount — links a social provider identity to a Client
# ---------------------------------------------------------------------------

class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="uq_oauth_provider_id"),
    )

    id          = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    client_id   = Column(UUID(as_uuid=False), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    provider    = Column(String(50), nullable=False)   # 'google' | 'github'
    provider_id = Column(String(255), nullable=False)  # subject / user ID from provider
    email       = Column(String(255), nullable=True)   # email as returned by provider
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)

    client = relationship("Client", back_populates="oauth_accounts")


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

    id               = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    client_id        = Column(UUID(as_uuid=False), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
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
    created_at       = Column(DateTime(timezone=True), nullable=False, default=_now)

    client      = relationship("Client", back_populates="verdicts")
    alerts_sent = relationship("AlertSent", back_populates="verdict", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# IpMemory — running profile of each IP seen per client (LTM)
# ---------------------------------------------------------------------------

class IpMemory(Base):
    __tablename__ = "ip_memory"
    __table_args__ = (
        UniqueConstraint("client_id", "ip", name="uq_ip_memory_client_ip"),
    )

    id             = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    client_id      = Column(UUID(as_uuid=False), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    ip             = Column(String(45), nullable=False, index=True)
    first_seen     = Column(DateTime(timezone=True), nullable=False)
    last_seen      = Column(DateTime(timezone=True), nullable=False)
    total_requests = Column(Integer, nullable=False, default=0)
    threat_count   = Column(Integer, nullable=False, default=0)
    risk_score     = Column(Float, nullable=False, default=0.0)  # 0.0 – 1.0
    geo_country    = Column(String(10), nullable=True)           # ISO 3166-1 alpha-2
    notes          = Column(Text, nullable=True)

    client = relationship("Client", back_populates="ip_memories")


# ---------------------------------------------------------------------------
# AlertSent — record of every notification dispatched
# ---------------------------------------------------------------------------

class AlertSent(Base):
    __tablename__ = "alerts_sent"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    client_id  = Column(UUID(as_uuid=False), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    verdict_id = Column(UUID(as_uuid=False), ForeignKey("verdicts.id", ondelete="CASCADE"), nullable=False, index=True)
    channel    = Column(String(50), nullable=False)   # 'email' | 'slack'
    sent_at    = Column(DateTime(timezone=True), nullable=False, default=_now)
    status     = Column(String(50), nullable=False)   # 'sent' | 'failed'

    client  = relationship("Client",  back_populates="alerts_sent")
    verdict = relationship("Verdict", back_populates="alerts_sent")
