"""Correlation id middleware: header on every response, id in error logs, JSON 500."""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.auth_utils import create_access_token
from api.correlation import CorrelationIdMiddleware
from api.main import app as real_app


def _small_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/denied")
    def denied():
        raise HTTPException(status_code=403, detail="No active organisation")

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    return app


def test_real_app_sets_header_and_does_not_change_body():
    res = TestClient(real_app).get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert len(res.headers["x-correlation-id"]) == 32


def test_each_request_gets_its_own_id():
    client = TestClient(_small_app())
    first = client.get("/ok").headers["x-correlation-id"]
    second = client.get("/ok").headers["x-correlation-id"]
    assert first != second


def test_inbound_header_is_ignored():
    res = TestClient(_small_app()).get("/ok", headers={"X-Correlation-Id": "attacker-value"})
    assert res.headers["x-correlation-id"] != "attacker-value"


def test_http_error_keeps_body_and_logs_id_and_org(caplog):
    token = create_access_token("client-1", {"org_id": "org-42"})
    client = TestClient(_small_app(), cookies={"access_token": token})
    with caplog.at_level(logging.INFO, logger="clew.api"):
        res = client.get("/denied")
    assert res.status_code == 403
    assert res.json() == {"detail": "No active organisation"}
    corr = res.headers["x-correlation-id"]
    lines = [r.getMessage() for r in caplog.records if r.name == "clew.api"]
    assert any(corr in line and "status=403" in line and "org=org-42" in line for line in lines)


def test_success_is_not_logged(caplog):
    client = TestClient(_small_app())
    with caplog.at_level(logging.INFO, logger="clew.api"):
        client.get("/ok")
    assert [r for r in caplog.records if r.name == "clew.api"] == []


def test_forged_token_gives_no_org(caplog):
    client = TestClient(_small_app(), cookies={"access_token": "not-a-jwt"})
    with caplog.at_level(logging.INFO, logger="clew.api"):
        client.get("/denied")
    lines = [r.getMessage() for r in caplog.records if r.name == "clew.api"]
    assert any("org=None" in line for line in lines)


def test_unhandled_exception_becomes_json_500_with_id(caplog):
    client = TestClient(_small_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="clew.api"):
        res = client.get("/boom")
    assert res.status_code == 500
    body = res.json()
    assert body["correlation_id"] == res.headers["x-correlation-id"]
    assert "kaboom" not in res.text
    assert any(body["correlation_id"] in r.getMessage() for r in caplog.records)
