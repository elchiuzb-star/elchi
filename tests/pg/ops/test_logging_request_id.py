"""BR #13: JSON logs with PII redaction, uvicorn log config, request-id middleware (no Docker)."""

from __future__ import annotations

import io
import json
import logging
import logging.config
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ops import logging as ops_logging
from app.ops.request_id import RequestIdMiddleware

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("raw", "must_not_contain", "must_contain"),
    [
        ("GET /api/v1/files/doc.pdf?exp=1789999999&sig=AbCdEf123&x=1", ["1789999999", "AbCdEf123"], ["x=1", "sig=[redacted]"]),
        ("otp sent to +998 90 123 45 67", ["123 45 67"], ["[phone]"]),
        ("login 998901234567 ok", ["998901234567"], ["[phone]"]),
        ("passport AB1234567 uploaded", ["AB1234567"], ["[passport]"]),
        ("Authorization: Bearer abc.def-ghi_jkl", ["abc.def-ghi_jkl"], ["Bearer [token]"]),
        ("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sgn_part", ["eyJzdWIiOiIxIn0"], ["[jwt]"]),
        ('{"password": "hunter22", "phone_verified": true}', ["hunter22"], ["[redacted]"]),
        ("order 20260914-000123 created, 400000 som", [], ["20260914-000123", "400000"]),
    ],
)
def test_redact(raw: str, must_not_contain: list[str], must_contain: list[str]) -> None:
    out = ops_logging.redact(raw)
    for needle in must_not_contain:
        assert needle not in out, out
    for needle in must_contain:
        assert needle in out, out


def _capture_logger(name: str) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(ops_logging.JsonFormatter())
    handler.addFilter(ops_logging.RedactionFilter())
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger, stream


def test_json_record_has_context_fields_and_redacts_args_and_extras() -> None:
    logger, stream = _capture_logger("elchi.test.json")
    rid = ops_logging.request_id_var.set("req-12345678")
    aid = ops_logging.actor_id_var.set(42)
    try:
        logger.info('%s - "GET %s HTTP/1.1" %d', "10.0.0.1:5000", "/api/v1/files/k?exp=1&sig=SECRET", 200,
                    extra={"error_code": "NOT_FOUND", "phone": "+998901234567"})
        try:
            raise ValueError("user +998901112233 failed")
        except ValueError:
            logger.exception("boom")
    finally:
        ops_logging.request_id_var.reset(rid)
        ops_logging.actor_id_var.reset(aid)
    first, second = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert first["request_id"] == "req-12345678" and first["actor_id"] == 42
    assert first["error_code"] == "NOT_FOUND"
    assert first["ts"].endswith("Z") and first["level"] == "INFO" and first["logger"] == "elchi.test.json"
    assert "SECRET" not in first["message"] and "sig=[redacted]" in first["message"]
    assert first["phone"] == "[redacted]", "secret-named extras are replaced wholesale (N9)"
    assert "+998901112233" not in second["exc"] and "[phone]" in second["exc"]


def test_dict_and_nested_extras_are_redacted_recursively() -> None:
    """BR N9: dict/list extras (e.g. request payloads) must not leak PII or secrets."""
    logger, stream = _capture_logger("elchi.test.nested")
    payload = {
        "user": {"phone": "+998901234567", "name": "Ali", "contacts": ["call 998901112233", {"passport": "AB1234567"}]},
        "url": "/api/v1/files/k?exp=1789999999&sig=NESTEDSECRET",
        "headers": {"Authorization": "Bearer abcdef.ghijkl-mnop", "X-Trace": "ok"},
        "password": "hunter22",
        "amount_minor": 40000000,
        "deep": [[[[[[["+998907654321"]]]]]]],
        "tags": ("otp=5555", "fine"),
    }
    logger.info("payload received", extra={"payload": payload, "token": "raw-top-level-token-value"})
    record = json.loads(stream.getvalue())
    text = json.dumps(record)
    for leaked in ("998901234567", "998901112233", "AB1234567", "NESTEDSECRET", "1789999999", "abcdef.ghijkl",
                   "hunter22", "raw-top-level-token-value", "998907654321", "5555"):
        assert leaked not in text, leaked
    body = record["payload"]
    assert body["user"]["phone"] == "[redacted]"
    assert body["user"]["name"] == "Ali"
    assert body["user"]["contacts"][0] == "call [phone]"
    assert body["user"]["contacts"][1] == {"passport": "[redacted]"}
    assert body["headers"] == {"Authorization": "[redacted]", "X-Trace": "ok"}
    assert body["amount_minor"] == 40000000, "numbers are not touched"
    assert record["token"] == "[redacted]"
    assert payload["password"] == "hunter22", "the caller's object is not mutated"


