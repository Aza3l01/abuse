"""Correlation ids for support.

Every HTTP request gets a fresh id, returned in the `X-Correlation-Id` response
header. Error responses (status 400 and above) and unhandled exceptions are
logged with that id, the method, the path, the status and the org id, so a
customer who quotes the id from the dashboard can be matched to one log line.

The id is always generated here. A client-supplied value is never trusted,
because it would land in the logs verbatim.

Response bodies are not changed, with one exception: an unhandled exception
becomes a JSON 500 with `detail` and `correlation_id`, instead of the plain
text "Internal Server Error", so the dashboard can show the id.
"""
from __future__ import annotations

import json
import logging
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api import analytics
from api.auth_utils import decode_access_token

logger = logging.getLogger("clew.api")

CORRELATION_HEADER = "x-correlation-id"


def _org_id_from_scope(scope: Scope) -> str | None:
    """Org id claim from the access_token cookie, or None. The token is decoded
    and verified, never trusted unverified. No database access."""
    for name, value in scope.get("headers", []):
        if name != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            key, _, token = part.strip().partition("=")
            if key == "access_token" and token:
                payload = decode_access_token(token)
                if payload:
                    return payload.get("org_id")
    return None


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = uuid.uuid4().hex
        status_code = 0
        started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status_code, started
            if message["type"] == "http.response.start":
                started = True
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((CORRELATION_HEADER.encode(), correlation_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            logger.exception(
                "unhandled error corr=%s %s %s org=%s",
                correlation_id,
                scope.get("method"),
                scope.get("path"),
                _org_id_from_scope(scope),
            )
            # Phase 11: error tracking. The route template (never the raw path,
            # which can hold an id or token) and the correlation id are the only
            # request details sent.
            route = scope.get("route")
            analytics.capture_exception(
                exc,
                {
                    "source": "api",
                    "method": scope.get("method"),
                    "route": getattr(route, "path", None) or "unmatched",
                    "correlation_id": correlation_id,
                },
            )
            if started:
                raise
            body = json.dumps(
                {
                    "detail": "Something went wrong on our side.",
                    "correlation_id": correlation_id,
                }
            ).encode()
            status_code = 500
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (CORRELATION_HEADER.encode(), correlation_id.encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        if status_code >= 400:
            # 401 is routine (silent token refresh), so it stays at INFO.
            level = logging.INFO if status_code == 401 else logging.WARNING
            logger.log(
                level,
                "request failed corr=%s %s %s status=%s org=%s",
                correlation_id,
                scope.get("method"),
                scope.get("path"),
                status_code,
                _org_id_from_scope(scope),
            )
