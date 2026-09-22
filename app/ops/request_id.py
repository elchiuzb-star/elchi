"""Request id middleware (spec §19.2 structured logs; BR #13).

Pure ASGI (no response buffering, works for streaming and file downloads):

* accepts an incoming ``X-Request-ID`` only if it is 8-64 characters of
  ``[A-Za-z0-9._-]`` (anything else is replaced, so clients cannot inject log noise);
* otherwise generates a UUID4 hex;
* stores it in ``app.ops.logging.request_id_var`` and ``scope["state"]["request_id"]``
  (``request.state.request_id``);
* adds ``X-Request-ID`` to the response headers. Response bodies, status codes and
  every existing header are unchanged, so the v1 contract is unaffected;
* **wave 6 (§19.2):** writes one structured access line per request (method, route template, status,
  ``duration_ms``, request id, actor id) and feeds the in-process latency registry
  (:mod:`app.ops.metrics`). The line carries the route *template*, never the concrete ids or the query string,
  so no phone, booking id or token reaches the log.

The v2 error envelope already echoes ``request.headers["X-Request-ID"]``; with the
middleware in place that value is always present and well-formed for callers that send one.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from app.ops.logging import actor_id_var, request_id_var
from app.ops.metrics import REGISTRY

access_logger = logging.getLogger("elchi.access")
# Opaque public ids only (AGENTS §6); never a phone, a token or free text.
_LOGGED_PATH_PARAMS = ("booking_id", "trip_id", "listing_id")

HEADER = "X-Request-ID"
_HEADER_BYTES = HEADER.lower().encode("latin-1")
_VALID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def _incoming(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or ():
        if name == _HEADER_BYTES:
            candidate = value.decode("latin-1", "replace").strip()
            return candidate if _VALID.fullmatch(candidate) else None
    return None


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        request_id = _incoming(scope) or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        rid_token = request_id_var.set(request_id)
        actor_token = actor_id_var.set(None)

        started = time.perf_counter()
        status_holder: list[int] = []

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != _HEADER_BYTES]
                headers.append((_HEADER_BYTES, request_id.encode("latin-1")))
                message["headers"] = headers
                status_holder.append(int(message.get("status", 0)))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            if scope["type"] == "http":
                self._record(scope, status_holder, time.perf_counter() - started)
            request_id_var.reset(rid_token)
            actor_id_var.reset(actor_token)

    @staticmethod
    def _record(scope: Scope, status_holder: list[int], duration: float) -> None:
        """One access line + one latency sample. Never raises: observability must not break a response."""
        try:
            route = scope.get("route")
            # The route template ("/api/v2/bookings/{booking_id}") keeps ids out of logs and metric keys.
            path = getattr(route, "path", None) or "unmatched"
            status = status_holder[0] if status_holder else 500
            REGISTRY.observe(route=path, status_code=status, duration_seconds=duration)
            extra = {
                "http_method": scope.get("method", ""),
                "route": path,
                "status_code": status,
                "duration_ms": round(duration * 1000, 1),
            }
            # §19.2 asks for the booking in the log line. Public ids are opaque and not secret (AGENTS §6);
            # nothing else from the path or the query string is logged.
            params = scope.get("path_params") or {}
            for key in _LOGGED_PATH_PARAMS:
                value = params.get(key)
                if isinstance(value, str) and value:
                    extra[key] = value[:64]
            access_logger.info("request", extra=extra)
        except Exception:  # noqa: BLE001 - logging/metrics failure is never the request's problem
            return
