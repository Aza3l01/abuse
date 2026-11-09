"""pytest configuration for workers/tests.

test_process_logs.py is a standalone script with its own runner (it defines a
helper named `test(name, fn)`, which pytest would try to collect as a test and
fail on). It stays runnable the way its own docstring says
(`python workers/tests/test_process_logs.py`), pytest just does not collect it.
"""
from __future__ import annotations

import pytest

from api.tests.billing_testkit import capture_notifications, make_session_factory

collect_ignore = ["test_process_logs.py"]


@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    """Queued billing emails, recorded instead of sent (no broker in tests)."""
    return capture_notifications(monkeypatch)


@pytest.fixture
def session_factory():
    return make_session_factory()


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
