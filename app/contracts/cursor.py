"""Opaque, signed keyset-pagination cursors (spec §13, ADR-0005).

A cursor carries the sort-key values of the last returned row plus a stable
tie-breaker (the row's internal id), e.g. ``[score, "2026-09-13T07:45:00Z", 42]``.
It is signed with HMAC-SHA256 over the payload *and* a query scope string
(endpoint + normalised filters), so a cursor from one query cannot be replayed
against another. Clients must treat cursors as opaque strings.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Sequence

from app.contracts.errors import DomainError, ErrorCode

CURSOR_VERSION = 1
MAX_CURSOR_LENGTH = 512
_MAC_BYTES = 16

CursorValue = str | int | bool | None


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _mac(payload: bytes, scope: str, secret: bytes) -> bytes:
    message = scope.encode("utf-8") + b"\x00" + payload
    return hmac.new(secret, message, hashlib.sha256).digest()[:_MAC_BYTES]


def _check_values(values: Sequence[CursorValue]) -> list[CursorValue]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values:
        raise ValueError("cursor values must be a non-empty sequence")
    for item in values:
        if item is not None and not isinstance(item, (str, int, bool)):
            raise TypeError("cursor values must be str, int, bool or None (serialize datetimes with to_iso_utc)")
        if isinstance(item, float):  # pragma: no cover - float is not int/str/bool
            raise TypeError("float cursor values are not allowed")
    return list(values)


def encode_cursor(values: Sequence[CursorValue], *, scope: str, secret: bytes) -> str:
    if not secret:
        raise ValueError("secret is required")
    payload = json.dumps(
        {"v": CURSOR_VERSION, "k": _check_values(values)},
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    token = f"{_b64encode(payload)}.{_b64encode(_mac(payload, scope, secret))}"
    if len(token) > MAX_CURSOR_LENGTH:
        raise ValueError("cursor too long; reduce sort keys")
    return token


def decode_cursor(token: str, *, scope: str, secret: bytes) -> list[CursorValue]:
    invalid = DomainError(ErrorCode.INVALID_CURSOR)
    if not secret:
        raise ValueError("secret is required")
    if not isinstance(token, str) or not token or len(token) > MAX_CURSOR_LENGTH or token.count(".") != 1:
        raise invalid
    payload_part, mac_part = token.split(".")
    try:
        payload = _b64decode(payload_part)
        mac = _b64decode(mac_part)
    except (ValueError, TypeError):
        raise invalid from None
    if not hmac.compare_digest(mac, _mac(payload, scope, secret)):
        raise invalid
    try:
        data = json.loads(payload)
    except ValueError:
        raise invalid from None
    if not isinstance(data, dict) or data.get("v") != CURSOR_VERSION or not isinstance(data.get("k"), list) or not data["k"]:
        raise invalid
    return data["k"]
