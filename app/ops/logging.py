"""Structured JSON logging with PII redaction (spec §19.2, §17.8; BR #13).

Every record becomes one JSON line::

    {"ts": "2026-09-14T08:00:00.123Z", "level": "INFO", "logger": "elchi.api",
     "message": "...", "request_id": "...", "actor_id": 42, "error_code": "NOT_FOUND"}

* ``request_id`` / ``actor_id`` come from context variables set by
  :mod:`app.ops.request_id` and :func:`bind_actor_id`; ``error_code`` from
  ``logger.x(..., extra={"error_code": ...})``.
* :class:`RedactionFilter` scrubs phone numbers, Uzbek passport numbers, JWTs,
  bearer tokens, and secret query parameters (``sig``, ``exp``, ``token``, ``otp`` ...)
  from the message, exception text and string extras, before any handler sees them.

This module imports nothing from ``app`` so uvicorn can load it from
``--log-config app/ops/uvicorn_log_config.json`` before the application starts.
Response bodies and v1 behaviour are untouched: this only changes log output.
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.config
import os
import re
from datetime import UTC, datetime
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("elchi_request_id", default=None)
actor_id_var: contextvars.ContextVar[int | str | None] = contextvars.ContextVar("elchi_actor_id", default=None)


def bind_actor_id(actor_id: int | str | None) -> None:
    """Call once the caller is authenticated (e.g. in ``get_current_user``)."""
    actor_id_var.set(actor_id)


# ── redaction ────────────────────────────────────────────────────────────────

_SECRET_QUERY_KEYS = "sig|exp|signature|token|access_token|refresh_token|otp|code|password|api_key|apikey|key"
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # JWTs (three base64url parts, header starts with {" -> eyJ)
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), "[jwt]"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [token]"),
    # secret query parameters in URLs and access-log lines
    (re.compile(rf"(?i)([?&](?:{_SECRET_QUERY_KEYS})=)[^&\s\"'#]*"), r"\1[redacted]"),
    # key=value / "key": "value" pairs for obviously secret fields
    (
        re.compile(r"(?i)([\"']?(?:password|passport(?:_number)?|otp|secret|token)[\"']?\s*[:=]\s*[\"']?)[^\"',\s}&]+"),
        r"\1[redacted]",
    ),
    # Uzbek phone numbers: +998 XX XXX XX XX with optional separators, or bare 998XXXXXXXXX
    (re.compile(r"(?<![\w+])\+?998[\s-]?\(?\d{2}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)"), "[phone]"),
    # Uzbek passport / ID card series: two letters + seven digits
    (re.compile(r"\b[A-Z]{2}\s?\d{7}\b"), "[passport]"),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


_SECRET_KEY_NAMES = re.compile(
    r"(?i)^(password|passwd|secret|token|access_token|refresh_token|otp|code|sig|signature|exp|api_?key|"
    r"authorization|cookie|passport(_number)?|phone(_number)?)$"
)
_MAX_DEPTH = 6


def redact_value(value: Any, _depth: int = 0) -> Any:
    """Recursively redact strings inside dicts, lists, tuples and sets (BR N9).

    Values under obviously secret keys (``password``, ``token``, ``phone`` ...) are replaced
    entirely; other strings go through :func:`redact`. Depth is bounded; anything deeper or of an
    unknown type is converted with ``str`` and redacted, so nothing escapes unredacted.
    """
    if isinstance(value, str):
        return redact(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if _depth >= _MAX_DEPTH:
        return redact(str(value))
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY_NAMES.match(key) and item not in (None, "", [], {}):
                out[key] = "[redacted]"
            else:
                out[key] = redact_value(item, _depth + 1)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_value(item, _depth + 1) for item in value]
    return redact(str(value))


_RESERVED = frozenset(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime", "taskName"}


class RedactionFilter(logging.Filter):
    """Resolve %-args, then redact message, exception text and string extras in place."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never lose a log line because of bad args
            message = str(record.msg)
        record.msg = redact(message)
        record.args = ()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        for key, value in list(vars(record).items()):
            if key not in _RESERVED:
                if _SECRET_KEY_NAMES.match(key) and value not in (None, "", [], {}):
                    setattr(record, key, "[redacted]")
                else:
                    setattr(record, key, redact_value(value))
        return True


# ── formatting ───────────────────────────────────────────────────────────────


class JsonFormatter(logging.Formatter):
    """One JSON object per line; safe for any extra values (falls back to ``str``)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "actor_id": actor_id_var.get(),
            "error_code": getattr(record, "error_code", None),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(self.formatException(record.exc_info))
        if record.exc_text:
            payload["exc"] = record.exc_text
        return json.dumps(payload, ensure_ascii=False, default=str)


def logging_config(level: str | None = None) -> dict[str, Any]:
    """dictConfig for API (uvicorn) and worker. Level from ``ELCHI_LOG_LEVEL`` (default INFO)."""
    level = (level or os.environ.get("ELCHI_LOG_LEVEL") or "INFO").upper()
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"redact": {"()": "app.ops.logging.RedactionFilter"}},
        "formatters": {"json": {"()": "app.ops.logging.JsonFormatter"}},
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json",
                "filters": ["redact"],
            }
        },
        "loggers": {
            "uvicorn": {"handlers": ["stdout"], "level": level, "propagate": False},
            "uvicorn.error": {"handlers": ["stdout"], "level": level, "propagate": False},
            "uvicorn.access": {"handlers": ["stdout"], "level": level, "propagate": False},
        },
        "root": {"handlers": ["stdout"], "level": level},
    }


def configure_logging(level: str | None = None) -> None:
    logging.config.dictConfig(logging_config(level))