def test_redact_value_handles_odd_types_without_leaking() -> None:
    class Weird:
        def __str__(self) -> str:
            return "contact +998901234567"

    out = ops_logging.redact_value({"obj": Weird(), "set": {"/f?sig=ABC"}, "none": None, "empty_token": ""})
    assert out == {"obj": "contact [phone]", "set": ["/f?sig=[redacted]"], "none": None, "empty_token": ""}


def test_uvicorn_log_config_file_loads_and_matches_python_config() -> None:
    config = json.loads((REPO_ROOT / "app/ops/uvicorn_log_config.json").read_text(encoding="utf-8"))
    python_config = ops_logging.logging_config("INFO")
    assert config["filters"] == python_config["filters"]
    assert config["formatters"] == python_config["formatters"]
    assert set(config["loggers"]) == set(python_config["loggers"])
    saved = logging.root.handlers[:]
    try:
        logging.config.dictConfig(config)
        handler = logging.getLogger("uvicorn.access").handlers[0]
        assert isinstance(handler.formatter, ops_logging.JsonFormatter)
        assert any(isinstance(f, ops_logging.RedactionFilter) for f in handler.filters)
    finally:
        logging.root.handlers = saved


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/echo")
    def echo() -> dict[str, str | None]:
        return {"request_id": ops_logging.request_id_var.get()}

    app.add_middleware(RequestIdMiddleware)
    return app


def test_request_id_is_echoed_when_valid() -> None:
    response = TestClient(_app()).get("/echo", headers={"X-Request-ID": "abc-12345_XYZ"})
    assert response.headers["x-request-id"] == "abc-12345_XYZ"
    assert response.json() == {"request_id": "abc-12345_XYZ"}


@pytest.mark.parametrize("bad", ["short", "has space 123456", "x" * 65, "evil\xe9latin1-12345", "inject}{\"level\":1"])
def test_invalid_request_id_is_replaced(bad: str) -> None:
    response = TestClient(_app()).get("/echo", headers={"X-Request-ID": bad.encode("latin-1")})
    rid = response.headers["x-request-id"]
    assert rid != bad and len(rid) == 32
    assert response.json() == {"request_id": rid}


def test_request_id_generated_and_context_reset_after_request() -> None:
    client = TestClient(_app())
    first = client.get("/echo").headers["x-request-id"]
    second = client.get("/echo").headers["x-request-id"]
    assert first != second and len(first) == 32
    assert ops_logging.request_id_var.get() is None


def test_v1_response_body_and_status_unchanged_by_middleware() -> None:
    from app.main import app as real_app

    plain = TestClient(real_app).get("/api/v1/health")
    wrapped = TestClient(RequestIdMiddleware(real_app)).get("/api/v1/health")
    assert (plain.status_code, plain.json()) == (wrapped.status_code, wrapped.json()) == (200, {"success": True, "message": "OK"})
    assert "x-request-id" in wrapped.headers
    for header in ("referrer-policy", "x-content-type-options", "x-frame-options"):
        assert plain.headers[header] == wrapped.headers[header]
