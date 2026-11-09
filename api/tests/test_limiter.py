"""Rate limiter coverage (Phase 10). The production limiter stores counts in
Redis, which tests do not have, so the behaviour tests build a Limiter with the
same settings on memory:// storage. A separate test checks the production
instance's own settings, and that the routes the security review relies on
carry a limit."""
# No `from __future__ import annotations` here: slowapi's decorator needs the
# real Request annotation on the route function.
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import api.main as main_module
from api.limiter import limiter as production_limiter

SECRET = "tok_PLAINTEXT_SECRET_123"


def _app() -> tuple[TestClient, Limiter]:
    limiter = Limiter(key_func=get_remote_address, storage_uri="memory://", key_style="endpoint")
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, main_module._rate_limit_handler)

    @app.post("/login")
    @limiter.limit("3/minute")
    def login(request: Request):
        return {"ok": True}

    @app.post("/other")
    @limiter.limit("3/minute")
    def other(request: Request):
        return {"ok": True}

    @app.post("/invite/{token}/accept")
    @limiter.limit("3/minute")
    def accept(request: Request, token: str):
        return {"ok": True}

    return TestClient(app), limiter


def test_requests_over_the_limit_get_429_in_the_api_error_shape():
    client, _ = _app()
    assert [client.post("/login").status_code for _ in range(3)] == [200, 200, 200]
    blocked = client.post("/login")
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many attempts. Please wait a few minutes and try again."}


def test_each_route_has_its_own_bucket():
    client, _ = _app()
    for _ in range(4):
        client.post("/login")
    assert client.post("/login").status_code == 429
    assert client.post("/other").status_code == 200


def test_a_secret_in_the_path_never_reaches_the_storage_key():
    client, limiter = _app()
    assert client.post(f"/invite/{SECRET}/accept").status_code == 200
    keys = list(limiter._storage.storage.keys())
    assert keys, "the limiter stored nothing"
    assert not any(SECRET in key for key in keys)


def test_the_window_is_enforced_per_path_value_under_one_bucket():
    # key_style="endpoint": every token shares the endpoint's bucket, so
    # rotating the token in the URL does not reset the count.
    client, _ = _app()
    codes = [client.post(f"/invite/token{i}/accept").status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_production_limiter_is_shared_and_secret_free():
    assert production_limiter._key_style == "endpoint"
    assert production_limiter._storage_uri.startswith("redis")


@pytest.mark.parametrize(
    "prefix, minimum",
    [("api.routes.auth.", 8), ("api.routes.org.", 9), ("api.routes.newsletter.", 1)],
)
def test_sensitive_route_modules_carry_limits(prefix, minimum):
    limited = [name for name in production_limiter._route_limits if name.startswith(prefix)]
    assert len(limited) >= minimum, limited
