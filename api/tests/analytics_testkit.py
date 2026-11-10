"""Shared helpers for the Phase 11 analytics tests (api/tests and workers/tests).

A recording stand-in replaces the PostHog client and a dict replaces Redis, so
no test touches the network. Nothing here ever sees a real key.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from api import analytics  # noqa: E402
from db.models import Client, OrganizationMember  # noqa: E402


class FakePostHog:
    """The slice of posthog.Posthog that api.analytics uses."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str | None, dict]] = []
        self.errors: list[tuple[BaseException, dict]] = []
        self.flushes = 0
        self.fail = False

    def capture(self, event, distinct_id=None, properties=None):
        if self.fail:
            raise RuntimeError("posthog is down")
        self.events.append((event, distinct_id, properties or {}))

    def capture_exception(self, exc, properties=None):
        if self.fail:
            raise RuntimeError("posthog is down")
        self.errors.append((exc, properties or {}))

    def flush(self):
        self.flushes += 1

    def named(self, event: str) -> list[tuple[str, str | None, dict]]:
        return [e for e in self.events if e[0] == event]


class FakeRedis:
    """SET NX EX only. `down` makes every call raise, like an outage."""

    def __init__(self) -> None:
        self.keys: dict[str, str] = {}
        self.down = False

    def set(self, key, value, nx=False, ex=None):
        if self.down:
            raise ConnectionError("redis is down")
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True


def install(monkeypatch, enabled: bool = True) -> tuple[FakePostHog, FakeRedis]:
    """Point api.analytics at the fakes. enabled=False models a blank key."""
    fake, fake_redis = FakePostHog(), FakeRedis()
    monkeypatch.setenv("POSTHOG_API_KEY", "phc_test_key" if enabled else "")
    monkeypatch.setattr(analytics, "_get_client", lambda: fake if analytics.enabled() else None)
    monkeypatch.setattr(analytics, "_client", fake)
    monkeypatch.setattr(analytics, "_client_pid", os.getpid())
    monkeypatch.setattr(analytics, "_redis", fake_redis)
    return fake, fake_redis


def add_owner(db, org, email: str = "owner@example.test") -> str:
    """Give `org` an owner and return the owner's Client id."""
    client = Client(email=email, full_name="Owner Person")
    db.add(client)
    db.commit()
    db.add(OrganizationMember(client_id=client.id, org_id=org.id, role="owner"))
    db.commit()
    return client.id
