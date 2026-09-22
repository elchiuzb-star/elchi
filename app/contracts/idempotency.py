"""Idempotency-Key helpers (spec §14.2, §15, ADR-0005).

The record key is ``(actor_id, method + route_template, idempotency_key)``.
The request hash covers method, route template, path parameters and the
canonical JSON body, so reusing a key for another object or another body is
detected and answered with ``409 IDEMPOTENCY_KEY_REUSED``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from app.contracts.errors import DomainError, ErrorCode

IDEMPOTENCY_HEADER = "Idempotency-Key"
IDEMPOTENT_REPLAY_HEADER = "Idempotent-Replayed"
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:\-]{8,128}$")
# Records stay replayable for this long; after it the key may be reused.
IDEMPOTENCY_RECORD_TTL = timedelta(hours=24)


def validate_idempotency_key(value: str | None) -> str:
    if value is None or value == "":
        raise DomainError(ErrorCode.IDEMPOTENCY_KEY_REQUIRED)
    if not isinstance(value, str) or not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        raise DomainError(
            ErrorCode.IDEMPOTENCY_KEY_INVALID,
            details={"pattern": IDEMPOTENCY_KEY_PATTERN.pattern},
        )
    return value


def canonical_json(value: Any) -> bytes:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8, no NaN/Infinity."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def request_hash(
    method: str,
    route_template: str,
    body: Any,
    path_params: Mapping[str, Any] | None = None,
) -> str:
    """SHA-256 hex digest identifying the semantic request.

    ``body`` must be the parsed JSON body (``None`` when absent), not raw bytes,
    so whitespace or key order differences do not count as a different request.
    """
    if not method or not route_template:
        raise ValueError("method and route_template are required")
    envelope = {
        "method": method.upper(),
        "route": route_template,
        "path": dict(path_params or {}),
        "body": body,
    }
    return hashlib.sha256(canonical_json(envelope)).hexdigest()


def record_scope(method: str, route_template: str) -> str:
    """Value stored in ``idempotency_records.route`` next to actor and key."""
    return f"{method.upper()} {route_template}"
