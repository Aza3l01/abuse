"""Shared helpers for the Phase 3 billing tests (api/tests and workers/tests).

An in-memory SQLite database is built from the real SQLAlchemy models, so the
billing engine and the purge task run against real ORM objects without needing
Postgres. SQLite drops time zone info on DateTime columns, which is why the
code under test treats a naive datetime as UTC (api.billing_rules.as_utc).

db.session and workers.celery_app read DATABASE_URL and REDIS_URL at import
time. Placeholders are set only when the variables are absent, nothing here
ever connects to them: the tests use their own SQLite engine.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from datetime import date, timezone  # noqa: E402

from sqlalchemy import DateTime, create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from api.billing_rules import ist_midnight  # noqa: E402
from db.models import Organization  # noqa: E402
from db.session import Base  # noqa: E402


def capture_notifications(monkeypatch) -> list[tuple]:
    """Replace the Celery enqueue behind api.billing_notify.notify with a
    recorder, so no test needs a broker. Each entry is (kind, org_id, bill_id,
    payment_id)."""
    import api.billing_notify as billing_notify

    sent: list[tuple] = []
    monkeypatch.setattr(
        billing_notify, "_enqueue", lambda kind, org_id, bill_id, payment_id: sent.append((kind, org_id, bill_id, payment_id))
    )
    return sent


def _restore_utc(target, *_args) -> None:
    """Give naive DateTime values read back from SQLite their UTC tzinfo, as
    Postgres's timestamptz columns do, so the code under test sees the same
    aware datetimes in tests as in production."""
    for column in target.__table__.columns:
        if isinstance(column.type, DateTime):
            value = target.__dict__.get(column.key)
            if value is not None and value.tzinfo is None:
                target.__dict__[column.key] = value.replace(tzinfo=timezone.utc)


event.listen(Base, "load", _restore_utc, propagate=True)
event.listen(Base, "refresh", _restore_utc, propagate=True)


def make_session_factory():
    """A fresh in-memory database with every model's table created. Matches
    production's session settings (no autoflush, no autocommit)."""
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def make_org(
    db,
    *,
    tier: str = "starter",
    period: str | None = "monthly",
    next_bill: date | None = None,
    name: str = "Acme",
    **extra,
) -> Organization:
    """Insert and return an org. `next_bill` is stored as an IST midnight,
    the way the billing engine stores it. Orgs default to the INR / India
    billing currency; pass billing_country=None, billing_currency="USD" for
    one that has not chosen yet."""
    org = Organization(**{
        "company_name": name,
        "tier": tier,
        "billing_period": period,
        "billing_provider": "razorpay" if tier != "free" else None,
        "next_billing_date": ist_midnight(next_bill) if next_bill else None,
        "billing_currency": "INR",
        "billing_country": "IN",
        **extra,
    })
    db.add(org)
    db.commit()
    return org
